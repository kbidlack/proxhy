import asyncio
import json
import pathlib
import time
from uuid import UUID

import hypixel
import quarry
from hypixel.aliases import GUILD, PLAYER, STATUS
from hypixel.game import Game
from hypixel.models import Player
from quarry.types import chat
from quarry.types.buffer import BufferUnderrun


class Client():
    """Synchronous wrapper for hypixel.Client that supports caching across program runs"""
    def __init__(self, api_key):
        self.api_key = api_key
        
        # load cached info
        dir = __file__[:__file__.rfind('/')]
        self.cache_path = dir / pathlib.Path('proxhy_cache.json')
        if self.cache_path.exists():
            with open(self.cache_path, 'r') as cache_file:
                self.cached_data = json.load(cache_file)
        else:
            self.cached_data = {}

            with open(self.cache_path, 'w') as cache_file:
                json.dump(self.cached_data, cache_file)

    @staticmethod
    def _clean(data: dict, mode: str) -> dict:
        alias = globals()[mode]

        if mode == 'PLAYER':
            # Avoid name conflicts
            data['achievement_stats'] = data.pop('achievements', {})

        # Deprecated by Hypixel
        # elif mode == 'FRIEND':
        #     # Sender and receiver could be either the player or the friend
        #     # as the api stores the sender and receiver of the actual friend
        #     # request.
        #     # Extra is the player's uuid.
        #     if data['uuidReceiver'] == extra:
        #         data['uuidReceiver'] = data['uuidSender']

        elif mode == 'STATUS':
            data['gameType'] = Game.from_type(data.get('gameType'))

        elif mode == 'GUILD':
            achievements = data.get('achievements', {})
            data['winners'] = achievements.get('WINNERS')
            data['experience_kings'] = achievements.get('EXPERIENCE_KINGS')
            data['most_online_players'] = achievements.get('ONLINE_PLAYERS')

        # Replace keys in data with formatted alias
        # Remove items that are not in the alias dictionary
        return {alias.get(k, k): v for k, v in data.items() if k in alias.keys()}

    async def player_async(self, *usernames: str) -> list[Player]:
        """Call hypixel async player method with a new client""" 
        client = hypixel.Client(self.api_key)
        async with client:
            tasks = []
            for username in usernames:
                tasks.append(asyncio.create_task(client.player(username)))

            players = await asyncio.gather(*tasks)
        return players

    def player(self, *usernames: str) -> list[Player]:
        players = []
        players_to_request = []

        for username in usernames:
            # check if player data is cached and not outdated
            cached_data = self.cached_data.get(username.lower())
            if cached_data and (time.monotonic() - float(cached_data['_time'])) < 3600:
                data = {
                    'raw': cached_data,
                    '_data': cached_data['player']
                }
                clean_data = self._clean(cached_data['player'], mode='PLAYER')
                data.update(clean_data)
                players.append(Player(**data))
            else:
                players_to_request.append(username)

        requested_players: list = asyncio.run(self.player_async(*players_to_request)) 
        for player in requested_players:
            # cache data
            data = player.raw
            # if this is not here, causes a circular reference
            # because for some reason the last stats has a "..."
            # which throws an error
            try:
                del data['player']['stats']['Arcade']['_data']['stats']
            except KeyError:
                pass
            # cache data
            data.update({'_time': str(time.monotonic())})
            self.cached_data.update({player.name.lower(): player.raw})
            with open(self.cache_path, 'w') as cache_file:
                json.dump(self.cached_data, cache_file, indent=4)

            players.append(player)

        return players


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
                        self.buff_type,
                        self.compression_threshold)

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
                        raise quarry.net.protocol.ProtocolError("Packet is too short: %s" % name)

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
        byte = b'\x00' # chat box
    elif _type == 1:
        byte = b'\x01' # system message (chat box)
    elif _type == 2:
        byte = b'\x02' # above hotbar
    return message.to_bytes() + byte
