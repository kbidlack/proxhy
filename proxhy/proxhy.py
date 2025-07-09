import asyncio
import base64
import json
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Self

import hypixel
import keyring

from . import auth
from .command import commands
from .datatypes import (
    UUID,
    Boolean,
    Buffer,
    Byte,
    ByteArray,
    Chat,
    Int,
    String,
    TextComponent,
    UnsignedShort,
    VarInt,
)
from .errors import CommandException
from .mcmodels import Game, Team, Teams
from .proxy import Proxy, State, listen_client, listen_server
from .settings import Settings


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
        from .ext.statcheck import StatCheck

        stat_highlights: Callable = StatCheck.stat_highlights
        log_bedwars_stats: Callable = StatCheck.log_bedwars_stats
        _update_stats: Callable = StatCheck._update_stats

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.client_type = ""
        self.hypixel_client: hypixel.Client
        self._hypixel_api_key = ""

        self.game = Game()
        self.rq_game = Game()

        self.players: dict[str, str] = {}
        self.players_getting_stats = []
        self.players_with_stats = {}
        self.teams: Teams = Teams()
        self._user_team_prefix = ""  # Cached team prefix from "(YOU)" marker
        self.nick_team_colors: dict[str, str] = {}  # Nicked player team colors

        # EVENTS
        # used so the tab updater can signal functions that stats are logged
        self.received_player_stats = asyncio.Event()

        self.received_locraw = asyncio.Event()
        self.received_locraw.set()

        self.game_error = None  # if error has been sent that game
        self.logged_in = False
        self.logging_in = False

        self.log_path = "stat_log.jsonl"

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
        self.players_getting_stats.clear()
        self._user_team_prefix = ""  # Reset cached team prefix for new game

        self.game_error = None
        self.client.send_packet(0x01, buff.getvalue())

        if not self.client_type == "lunar":
            self.received_locraw.clear()
            self.server.send_packet(0x01, String("/locraw"))

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

            # Check if this team has "(YOU)" or " YOU" in suffix - this indicates it's the user's team
            clean_suffix = re.sub(r"§.", "", suffix)
            if any(
                marker in suffix or marker in clean_suffix
                for marker in ["(YOU)", "(You)", " YOU", " You"]
            ):
                self._user_team_prefix = prefix
                if hasattr(self, "client_stream") and self.client:
                    self.client.chat(f"§a§lTeam detected: §r{prefix}§7Team {name}")

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
            self.teams.delete(name)
        # team information updation
        elif mode == b"\x02":
            team = self.teams.get(name)
            if team:
                team.display_name = buff.unpack(String)
                team.prefix = buff.unpack(String)
                team.suffix = buff.unpack(String)
                team.friendly_fire = buff.unpack(Byte)[0]
                team.name_tag_visibility = buff.unpack(String)
                team.color = buff.unpack(Byte)[0]

                # Check for YOU marker in updated team
                clean_suffix = re.sub(r"§.", "", team.suffix)
                if any(
                    marker in team.suffix or marker in clean_suffix
                    for marker in ["(YOU)", "(You)", " YOU", " You"]
                ):
                    self._user_team_prefix = team.prefix

        # add players to team
        elif mode in {b"\x03", b"\x04"}:
            add = True if mode == b"\x03" else False
            player_count = buff.unpack(VarInt)
            players = {buff.unpack(String) for _ in range(player_count)}

            if add:
                self.teams.get(name).players |= players
            else:
                self.teams.get(name).players -= players

        for name, (_uuid, display_name) in self.players_with_stats.items():
            prefix, suffix = next(
                (
                    (team.prefix, team.suffix)
                    for team in self.teams
                    if name in team.players
                ),
                ("", ""),
            )
            self.client.send_packet(
                0x38,
                VarInt(3),
                VarInt(1),
                UUID(uuid.UUID(str(_uuid))),
                Boolean(True),
                Chat(prefix + display_name + suffix),
            )
        self.client.send_packet(0x3E, buff.getvalue())

        if mode in {b"\x03", b"\x04"}:
            asyncio.create_task(self._update_stats())

    @listen_server(0x02)
    async def packet_server_chat_message(self, buff: Buffer):
        message = buff.unpack(Chat)
        block_msg = False

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
                if (
                    message == game_start_msgs[-2]
                ):  # replace them with the statcheck overview
                    self.client.chat(
                        TextComponent("Fetching top stats...").color("gold").bold()
                    )
                    await asyncio.sleep(3)  # TODO: why do we have to wait 3s?
                    # idfk its supposed to wait for the flare from the _update_stats function
                    # and it does, but then for some reason it only fetches one player so idk
                    # if we wait 3s it works slash shrug
                    highlights = await self.stat_highlights()
                    self.client.chat(highlights)

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

                    err.message = TextComponent(err.message)
                    if not err.message.data.get("color"):
                        err.message.color("dark_red")

                    error_msg = (
                        TextComponent("∎ ").color("blue").bold().append(err.message)
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

    @property
    def hypixel_api_key(self):
        if self._hypixel_api_key:
            return self._hypixel_api_key

        return keyring.get_password("proxhy", "hypixel_api_key")

    @hypixel_api_key.setter
    def hypixel_api_key(self, key):
        self._hypixel_api_key = key

        auth.safe_set("proxhy", "hypixel_api_key", key)
