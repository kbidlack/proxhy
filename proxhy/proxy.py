import asyncio
import base64
import json
import re
import uuid
from pathlib import Path
from secrets import token_bytes

import aiohttp
import hypixel
from hypixel.errors import (
    HypixelException,
    InvalidApiKey,
    PlayerNotFound,
    RateLimitError,
)

from .aliases import Gamemode, Statistic
from .auth import load_auth_info
from .client import Client, State, listen_client, listen_server
from .command import command, commands
from .datatypes import (
    UUID,
    Boolean,
    Buffer,
    Byte,
    ByteArray,
    Chat,
    Long,
    String,
    UnsignedShort,
    VarInt,
)
from .encryption import Stream, generate_verification_hash, pkcs1_v15_padded_rsa_encrypt
from .errors import CommandException
from .formatting import FormattedPlayer
from .models import Game, Team, Teams


class ProxyClient(Client):
    # load favicon
    # https://github.com/barneygale/quarry/blob/master/quarry/net/server.py/#L356-L357
    favicon_path = Path(__file__).parent.resolve() / "assets" / "favicon.png"
    with open(favicon_path, "rb") as file:
        b64_favicon = base64.encodebytes(file.read()).decode("ascii").replace("\n", "")

    server_list_ping = {
        "version": {"name": "1.8.9", "protocol": 47},
        "players": {
            "max": 1,
            "online": 0,
        },
        "description": {"text": "Proxhy"},
        "favicon": f"data:image/png;base64,{b64_favicon}",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.client = ""
        self.hypixel_client = None

        self.game = Game()
        self.rq_game = Game()

        self.players: dict[str, str] = {}
        self.players_getting_stats = []
        self.players_with_stats = {}
        self.teams: list[Team] = Teams()

        self.waiting_for_locraw = False

    async def close(self):
        if self.server_stream:
            self.server_stream.close()
        if self.hypixel_client:
            await self.hypixel_client.close()
        self.client_stream.close()

        del self  # idk if this does anything or not
        # on second thought probably not but whatever

    @listen_client(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self, _):
        self.send_packet(
            self.client_stream, 0x00, String.pack(json.dumps(self.server_list_ping))
        )

    @listen_client(0x00, State.HANDSHAKING, blocking=True)
    async def packet_handshake(self, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        assert buff.unpack(VarInt) == 47  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)
        if self.state == State.LOGIN:
            reader, writer = await asyncio.open_connection("mc.hypixel.net", 25565)
            self.server_stream = Stream(reader, writer)
            asyncio.create_task(self.handle_server())

            self.send_packet(
                self.server_stream,
                0x00,
                VarInt.pack(47),
                String.pack("mc.hypixel.net"),
                UnsignedShort.pack(25565),
                VarInt.pack(State.LOGIN.value),
            )

    @listen_client(0x01, State.STATUS, blocking=True)
    async def packet_ping_request(self, buff: Buffer):
        payload = buff.unpack(Long)
        self.send_packet(self.client_stream, 0x01, Long.pack(payload))
        # close connection
        await self.close()

    @listen_client(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        (
            self.access_token,
            self.username,
            self.uuid,
            self.hypixel_api_key,
        ) = await load_auth_info()

        while not self.server_stream:
            await asyncio.sleep(0.01)

        self.username = buff.unpack(String)
        self.send_packet(self.server_stream, 0x00, String.pack(self.username))

    @listen_server(0x01, State.LOGIN, blocking=True)
    async def packet_encryption_request(self, buff: Buffer):
        server_id = buff.unpack(String).encode("utf-8")
        public_key = buff.unpack(ByteArray)
        verify_token = buff.unpack(ByteArray)

        # generate shared secret
        secret = token_bytes(16)
        payload = {
            "accessToken": self.access_token,
            "selectedProfile": self.uuid,
            "serverId": generate_verification_hash(server_id, secret, public_key),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://sessionserver.mojang.com/session/minecraft/join",
                json=payload,
                ssl=False,
            ) as response:
                if not response.status == 204:
                    raise Exception(
                        f"Login failed: {response.status} {await response.json()}"
                    )

        encrypted_secret = pkcs1_v15_padded_rsa_encrypt(public_key, secret)
        encrypted_verify_token = pkcs1_v15_padded_rsa_encrypt(public_key, verify_token)

        self.send_packet(
            self.server_stream,
            0x01,
            ByteArray.pack(encrypted_secret),
            ByteArray.pack(encrypted_verify_token),
        )

        # enable encryption
        self.server_stream.key = secret

    @listen_server(0x02, State.LOGIN, blocking=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.hypixel_client = hypixel.Client(self.hypixel_api_key)
        self.send_packet(self.client_stream, 0x02, buff.read())

    @listen_server(0x03, State.LOGIN, blocking=True)
    async def packet_set_compression(self, buff: Buffer):
        self.compression_threshold = buff.unpack(VarInt)
        self.compression = False if self.compression_threshold == -1 else True

    @listen_client(0x17)
    async def packet_plugin_channel(self, buff: Buffer):
        self.send_packet(self.server_stream, 0x17, buff.getvalue())

        channel = buff.unpack(String)
        data = buff.unpack(ByteArray)
        if channel == "MC|Brand":
            if b"lunarclient" in data:
                self.client = "lunar"
            elif b"vanilla" in data:
                self.client = "vanilla"

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, buff: Buffer):
        # flush player lists
        self.players.clear()
        self.players_with_stats.clear()

        self.send_packet(self.client_stream, 0x01, buff.getvalue())

        self.waiting_for_locraw = True
        self.send_packet(self.server_stream, 0x01, String.pack("/locraw"))

    @listen_server(0x3E, blocking=True)
    async def packet_teams(self, buff: Buffer):
        name = buff.unpack(String)
        mode = buff.unpack(Byte)
        # team creation
        if mode == b"\x00":
            display_name = buff.unpack(String)
            prefix = buff.unpack(String)
            suffix = buff.unpack(String)
            friendly_fire = buff.unpack(Byte)[0]
            name_tag_visibility = buff.unpack(String)
            color = buff.unpack(Byte)[0]

            player_count = buff.unpack(VarInt)
            players = set()
            for _ in range(player_count):
                players.add(buff.unpack(String))

            self.teams.append(
                Team(
                    name,
                    display_name,
                    prefix,
                    suffix,
                    friendly_fire,
                    name_tag_visibility,
                    color,
                    players,
                )
            )
        # team removal
        elif mode == b"\x01":
            del self.teams[name]
        # team information updation
        elif mode == b"\x02":
            self.teams[name].display_name = buff.unpack(String)
            self.teams[name].prefix = buff.unpack(String)
            self.teams[name].suffix = buff.unpack(String)
            self.teams[name].friendly_fire = buff.unpack(Byte)[0]
            self.teams[name].name_tag_visibility = buff.unpack(String)
            self.teams[name].color = buff.unpack(Byte)[0]
        # add players to team
        elif mode in {b"\x03", b"\x04"}:
            add = True if mode == b"\x03" else False
            player_count = buff.unpack(VarInt)
            players = {buff.unpack(String) for _ in range(player_count)}
            if add:
                self.teams[name].players |= players
            else:
                self.teams[name].players -= players

        for name, (_uuid, display_name) in self.players_with_stats.items():
            prefix, suffix = next(
                (
                    (team.prefix, team.suffix)
                    for team in self.teams
                    if name in team.players
                ),
                ("", ""),
            )
            self.send_packet(
                self.client_stream,
                0x38,
                VarInt.pack(3),
                VarInt.pack(1),
                UUID.pack(uuid.UUID(str(_uuid))),
                Boolean.pack(True),
                Chat.pack(prefix + display_name + suffix),
            )

        self.send_packet(self.client_stream, 0x3E, buff.getvalue())

    @listen_server(0x02)
    async def packet_chat_message(self, buff: Buffer):
        message = buff.unpack(Chat)
        if re.match(r"^\{.*\}$", message) and self.waiting_for_locraw:  # locraw
            if "limbo" in message:  # sometimes returns limbo right when you join
                if not self.teams:  # probably in limbo
                    return
                else:
                    await asyncio.sleep(0.1)
                    return self.send_packet(
                        self.server_stream, 0x01, String.pack("/locraw")
                    )
            else:
                game = json.loads(message)
                self.game.update(game)
                self.waiting_for_locraw = False
                if game.get("mode"):
                    self.rq_game.update(game)
                    return await self._update_stats()

        self.send_packet(self.client_stream, 0x02, buff.getvalue())

    @listen_client(0x01)
    async def packet_chat_message(self, buff: Buffer):
        message = buff.unpack(String)

        # run command
        if message.startswith("/"):
            segments = message.split()
            command = commands.get(segments[0].removeprefix("/")) or commands.get(
                segments[0].removeprefix("//")
            )
            if command:
                try:
                    output = await command(self, message)
                except CommandException as err:
                    self.send_packet(
                        self.client_stream, 0x02, Chat.pack(err.message), b"\x00"
                    )
                else:
                    if output:
                        if segments[0].startswith("//"):  # send output of command
                            # remove chat formatting
                            output = re.sub(r"§.", "", output)
                            self.send_packet(
                                self.server_stream, 0x01, String.pack(output)
                            )
                        else:
                            self.send_packet(
                                self.client_stream, 0x02, Chat.pack(output), b"\x00"
                            )
            else:
                self.send_packet(self.server_stream, 0x01, buff.getvalue())
        else:
            self.send_packet(self.server_stream, 0x01, buff.getvalue())

    @listen_server(0x38, blocking=True)
    async def packet_player_list_item(self, buff: Buffer):
        action = buff.unpack(VarInt)
        num_players = buff.unpack(VarInt)

        for _ in range(num_players):
            _uuid = buff.unpack(UUID)
            if action == 0:  # add player
                name = buff.unpack(String)
                self.players[_uuid] = name
            elif action == 4:  # remove player
                try:
                    del self.players[_uuid]
                except KeyError:
                    pass  # some things fail idk

        self.send_packet(self.client_stream, 0x38, buff.getvalue())

        if action == 0:
            # this doesn't work with await for some reason
            asyncio.create_task(self._update_stats())

    @command("rq")
    async def requeue(self):
        if not self.game.mode:
            raise CommandException("§9§l∎ §4No game to requeue!")
        else:
            self.send_packet(
                self.server_stream, 0x01, String.pack(f"/play {self.game.mode}")
            )

    @command()  # Mmm, garlic bread.
    async def garlicbread(self):  # Mmm, garlic bread.
        return "§eMmm, garlic bread."  # Mmm, garlic bread.

    @command("sc")
    async def statcheck(self, ign=None, mode=None, *stats):
        # TODO default gamemode is hypixel stats
        ign = ign or self.username
        # verify gamemode
        if mode is None:
            gamemode = Gamemode(self.game.gametype) or "bedwars"  # default
        elif (gamemode := Gamemode(mode)) is None:
            raise CommandException(f"§9§l∎ §4Unknown gamemode '{mode}'!")

        # verify stats
        if not stats:
            if gamemode == "bedwars":
                stats = ("Finals", "FKDR", "Wins", "WLR")
            elif gamemode == "skywars":
                stats = ("Kills", "KDR", "Wins", "WLR")
        elif any(Statistic(stat, gamemode) is None for stat in stats):
            unknown_stat = next(
                (stat for stat in stats if Statistic(stat, gamemode) is None)
            )
            raise CommandException(
                f"§9§l∎ §4Unknown statistic '{unknown_stat}' "
                f"for gamemode {gamemode}!"
            )
        else:
            stats = tuple(Statistic(stat, gamemode) for stat in stats)

        try:
            player = await self.hypixel_client.player(ign)
        except PlayerNotFound:
            raise CommandException(f"§9§l∎ §4Player '{ign}' not found!")
        except InvalidApiKey:
            raise CommandException(f"§9§l∎ §4Invalid API Key!")
        except RateLimitError:
            raise CommandException(
                f"§9§l∎ §4Your API key is being rate limited; please wait a little bit!"
            )
        except HypixelException:
            raise CommandException(
                f"§9§l∎ §4An unknown error occurred"
                f"while fetching player '{ign}'! ({player})"
            )

        fplayer = FormattedPlayer(player)
        return fplayer.format_stats(gamemode, *stats)

    # debug command sorta
    @command("game")
    async def _game(self):
        self.send_packet(self.client_stream, 0x02, Chat.pack(f"§aGame:"), b"\x00")
        for key in self.game.__annotations__:
            if value := getattr(self.game, key):
                self.send_packet(
                    self.client_stream,
                    0x02,
                    Chat.pack(f"§b{key.capitalize()}: §e{value}"),
                    b"\x00",
                )

    @command("teams")
    async def _teams(self):
        print(self.teams)

    async def _update_stats(self):
        if self.waiting_for_locraw:
            return
        # update stats in tab in a game, bw & sw are supported so far
        if self.game.gametype in {"bedwars", "skywars"} and self.game.mode:
            # players are in these teams in pregame
            real_player_teams: list[Team] = [
                team
                for team in self.teams
                if team.prefix in {"§a", "§b", "§6", "§c", "§2", "§c", "§d", "§7"}
            ]
            real_players = [
                player
                for team in real_player_teams
                for player in team.players
                if player.isascii()
                and player not in self.players_with_stats.keys()
                and player not in self.players_getting_stats
            ]
            self.players_getting_stats.extend(real_players)

            player_stats = await asyncio.gather(
                *[self.hypixel_client.player(player) for player in real_players],
                return_exceptions=True,
            )

            for player in real_players:
                self.players_getting_stats.remove(player)

            for player in player_stats:
                if isinstance(player, PlayerNotFound):
                    player.name = player.player
                    player.uuid = next(
                        u
                        for u, p in self.players.items()
                        if p.casefold() == player.player.casefold()
                    )
                elif isinstance(player, InvalidApiKey):
                    print("Invalid API Key!")  # TODO
                    continue
                elif isinstance(player, RateLimitError):
                    print("Rate limit!")  # TODO
                    continue
                elif isinstance(player, TimeoutError):
                    print(f"Request timed out!")  # TODO
                    continue
                elif not isinstance(player, hypixel.Player):
                    print(f"An unknown error occurred! ({player})")  # TODO
                    continue

                if player.name in self.players.values():
                    if not isinstance(player, PlayerNotFound):  # nick, probably
                        fplayer = FormattedPlayer(player)

                        # that red player that always shows up
                        if red_player_team := next(
                            (
                                team
                                for team in self.teams
                                if team.prefix == "§c"
                                and team.name_tag_visibility == "never"
                            ),
                            None,
                        ):  # shortest python if statement
                            if (
                                player.name in red_player_team.players
                                and not fplayer.rank.startswith("§c")
                            ):
                                continue

                        if self.game.gametype == "bedwars":
                            display_name = " ".join(
                                (
                                    fplayer.bedwars.level,
                                    fplayer.rankname,
                                    f"§f | {fplayer.bedwars.fkdr}",
                                )
                            )
                        elif self.game.gametype == "skywars":
                            display_name = " ".join(
                                (
                                    fplayer.skywars.level,
                                    fplayer.rankname,
                                    f"§f | {fplayer.skywars.kdr}",
                                )
                            )
                    else:
                        display_name = f"§5[NICK] {player.name}"

                    self.send_packet(
                        self.client_stream,
                        0x38,
                        VarInt.pack(3),
                        VarInt.pack(1),
                        UUID.pack(uuid.UUID(str(player.uuid))),
                        Boolean.pack(True),
                        Chat.pack(display_name),
                    )
                    self.players_with_stats.update(
                        {player.name: (player.uuid, display_name)}
                    )
