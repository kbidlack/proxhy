import asyncio
import os
import pickle
import sys
import time
from pathlib import Path

import aiohttp
import hypixel
import quarry
from appdirs import user_cache_dir
from dotenv import load_dotenv
from hypixel.aliases import GUILD, PLAYER, STATUS
from hypixel.errors import HypixelException
from hypixel.game import Game
from hypixel.models import Player
from quarry.net.proxy import Downstream, Upstream
from quarry.types import chat
from quarry.types.buffer import Buffer1_7, BufferUnderrun
from twisted.internet import reactor
from twisted.python import threadable


class Client:
    """Synchronous wrapper for hypixel.Client that supports caching across program runs"""

    def __init__(self):
        load_dotenv()
        if not os.environ.get("HYPIXEL_API_KEY"):
            print("Please put your Hypixel API Key in .env file")
            sys.exit()

        self.api_key = os.environ.get("HYPIXEL_API_KEY")

        # load cached info
        self.cache_dir = Path(user_cache_dir("proxhy"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.cache_path = self.cache_dir / Path("players.pkl")
        if self.cache_path.exists():
            with open(self.cache_path, "rb") as cache_file:
                self.cached_data = pickle.load(cache_file)
        else:
            self.cached_data = {}

            with open(self.cache_path, "wb") as cache_file:
                pickle.dump(self.cached_data, cache_file)

    def cache_data(self):
        with open(self.cache_path, "wb") as cache_file:
            pickle.dump(self.cached_data, cache_file)

    @staticmethod
    def _clean(data: dict, mode: str) -> dict:
        # alias = globals()[mode]
        if mode == "GUILD":
            alias = GUILD
        elif mode == "PLAYER":
            alias = PLAYER
        elif mode == "STATUS":
            alias = STATUS

        if mode == "PLAYER":
            # Avoid name conflicts
            data["achievement_stats"] = data.pop("achievements", {})

        # Deprecated by Hypixel
        # elif mode == 'FRIEND':
        #     # Sender and receiver could be either the player or the friend
        #     # as the api stores the sender and receiver of the actual friend
        #     # request.
        #     # Extra is the player's uuid.
        #     if data['uuidReceiver'] == extra:
        #         data['uuidReceiver'] = data['uuidSender']

        elif mode == "STATUS":
            data["gameType"] = Game.from_type(data.get("gameType"))

        elif mode == "GUILD":
            achievements = data.get("achievements", {})
            data["winners"] = achievements.get("WINNERS")
            data["experience_kings"] = achievements.get("EXPERIENCE_KINGS")
            data["most_online_players"] = achievements.get("ONLINE_PLAYERS")

        # Replace keys in data with formatted alias
        # Remove items that are not in the alias dictionary
        return {alias.get(k, k): v for k, v in data.items() if k in alias.keys()}

    async def players_async(self, *usernames: str) -> list[Player]:
        """Call hypixel async player method with a new client"""
        client = hypixel.Client(self.api_key)

        # disable ssl cuz that was causing a problem I guess
        await client._session.close()
        client._session = aiohttp.ClientSession(
            loop=client.loop,
            timeout=aiohttp.ClientTimeout(total=client.timeout),
            connector=aiohttp.TCPConnector(ssl=False),
        )

        async with client:
            tasks = []
            for username in usernames:
                tasks.append(asyncio.create_task(client.player(username)))

            players = await asyncio.gather(*tasks, return_exceptions=True)
        return players

    def players(self, *usernames: str) -> list[Player]:
        players = []
        players_to_request = []

        for username in usernames:
            # check if player data is cached and not outdated
            cached_player = self.cached_data.get(username.lower())
            if (
                cached_player
                and (time.monotonic() - cached_player.data_gen_time) < 3600
            ):
                players.append(cached_player)
            else:
                players_to_request.append(username)

        requested_players: list = asyncio.run(self.players_async(*players_to_request))
        for player in requested_players:
            if isinstance(player, HypixelException):
                players.append(player)
                continue
            # cache data
            player.data_gen_time = time.monotonic()
            # call from thread otherwise dictionary changes size during iteration
            reactor.callFromThread(
                self.cached_data.update, {player.name.lower(): player}
            )
            reactor.callFromThread(self.cache_data)

            players.append(player)

        return players

    def player(self, username: str) -> Player:
        return self.players(username)[0]


def data_received(self, data):
    # Decrypt data
    data = self.cipher.decrypt(data)

    # Add it to our buffer
    self.recv_buff.add(data)

    # Read some packets
    while not self.closed:
        # Save the buffer, in case we read an incomplete packet
        self.recv_buff.save()

        # Read the packet
        try:
            buff = self.recv_buff.unpack_packet(
                self.buff_type, self.compression_threshold
            )

        except BufferUnderrun:
            self.recv_buff.restore()
            break

        try:
            # Identify the packet
            name = self.get_packet_name(buff.unpack_varint())

            # Dispatch the packet
            try:
                self.packet_received(buff, name)
            except BufferUnderrun:
                raise quarry.net.protocol.ProtocolError(
                    "Packet is too short: %s" % name
                )

            # Reset the inactivity timer
            self.connection_timer.restart()

        except quarry.net.protocol.ProtocolError as e:
            self.protocol_error(e)


def pack_chat(message: str, _type: int = 0):
    # downstream chat packing works differently from upstream
    # see https://wiki.vg/index.php?title=Protocol&oldid=7368#Chat_Message for types
    # 0: chat (chat box), 1: system message (chat box), 2: above hotbar
    message = chat.Message.from_string(message)

    if _type == 0:
        byte = b"\x00"  # chat box
    elif _type == 1:
        byte = b"\x01"  # system message (chat box)
    elif _type == 2:
        byte = b"\x02"  # above hotbar
    return message.to_bytes() + byte


def upstream_send_chat(self, *data):
    packed_data = [Buffer1_7().pack_string(item) for item in data]
    return self.send_packet("chat_message", *packed_data)


def downstream_send_chat(self, *data):
    packed_data = [pack_chat(item) for item in data]
    return self.send_packet("chat_message", *packed_data)


# thread safe (?) packet sending
def send_packet(self, name, *data):
    if isinstance(self, Downstream):
        kind = Downstream
    else:
        kind = Upstream
    send = lambda: kind.send_packet(self, name, *data)

    if not threadable.isInIOThread():
        return reactor.callFromThread(send)
    return send()
