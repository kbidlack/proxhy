import asyncio
import base64
import json
import re
import time
import uuid
from pathlib import Path
from typing import Literal, Self

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

from .aliases import Gamemode, Statistic
from .auth import load_auth_info, users
from .client import Proxy, State, listen_client, listen_server
from .command import command, commands
from .datatypes import UUID, Boolean, Buffer, Byte, ByteArray, Chat, String, VarInt
from .errors import CommandException
from .formatting import FormattedPlayer
from .models import Game, Team, Teams
from .packets import roll_packets
from .server import Server


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
        self.game_error = None  # if error has been sent that game
        self.logged_in = False

        self.username = ""

        self.rolling = (None, None)
        self.rolling_target = 0

        self.broadcast_server = None

        # TODO move to config file or something similar
        # self.CONNECT_HOST = ("mc.hypixel.net", 25565)
        self.CONNECT_HOST = ("192.168.68.72", 25565)

    async def close(self):
        if not self.open:
            return

        await super().close()

        if self.username and self.broadcast_server:
            await self.stop_broadcast(disconnected=True)

        if self.hypixel_client:
            await self.hypixel_client.close()

    @listen_client(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        username = buff.unpack(String)

        if username.casefold() not in users():
            self.send_packet(
                self.client_stream,
                0x00,
                Chat.pack(
                    "§4You are not logged in with this account!\n"
                    "§4Restart Proxhy with this username to log in."
                ),
            )
            return await self.close()

        (
            self.access_token,
            self.username,
            self.uuid,
        ) = await load_auth_info(username)

        while not self.server_stream:
            await asyncio.sleep(0.01)

        self.send_packet(self.server_stream, 0x00, String.pack(self.username))

    @listen_server(0x02, State.LOGIN, blocking=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.logged_in = True

        self.hypixel_client = hypixel.Client()  # TODO
        self.send_packet(self.client_stream, 0x02, buff.read())

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
        self.players_getting_stats.clear()

        self.game_error = None

        self.send_packet(self.client_stream, 0x01, buff.getvalue())

        if not self.client == "lunar":
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
    async def packet_server_chat_message(self, buff: Buffer):
        message = buff.unpack(Chat)

        async def _update_game(self: Self, game: dict):
            self.game.update(game)
            if game.get("mode"):
                self.rq_game.update(game)
                return await self._update_stats()
            else:
                return

        if re.match(r"^\{.*\}$", message):  # locraw
            if self.waiting_for_locraw:
                if "limbo" in message:  # sometimes returns limbo right when you join
                    if not self.teams:  # probably in limbo
                        return
                    else:
                        await asyncio.sleep(0.1)
                        return self.send_packet(
                            self.server_stream, 0x01, String.pack("/locraw")
                        )
                else:
                    self.waiting_for_locraw = False
                    await _update_game(self, json.loads(message))
            else:
                await _update_game(self, json.loads(message))
        elif (
            message.startswith("TICKET REWARD!") and self.rolling[1] == "Ticket Machine"
        ) or (
            re.match(r".*\[\d+/\d+\]$", message) and self.rolling[1] == "Arcade Player"
        ):
            # await asyncio.sleep(random.uniform(0.2, 0.5))
            await asyncio.sleep(0.1)
            self.send_packet(
                self.server_stream,
                0x02,
                VarInt.pack(self.rolling_target),
                VarInt.pack(1),
            )

        self.send_packet(self.client_stream, 0x02, buff.getvalue())

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
                    self.send_packet(
                        self.client_stream,
                        0x02,
                        Chat.pack_msg(f"§9§l∎ §4{err.message}"),
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
                                self.client_stream, 0x02, Chat.pack_msg(output)
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
            raise CommandException("No game to requeue!")
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

    # debug command sorta
    @command("game")
    async def _game(self):
        self.send_packet(self.client_stream, 0x02, Chat.pack_msg("§aGame:"))
        for key in self.game.__annotations__:
            if value := getattr(self.game, key):
                self.send_packet(
                    self.client_stream,
                    0x02,
                    Chat.pack_msg(f"§b{key.capitalize()}: §e{value}"),
                )

    @command("teams")
    async def _teams(self):
        print(self.teams)

    # ROLLING -------------------------------------------------------------------------

    @command()
    async def roll(self, target=""):
        if not target:
            raise CommandException("Please specify a target or 'off' to turn off!")

        match target.casefold():
            case "off":
                self.rolling = (None, None)
                self.send_packet(
                    self.client_stream, 0x02, Chat.pack_msg("§bRolling §l§4OFF")
                )
            case "ticket":
                self.rolling = ("Ticket Machine", "Ticket Machine")
                self.send_packet(
                    self.client_stream,
                    0x02,
                    Chat.pack_msg("§bRolling §l§aTicket Machine"),
                )
            case "arcade":
                self.rolling = ("Item Submission", "Arcade Player")
                self.send_packet(
                    self.client_stream,
                    0x02,
                    Chat.pack_msg("§bRolling §l§aArcade Player"),
                )
            case _:
                raise CommandException(f"Unknown target '{target}'!")

    @listen_client(0x0E, blocking=True)
    async def packet_click_window(self, buff: Buffer):
        self.send_packet(self.server_stream, 0x0E, buff.getvalue())
        # print(buff.getvalue())

    @listen_server(0x2D, blocking=True)
    async def packet_open_window(self, buff: Buffer):
        if not self.rolling[0]:
            return self.send_packet(self.client_stream, 0x2D, buff.getvalue())

        window_id = buff.unpack(Byte)
        buff.unpack(String)
        window_title = buff.unpack(Chat)

        if window_title == self.rolling[0] and self.rolling[1]:
            self.send_packet(
                self.server_stream, 0x0E, window_id, roll_packets[self.rolling[1]]
            )

    @listen_client(0x02, blocking=True)
    async def packet_use_entity(self, buff: Buffer):
        self.send_packet(self.server_stream, 0x02, buff.getvalue())

        target = buff.unpack(VarInt)
        if self.rolling[0]:
            self.rolling_target = target
            self.send_packet(
                self.client_stream,
                0x02,
                Chat.pack_msg(f"§aSet target to §l§b{self.rolling_target}"),
            )

    # ---------------------------------------------------------------------------------

    @command("ug")
    async def updategame(self):
        self.waiting_for_locraw = True
        self.send_packet(self.server_stream, 0x01, String.pack("/locraw"))
        self.send_packet(self.client_stream, 0x02, Chat.pack_msg("§aUpdating!"))

    @command()
    async def key(self, key):
        try:
            new_client = hypixel.Client(key)
            await new_client.player("gamerboy80")  # test key
            # await new_client.validate_keys()
        except ApiError as e:
            raise CommandException(f"Invalid API Key! {e}")

        if self.hypixel_client:
            await self.hypixel_client.close()

        self.hypixel_client = new_client
        self.send_packet(self.client_stream, 0x02, Chat.pack_msg("§aUpdated API Key!"))

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
                        self.send_packet(
                            self.client_stream,
                            0x02,
                            Chat.pack_msg(err_message[type(player)]),
                        )
                    continue
                elif not isinstance(player, Player):
                    # TODO log this
                    print(f"An unknown error occurred! ({player})", time.time())
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

    @command("broadcast", "bc")
    async def broadcast(self, action: Literal["start", "stop", "chat"], *args):
        if action != "start" and not self.broadcast_server:
            raise CommandException("You are not broadcasting!")

        # TODO: kick, info
        if action == "start":
            if len(args) > 1:
                raise CommandException(
                    "Too many arguments for broadcast start! (expected 1; port)"
                )
            if self.broadcast_server:
                raise CommandException("You are already broadcasting!")

            if args and not args[0].isdigit():
                raise CommandException("Port must be a number!")

            if args and (not 1000 < int(args[0]) < 65535):
                raise CommandException(
                    "Port must be between 1000 and 65535 (exclusive)!"
                )

            await self.start_broadcast(*args)
        elif action == "stop":
            if args:
                raise CommandException(
                    "Too many arguments for broadcast stop! (expected 0)"
                )

            await self.stop_broadcast()
        elif action == "chat":
            if not args:
                raise CommandException("No message provided!")

            msg = Chat.pack_msg(
                f"§3[§5BROADCAST§3] §b{self.username}: §e{" ".join(args)}"
            )
            self.broadcast_server.announce(0x02, msg)
            self.send_packet(self.client_stream, 0x02, msg)
        else:
            raise CommandException(f"Unknown action '{action}'!")

    async def start_broadcast(self, port: int = 25565):
        self.broadcast_server = Server(self)
        asyncio.create_task(self.broadcast_server.serve_forever(port))

        self.send_packet(
            self.client_stream, 0x02, Chat.pack_msg("§aStarted broadcasting!")
        )

    async def stop_broadcast(self, disconnected: bool = False):
        if self.broadcast_server is not None:
            reason = (
                "§4Broadcast owner disconnected!"
                if disconnected
                else "§4Broadcast stopped!"
            )
            await self.broadcast_server.close(reason)

            self.broadcast_server = None

            self.send_packet(
                self.client_stream, 0x02, Chat.pack_msg("§aStopped broadcasting!")
            )

    async def client_packet(self, packet_id: int, packet_data: Buffer):
        if packet_id == 0x01 and self.broadcast_server:  # join game
            for client in self.broadcast_server.clients:
                client.getting_data = True

        # this blocks, so we should move on quickly
        # if self.broadcast_server:
        #     for client in [c for c in self.broadcast_server.clients if c.getting_data]:
        #         await client.send_packet(packet_id, packet_data.read())
