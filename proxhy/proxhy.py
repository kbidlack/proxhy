import asyncio
import base64
import json
import random
import re
import uuid
from pathlib import Path
from typing import Self
from unittest.mock import Mock

import appdirs
import hypixel
from hypixel import Player
from hypixel.errors import (
    ApiError,
    HypixelException,
    InvalidApiKey,
    KeyRequired,
    PlayerNotFound,
    RateLimitError,
)

from . import auth
from .aliases import Gamemode, Statistic
from .auth import load_auth_info
from .auth import login as auth_login
from .auth.msmcauthaio.errors import InvalidCredentials, MsMcAuthException
from .command import command, commands
from .datatypes import (
    UUID,
    Boolean,
    Buffer,
    Byte,
    ByteArray,
    Chat,
    Double,
    Float,
    Int,
    Pos,
    Position,
    String,
    UnsignedByte,
    UnsignedShort,
    VarInt,
)
from .errors import CommandException
from .formatting import FormattedPlayer
from .mcmodels import Game, Team, Teams
from .net import Stream
from .proxy import Proxy, State, listen_client, listen_server


class Proxhy(Proxy):
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
        "description": {"text": "insane epic hypixel proxy"},
        "favicon": f"data:image/png;base64,{b64_favicon}",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.client = ""
        self.hypixel_client = None
        self._hypixel_api_key = ""

        self.game = Game()
        self.rq_game = Game()

        self.players: dict[str, str] = {}
        self.players_getting_stats = []
        self.players_with_stats = {}
        self.teams: list[Team] = Teams()

        self.waiting_for_locraw = False
        self.game_error = None  # if error has been sent that game
        self.logged_in = False
        self.logging_in = False

        self.client_stream: Stream

        # TODO move to config file or something similar
        self.CONNECT_HOST = ("mc.hypixel.net", 25565)
        # self.CONNECT_HOST = ("192.168.68.72", 25565)

    async def close(self):
        if not self.open:
            return

        await super().close()

        if self.hypixel_client:
            await self.hypixel_client.close()

    async def login_keep_alive(self):
        while True:
            await asyncio.sleep(10)
            if self.state == State.PLAY and self.client_stream.open:
                self.client_stream.send_packet(0x00, VarInt(random.randint(0, 256)))
            else:
                await self.close()
                break

    async def login(self):
        # immediately send login start to enter login server
        self.state = State.PLAY
        self.logging_in = True

        # fake server stream
        self.server_stream = Mock()
        self.client_stream.send_packet(
            0x02, String(str(uuid.uuid4())), String(self.username)
        )

        self.client_stream.send_packet(
            0x01,
            Int(0),
            UnsignedByte(3),
            Byte(b"\x01"),
            UnsignedByte(0),
            UnsignedByte(1),
            String("default"),
            Boolean(True),
        )

        self.client_stream.send_packet(0x05, Position(Pos(0, 0, 0)))
        self.client_stream.send_packet(
            0x08, Double(0), Double(0), Double(0), Float(0), Float(0), Byte(b"\x00")
        )

        asyncio.create_task(self.login_keep_alive())
        self.client_stream.chat(
            "You have not logged into Proxhy with this account yet!"
        )
        self.client_stream.chat("Use /login <email> <password> to log in.")

    @listen_client(0x00, State.HANDSHAKING, blocking=True)
    async def packet_handshake(self, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)

    @listen_client(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        self.username = buff.unpack(String)

        if self.username.casefold() not in map(lambda s: s.casefold(), auth.users()):
            return await self.login()

        # switch server into login state
        if self.state == State.LOGIN:
            reader, writer = await asyncio.open_connection(
                self.CONNECT_HOST[0], self.CONNECT_HOST[1]
            )
            self.server_stream = Stream(reader, writer)
            self.server_stream.destination = 1
            asyncio.create_task(self.handle_server())

            self.server_stream.send_packet(
                0x00,
                VarInt(47),
                String(self.CONNECT_HOST[0]),
                UnsignedShort(self.CONNECT_HOST[1]),
                VarInt(State.LOGIN.value),
            )

        self.access_token, self.username, self.uuid = await load_auth_info(
            self.username
        )
        self.server_stream.send_packet(0x00, String(self.username))

    @listen_server(0x02, State.LOGIN, blocking=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.logged_in = True

        self.hypixel_client = hypixel.Client(self.hypixel_api_key)
        self.client_stream.send_packet(0x02, buff.read())

    @listen_client(0x17)
    async def packet_plugin_channel(self, buff: Buffer):
        self.server_stream.send_packet(0x17, buff.getvalue())

        channel = buff.unpack(String)
        data = buff.unpack(ByteArray)
        if channel == "MC|Brand":
            if b"lunarclient" in data:
                self.client = "lunar"
            elif b"vanilla" in data:
                self.client = "vanilla"

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, buff: Buffer):
        self.entity_id = buff.unpack(Int)

        # flush player lists
        self.players.clear()
        self.players_with_stats.clear()
        self.players_getting_stats.clear()

        self.game_error = None
        self.client_stream.send_packet(0x01, buff.getvalue())

        if not self.client == "lunar":
            self.waiting_for_locraw = True
            self.server_stream.send_packet(0x01, String("/locraw"))

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
            self.client_stream.send_packet(
                0x38,
                VarInt(3),
                VarInt(1),
                UUID(uuid.UUID(str(_uuid))),
                Boolean(True),
                Chat(prefix + display_name + suffix),
            )
        self.client_stream.send_packet(0x3E, buff.getvalue())

        if mode in {b"\x03", b"\x04"}:
            asyncio.create_task(self._update_stats())

    @listen_server(0x02)
    async def packet_server_chat_message(self, buff: Buffer):
        message = buff.unpack(Chat)

        async def _update_game(self: Self, game: dict):
            self.game.update(game)
            if game.get("mode"):
                return self.rq_game.update(game)
            else:
                return

        if re.match(r"^\{.*\}$", message):  # locraw
            if self.waiting_for_locraw:
                if "limbo" in message:  # sometimes returns limbo right when you join
                    if not self.teams:  # probably in limbo
                        return
                    else:
                        await asyncio.sleep(0.1)
                        return self.server_stream.send_packet(0x01, String("/locraw"))
                else:
                    self.waiting_for_locraw = False
                    await _update_game(self, json.loads(message))
            else:
                await _update_game(self, json.loads(message))

        self.client_stream.send_packet(0x02, buff.getvalue())

    @listen_client(0x01)
    async def packet_client_chat_message(self, buff: Buffer):
        message = buff.unpack(String)

        # run command
        if message.startswith("/"):
            segments = message.split()
            command = commands.get(
                segments[0].removeprefix("/").casefold()
            ) or commands.get(segments[0].removeprefix("//").casefold())
            if command:
                try:
                    output = await command(self, message)
                except CommandException as err:
                    self.client_stream.chat(f"§9§l∎ §4{err.message}")
                else:
                    if output:
                        if segments[0].startswith("//"):  # send output of command
                            # remove chat formatting
                            output = re.sub(r"§.", "", output)
                            self.server_stream.chat(output)
                        else:
                            self.client_stream.chat(output)
            else:
                self.server_stream.send_packet(0x01, buff.getvalue())
        else:
            self.server_stream.send_packet(0x01, buff.getvalue())

    @listen_client(0x14)
    async def packet_tab_complete(self, buff: Buffer):
        text = buff.unpack(String)
        if text.startswith("//"):
            self.server_stream.send_packet(0x14, String(text[1:]), buff.read())
        else:
            self.server_stream.send_packet(buff.getvalue())

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

        self.client_stream.send_packet(0x38, buff.getvalue())

    @command("login")
    async def login_command(self, email, password):
        self.client_stream.chat("§6Logging in...")
        if not self.logging_in:
            raise CommandException("You can't use that right now!")

        try:
            access_token, username, uuid = await auth_login(email, password)
        except InvalidCredentials:
            raise CommandException("Login failed; invalid credentials!")
        except MsMcAuthException:
            raise CommandException(
                "An unknown error occurred while logging in! Try again?"
            )

        if username != self.username:
            raise CommandException(
                f"Wrong account! Logged into {username}; expected {self.username}"
            )

        self.access_token = access_token
        self.uuid = uuid

        self.client_stream.chat("§aLogged in; rejoin proxhy to play!")
        self.state = State.LOGIN

    @command("rq")
    async def requeue(self):
        if not self.rq_game.mode:
            raise CommandException("No game to requeue!")
        else:
            self.server_stream.send_packet(0x01, String(f"/play {self.rq_game.mode}"))

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
            raise CommandException(f"Unknown gamemode '{mode}'!")

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
                f"Unknown statistic '{unknown_stat}' for gamemode {gamemode}!"
            )
        else:
            stats = tuple(Statistic(stat, gamemode) for stat in stats)

        try:
            player = await self.hypixel_client.player(ign)
        except PlayerNotFound:
            # TODO this throws when there's an invalid api key
            raise CommandException(f"Player '{ign}' not found!")
        except InvalidApiKey:
            raise CommandException("Invalid API Key!")
        except RateLimitError:
            raise CommandException(
                "Your API key is being rate limited; please wait a little bit!"
            )
        except HypixelException:
            raise CommandException(
                "An unknown error occurred while fetching player '{ign}'! ({player})"
            )

        fplayer = FormattedPlayer(player)
        return fplayer.format_stats(gamemode, *stats)

    # sorta debug commands
    @command("game")
    async def _game(self):
        self.client_stream.chat("§aGame:")
        for key in self.game.__annotations__:
            if value := getattr(self.game, key):
                self.client_stream.chat(f"§b{key.capitalize()}: §e{value}")

    @command("rqgame")
    async def _rqgame(self):
        self.client_stream.chat("§aRequeue Game:")
        for key in self.rq_game.__annotations__:
            if value := getattr(self.rq_game, key):
                self.client_stream.chat(f"§b{key.capitalize()}: §e{value}")

    @command("ug")
    async def updategame(self):
        self.waiting_for_locraw = True
        self.server_stream.send_packet(0x01, String("/locraw"))
        self.client_stream.chat("§aUpdating!")

    @property
    def hypixel_api_key(self):
        if self._hypixel_api_key:
            return self._hypixel_api_key

        if Path(key_fp := f"{appdirs.user_cache_dir("proxhy")}/k").exists():
            with open(key_fp) as file:
                self._hypixel_api_key = file.read().strip()
                return self._hypixel_api_key
        else:
            return ""

    @hypixel_api_key.setter
    def hypixel_api_key(self, key):
        self._hypixel_api_key = key

        with open(f"{appdirs.user_cache_dir("proxhy")}/k", "w") as file:
            file.write(key)

    @command()
    async def key(self, key):
        try:
            new_client = hypixel.Client(key)
            await new_client.player("gamerboy80")  # test key
            # await new_client.validate_keys()
        except ApiError as e:
            raise CommandException(f"Invalid API Key! {e}")
        finally:
            if new_client:
                await new_client.close()

        if self.hypixel_client:
            await self.hypixel_client.close()

        self.hypixel_api_key = key
        await self._update_stats()
        self.hypixel_client = new_client
        self.client_stream.chat("§aUpdated API Key!")

    async def _update_stats(self):
        if self.waiting_for_locraw:
            return

        # update stats in tab in a game, bw supported so far
        if self.game.gametype in {"bedwars"} and self.game.mode:
            # players are in these teams in pregame
            real_player_teams: list[Team] = [
                team for team in self.teams if re.match("§.§l[A-Z] §r§.", team.prefix)
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
                if player in self.players_getting_stats:
                    self.players_getting_stats.remove(player)

            for player in player_stats:
                if isinstance(player, PlayerNotFound):
                    player.name = player.player
                    try:
                        player.uuid = next(
                            u
                            for u, p in self.players.items()
                            if p.casefold() == player.player.casefold()
                        )
                    except StopIteration:
                        continue
                elif isinstance(player, (InvalidApiKey, RateLimitError, TimeoutError)):
                    err_message = {
                        InvalidApiKey: "§cInvalid API Key!",
                        KeyRequired: "§cNo API Key provided!",
                        RateLimitError: "§cRate limit!",
                        TimeoutError: f"§cRequest timed out! ({player})",
                    }

                    if not self.game_error:
                        self.game_error = player
                        self.client_stream.chat(err_message[type(player)])
                    continue
                elif not isinstance(player, Player):
                    # TODO log this
                    # Session is closed probably, this is pointless
                    continue

                if player.name in self.players.values():
                    if not isinstance(player, PlayerNotFound):  # nick, probably
                        fplayer = FormattedPlayer(player)

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
                    self.client_stream.send_packet(
                        0x38,
                        VarInt(3),
                        VarInt(1),
                        UUID(uuid.UUID(str(player.uuid))),
                        Boolean(True),
                        Chat(display_name),
                    )
                    self.players_with_stats.update(
                        {player.name: (player.uuid, display_name)}
                    )
