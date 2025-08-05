import asyncio
import base64
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Self

import hypixel
import keyring
from platformdirs import user_cache_dir

from . import auth
from .command import commands
from .datatypes import (
    UUID,
    Buffer,
    ByteArray,
    Chat,
    Int,
    String,
    TextComponent,
    UnsignedShort,
    VarInt,
)
from .errors import CommandException
from .mcmodels import Game, Teams
from .proxy import Proxy, State, listen_client, listen_server
from .settings import Settings

if TYPE_CHECKING:
    from .ext.gamestate import GameState
    from .ext.statcheck import StatCheck
    from .ext.window import Window


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
        "description": {"text": "why hello there"},
        "favicon": f"data:image/png;base64,{b64_favicon}",
    }

    settings = Settings()

    # TYPE HINTS
    if TYPE_CHECKING:
        stat_highlights: Callable = StatCheck.stat_highlights
        log_bedwars_stats: Callable = StatCheck.log_bedwars_stats
        _update_stats: Callable = StatCheck._update_stats
        keep_player_stats_updated: Callable = StatCheck.keep_player_stats_updated
        _update_teams: Callable = GameState._update_teams

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # HYPIXEL API
        self.hypixel_client: hypixel.Client
        self._hypixel_api_key = ""

        # CLIENT INFO
        self.client_type = ""

        # GAME STATE
        self.logged_in = False
        self.logging_in = False

        ## PROXHY
        self.windows: dict[int, Window] = {}
        self.game_error = None  # if error has been sent that game

        # cached player stats for stat highlights to pull from
        self._cached_players = {}

        # players from packet_player_list_item
        self.players: dict[str, str] = {}

        self.teams: Teams = Teams()

        # server info
        self.game = Game()
        self.rq_game = Game()

        # STATCHECK STATE
        self.players_with_stats = {}
        self.nick_team_colors: dict[str, str] = {}  # Nicked player team colors
        self.players_without_stats: set[str] = set()  # players from /who

        # EVENTS
        # statcheck
        self.received_player_stats = asyncio.Event()

        # server info
        self.received_locraw = asyncio.Event()
        self.received_locraw.set()

        self.received_who = asyncio.Event()
        self.received_who.set()

        # LOCKS
        # statcheck
        self.player_stats_lock = asyncio.Lock()

        # MISC
        self.log_path = (
            Path(user_cache_dir("proxhy", ensure_exists=True)) / "stat_log.jsonl"
        )

    async def close(self):
        if not self.open:
            return

        await super().close()
        try:
            if self.hypixel_client:
                await self.log_bedwars_stats("logout")
                await self.hypixel_client.close()
        except AttributeError:
            pass

    @listen_client(0x00, State.HANDSHAKING, blocking=True, override=True)
    async def packet_handshake(self, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)

    @listen_client(0x17)
    async def packet_plugin_channel(self, buff: Buffer):
        self.server.send_packet(0x17, buff.getvalue())

        channel = buff.unpack(String)
        data = buff.unpack(ByteArray)
        if channel == "MC|Brand":
            if b"lunarclient" in data:
                self.client_type = "lunar"
            elif b"vanilla" in data:
                self.client_type = "vanilla"

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, buff: Buffer):
        self.entity_id = buff.unpack(Int)

        # flush player lists
        self.players.clear()
        self.players_with_stats.clear()
        self._cached_players.clear()

        self.game_error = None
        self.client.send_packet(0x01, buff.getvalue())

        self.received_player_stats.clear()

        if not self.client_type == "lunar":
            self.received_locraw.clear()
            self.server.send_packet(0x01, String("/locraw"))

    @listen_server(0x3E)
    async def packet_teams(self, buff: Buffer):
        # game state
        self._update_teams(buff.clone())

        self.client.send_packet(0x3E, buff.getvalue())

        # statcheck
        self.keep_player_stats_updated()

    @listen_server(0x02)
    async def packet_server_chat_message(self, buff: Buffer):
        message = buff.unpack(Chat)
        block_msg = False

        if message.startswith("ONLINE: "):  # /who
            if not self.received_who.is_set():
                self.received_who.set()
            else:
                self.client.send_packet(0x02, buff.getvalue())

            self.players_without_stats.update(
                message.removeprefix("ONLINE: ").split(", ")
            )
            self.players_without_stats.difference_update(
                set(self.players_with_stats.keys())
            )
            return await self._update_stats()

        # if user rejoins a game
        if ("You will respawn in 10 seconds!" in message) or (
            "Your bed was destroyed so you are a spectator!" in message
        ):
            self.server.send_packet(0x01, String("/who"))
            self.received_who.clear()

        if (
            self.settings.bedwars.display_top_stats.state != "OFF"
        ):  # 3 on states so we just check if its not off
            game_start_msgs = [  # block all the game start messages
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
                "                                  Bed Wars",
                "     Protect your bed and destroy the enemy beds.",
                "      Upgrade yourself and your team by collecting",
                "    Iron, Gold, Emerald and Diamond from generators",
                "                  to access powerful upgrades.",
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
            ]

            if message in game_start_msgs:
                block_msg = True
                if message == game_start_msgs[-2]:
                    # replace them with the statcheck overview
                    self.client.chat(
                        TextComponent("Fetching top stats...").color("gold").bold()
                    )
                    self.server.send_packet(0x01, String("/who"))
                    self.received_who.clear()

        async def _update_game(self: Self, game: dict):
            self.game.update(game)
            if game.get("mode"):
                return self.rq_game.update(game)
            else:
                return

        if re.match(r"^\{.*\}$", message):  # locraw
            if not self.received_locraw.is_set():
                if "limbo" in message:  # sometimes returns limbo right when you join
                    if not self.teams:  # probably in limbo
                        return
                    elif self.client_type != "lunar":
                        await asyncio.sleep(0.1)
                        return self.server.send_packet(0x01, String("/locraw"))
                else:
                    self.received_locraw.set()
                    await _update_game(self, json.loads(message))
            else:
                await _update_game(self, json.loads(message))

        if not block_msg:
            self.client.send_packet(0x02, buff.getvalue())

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
                    output: str | TextComponent = await command(self, message)
                except CommandException as err:
                    if isinstance(err.message, TextComponent):
                        err.message.flatten()

                        for i, child in enumerate(err.message.get_children()):
                            if not child.data.get("color"):
                                err.message.replace_child(i, child.color("dark_red"))
                            if not child.data.get("bold"):
                                err.message.replace_child(i, child.bold(False))

                    err.message = TextComponent(err.message)
                    if not err.message.data.get("color"):
                        err.message.color("dark_red")

                    err.message = err.message.bold(False)

                    error_msg = (
                        TextComponent("∎ ").bold().color("blue").append(err.message)
                    )
                    self.client.chat(error_msg)
                else:
                    if output:
                        if segments[0].startswith("//"):  # send output of command
                            # remove chat formatting
                            output = re.sub(r"§.", "", str(output))
                            self.server.chat(output)
                        else:
                            self.client.chat(output)
            else:
                self.server.send_packet(0x01, buff.getvalue())
        else:
            self.server.send_packet(0x01, buff.getvalue())

    @listen_client(0x14)
    async def packet_tab_complete(self, buff: Buffer):
        text = buff.unpack(String)
        if text.startswith("//"):
            self.server.send_packet(0x14, String(text[1:]), buff.read())
        else:
            self.server.send_packet(0x14, buff.getvalue())

    @listen_server(0x38, blocking=True)
    async def packet_player_list_item(self, buff: Buffer):
        action = buff.unpack(VarInt)
        num_players = buff.unpack(VarInt)

        for _ in range(num_players):
            _uuid = buff.unpack(UUID)
            if action == 0:  # add player
                name = buff.unpack(String)
                self.players[str(_uuid)] = name
            elif action == 4:  # remove player
                try:
                    del self.players[str(_uuid)]
                except KeyError:
                    pass  # some things fail idk

        self.client.send_packet(0x38, buff.getvalue())
        self.keep_player_stats_updated()

    @property
    def hypixel_api_key(self):
        if self._hypixel_api_key:
            return self._hypixel_api_key

        return keyring.get_password("proxhy", "hypixel_api_key")

    @hypixel_api_key.setter
    def hypixel_api_key(self, key):
        self._hypixel_api_key = key

        auth.safe_set("proxhy", "hypixel_api_key", key)
