import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

import hypixel
import keyring
from hypixel import (
    ApiError,
    InvalidApiKey,
    KeyRequired,
    Player,
    PlayerNotFound,
    RateLimitError,
    TimeoutError,
)
from platformdirs import user_cache_dir

from core.events import listen_server, subscribe
from protocol.datatypes import (
    UUID,
    Boolean,
    Buffer,
    Chat,
    String,
    TextComponent,
    VarInt,
)
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.formatting import (
    format_bedwars_dict,
    format_bw_star,
    get_rankname,
)
from proxhy.gamestate import Team
from proxhy.plugin import ProxhyPlugin

with (
    files("proxhy")
    .joinpath("assets/bedwars_maps.json")
    .open("r", encoding="utf-8") as f
):
    BW_MAPS: dict = json.load(f)
with (
    files("proxhy")
    .joinpath("assets/rush_mappings.json")
    .open("r", encoding="utf-8") as f
):
    RUSH_MAPPINGS = json.load(f)
with (
    files("proxhy")
    .joinpath("assets/bedwars_chat.json")
    .open("r", encoding="utf-8") as file
):
    KILL_MSGS: list[str] = json.load(file)["kill_messages"]

GAME_START_MESSAGE_SETS = [  # block all the game start messages
    [
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "                                  Bed Wars",
        "     Protect your bed and destroy the enemy beds.",
        "      Upgrade yourself and your team by collecting",
        "    Iron, Gold, Emerald and Diamond from generators",
        "                  to access powerful upgrades.",
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ],
    #
    # no armed
    #
    [
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "                       Bed Wars Lucky Blocks",
        "    Collect Lucky Blocks from resource generators",
        "       to receive random loot! Break them to reveal",
        "                             their contents!",
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ],
    [
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "                              Bed Wars Rush"
        "     All generators are maxed! Your bed has three",
        "       layers of protection! Left click while holding",
        "                 wool to activate bridge building!",
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ],
    [
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "                           Bed Wars Ultimate",
        "          Select an ultimate in the store! They will",
        "                     be enabled in 10 seconds!"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ],
    #
    # no voidless
    #
    [
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "                          Bed Wars Swappage",
        "    Players swap teams at random intervals! Players",
        "        also swap positions with the players of the",
        "                    team they are swapping to!",
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ],
    [
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "                                  Bed Wars",
        "     Every few seconds brings a new surprise! Use"
        "        these items to defend your bed or destroy",
        "                                enemy beds.",
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ],
]
GAME_START_MESSAGES = [msg for msg_set in GAME_START_MESSAGE_SETS for msg in msg_set]

# Regex patterns
COLOR_CODE_RE = re.compile(r"§.")
JOIN_RE = re.compile(
    r"^(?:\[[A-Za-z0-9+]+\]\s*)?"  # optional rank tag like [MVP++]
    r"(?P<ign>[A-Za-z0-9_]{3,16}) has joined (?P<context>.+)!$"
)
COLOR_CODE = re.compile(r"(§[0-9a-fk-or])", re.IGNORECASE)

# Team color mappings
TEAM_NAME_TO_LETTER = {
    "red": "R",
    "blue": "B",
    "green": "G",
    "yellow": "Y",
    "aqua": "A",
    "white": "W",
    "pink": "P",
    "gray": "S",
}

TEAM_LETTER_TO_CODE = {
    "R": "§c",
    "B": "§9",
    "G": "§a",
    "Y": "§e",
    "A": "§b",
    "W": "§f",
    "P": "§d",
    "S": "§8",
}

COLOR_CODE_TO_NAME = {
    "§c": "Red",
    "§9": "Blue",
    "§a": "Green",
    "§e": "Yellow",
    "§b": "Aqua",
    "§f": "White",
    "§d": "Pink",
    "§7": "Gray",
    "§8": "Gray",
}


class PlayersWithStats(TypedDict):
    uuid: str
    display_name: str
    fplayer: dict | Nick


class TeamColor(TypedDict):
    letter: str
    code: str
    name: str


@dataclass
class Nick:
    name: str
    uuid: str = field(init=False)


def minecraft_uuid_v2():
    u = uuid.uuid4().int
    # Set version bits (4 bits starting at bit 76) to 2
    u &= ~(0xF << 76)  # clear version bits
    u |= 0x2 << 76  # set version=2
    return uuid.UUID(int=u)


class StatCheckPluginState:
    players_with_stats: dict[str, PlayersWithStats]
    nick_team_colors: dict[str, str]
    players_without_stats: set[str]
    final_dead: dict[str, str]
    dead: dict[str, str]
    _cached_players: dict
    players: dict[str, str]
    _hypixel_api_key: str
    game_error: Optional[Exception]
    stats_highlighted: bool
    adjacent_teams_highlighted: bool
    received_player_stats: asyncio.Event
    player_stats_lock: asyncio.Lock
    _api_key_valid: bool | None
    _api_key_validated_at: float | None
    update_stats_complete: asyncio.Event
    hypixel_client: hypixel.Client
    hypixel_api_key: str


class StatCheckPlugin(ProxhyPlugin):
    def _init_statcheck(self):
        self.players_with_stats: dict[str, PlayersWithStats] = {}
        self.nick_team_colors: dict[str, str] = {}  # Nicked player team colors
        self.players_without_stats: set[str] = set()  # players from /who

        self.final_dead: dict[str, str] = {}  # name: uuid
        self.dead: dict[str, str] = {}  # name: uuid

        self._cached_players: dict = {}
        # players from packet_player_list_item
        self.players: dict[str, str] = {}  # uuid: name
        self._hypixel_api_key = ""

        self.game_error = None  # if error has been sent that game
        self.stats_highlighted = False
        self.adjacent_teams_highlighted = False

        self.received_player_stats = asyncio.Event()

        self.player_stats_lock = asyncio.Lock()

        self.log_path = (
            Path(user_cache_dir("proxhy", ensure_exists=True)) / "stat_log.jsonl"
        )
        self._api_key_valid: bool | None = None
        self._api_key_validated_at: float | None = None

        self.update_stats_complete = asyncio.Event()

    @property
    def all_players(self) -> set[str]:
        if self.game.gametype == "bedwars" and self.game.started:
            real_player_teams: list[Team] = [
                team
                for team in self.gamestate.teams.values()
                if re.match("§.§l[A-Z] §r§.", team.prefix)
            ]

            real_players = set()
            for player in set(self.players.values()):
                if any(player in team.members for team in real_player_teams):
                    real_players.add(player)

            return real_players | self.dead.keys() | self.final_dead.keys()
        else:
            return set(self.players.values())

    @property
    def hypixel_api_key(self):
        if self._hypixel_api_key:
            return self._hypixel_api_key

        return keyring.get_password("proxhy", "hypixel_api_key")

    @hypixel_api_key.setter
    def hypixel_api_key(self, key):
        self._hypixel_api_key = key

        keyring.set_password("proxhy", "hypixel_api_key", key)

    async def validate_api_key(self, force: bool = False) -> bool:
        """Validate the Hypixel API key by making a test request.

        Caches the result for API_KEY_CACHE_TTL seconds unless force=True.
        """
        now = asyncio.get_event_loop().time()

        # Return cached result if valid and not expired
        if not force and self._api_key_valid is not None:
            if self._api_key_validated_at and (now - self._api_key_validated_at < 300):
                return self._api_key_valid

        # Test the API key
        client = None
        try:
            client = hypixel.Client(self.hypixel_api_key)
            await client.player("gamerboy80")
            self._api_key_valid = True
        except Exception:
            self._api_key_valid = False
        finally:
            if client:
                try:
                    await client.close()
                except Exception:
                    pass

        self._api_key_validated_at = now
        return self._api_key_valid

    # Helper methods for common operations

    def _send_tablist_update(
        self, player_uuid: str, display_name: str, listed: bool = True
    ) -> None:
        """Send a packet to update a player's display name in the tab list."""
        self.client.send_packet(
            0x38,
            VarInt.pack(3),
            VarInt.pack(1),
            UUID.pack(uuid.UUID(player_uuid)),
            Boolean.pack(listed),
            Chat.pack(display_name),
        )

    def _send_bulk_tablist_update(self, updates: list[tuple[str, str]]) -> None:
        """Send a packet to update multiple players' display names in the tab list.

        Args:
            updates: List of (player_uuid, display_name) tuples
        """
        if not updates:
            return

        self.client.send_packet(
            0x38,
            VarInt(3),
            VarInt(len(updates)),
            *(
                UUID(uuid.UUID(str(player_uuid))) + Boolean(True) + Chat(display_name)
                for player_uuid, display_name in updates
            ),
        )

    def _build_player_display_name(self, player_name: str, fdict: dict | Nick) -> str:
        try:
            color = self.get_team_color(player_name)
        except ValueError:
            color = {"code": "", "letter": "", "name": ""}

        if isinstance(fdict, Nick):
            return f"{color['code']}§l{color['letter']}§r §5[NICK] {player_name}"

        if (
            self.settings.bedwars.tablist.is_mode_specific.get() == "ON"
            and self.game.mode
        ):
            mode = self.game.mode[8:].lower()
            fkdr = fdict[f"{mode}_fkdr"]
        else:
            fkdr = fdict["fkdr"]

        show_rankname = self.settings.bedwars.tablist.show_rankname.get()
        name = fdict["rankname"] if show_rankname == "ON" else fdict["raw_name"]

        display_name = " ".join(
            (
                f"{fdict['star']}{color['code']}",
                name,
                f" §7| {fkdr}",
            )
        )

        prefix = color["code"] + "§l" + color["letter"] + "§r"
        return prefix + " " + display_name

    def _get_dead_display_name(self, player_name: str) -> str:
        """Get the grayed-out display name for a dead player.

        Args:
            player_name: The player's name

        Returns:
            The formatted display name with gray color codes
        """
        # Use bold+italic for current user, just italic for others
        color = "§7§l§o" if player_name == self.username else "§7§o"

        if (
            player_name in self.players_with_stats
            and self.settings.bedwars.tablist.show_stats.get() == "ON"
        ):
            display_name = re.sub(
                r"§[0-9a-f]",
                "",
                str(self.players_with_stats[player_name]["display_name"]),
            )
            return color + re.sub(r"§r", "§r" + color, display_name)
        else:
            return color + player_name

    def _update_dead_players_in_tablist(self) -> None:
        """Update all final dead players in the tab list with grayed-out display names."""
        for name, u in self.final_dead.items():
            display_name = self._get_dead_display_name(name)
            self._send_tablist_update(u, display_name)

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, _):
        for player, _uuid in (self.dead | self.final_dead).items():
            self.client.send_packet(
                0x38,
                VarInt.pack(4),
                VarInt.pack(1),
                UUID.pack(uuid.UUID(_uuid)),
            )

        # flush player lists
        self.players.clear()
        self.players_with_stats.clear()
        self._cached_players.clear()
        self.dead.clear()
        self.final_dead.clear()

        self.get_team_color.cache_clear()

        self.received_player_stats.clear()
        self.game_error = None
        self.stats_highlighted = False
        self.adjacent_teams_highlighted = False

    @subscribe("setting:bedwars.tablist.show_stats")
    async def _statcheck_event_setting_bedwars_tablist_show_stats(self, data: list):
        # data = [old_state, new_state]
        if data == ["OFF", "ON"]:
            self.received_who.clear()
            # self.server.chat("/who")
            await self._update_stats()
        elif data == ["ON", "OFF"]:
            await self._reset_stats()

        self._update_dead_players_in_tablist()

    @subscribe("setting:bedwars.tablist.is_mode_specific")
    async def _statcheck_event_setting_bedwars_tablist_is_mode_specific(
        self, data: list
    ) -> None:
        """Callback when is_mode_specific setting changes - rebuild display names."""
        if self.settings.bedwars.tablist.show_stats.get() == "ON":
            # Recalculate display names with new mode-specific setting
            for player, player_data in self.players_with_stats.items():
                fdict = player_data["fplayer"]
                if isinstance(fdict, dict):
                    # Rebuild display name with new setting
                    display_name = self._build_player_display_name(player, fdict)
                    self.players_with_stats[player] = {
                        "uuid": player_data["uuid"],
                        "display_name": display_name,
                        "fplayer": fdict,
                    }

            # Update the tab list immediately
            self.keep_player_stats_updated()
            self._update_dead_players_in_tablist()

    async def _reset_stats(self) -> None:
        """Reset all player display names to default (no stats shown)."""
        updates = [
            (
                str(self.players_with_stats[player]["uuid"]),
                self.get_team_color(player)["code"] + player,
            )
            for player in self.players_with_stats
        ]
        self._send_bulk_tablist_update(updates)
        self._update_dead_players_in_tablist()

    @subscribe("setting:bedwars.tablist.show_rankname")
    async def _statcheck_event_setting_bedwars_tablist_show_rankname(
        self, data: list
    ) -> None:
        """Callback when show_rankname setting changes - rebuild display names."""
        for player, player_data in self.players_with_stats.items():
            fdict = player_data["fplayer"]
            if isinstance(fdict, dict):
                # Rebuild display name with new setting
                display_name = self._build_player_display_name(player, fdict)
                self.players_with_stats[player] = {
                    "uuid": player_data["uuid"],
                    "display_name": display_name,
                    "fplayer": fdict,
                }
        self.keep_player_stats_updated()
        self._update_dead_players_in_tablist()

    @subscribe("setting:bedwars.tablist.show_eliminated_players")
    async def _statcheck_event_setting_bedwars_tablist_show_eliminated_players(
        self, data: list
    ) -> None:
        # remove self from final_dead
        final_dead_no_self = self.final_dead.copy()
        if self.username in final_dead_no_self:
            # TODO: does not work with nicks
            del final_dead_no_self[self.username]

        if data == ["OFF", "ON"]:
            packet = VarInt.pack(0) + VarInt.pack(len(final_dead_no_self))
            for player, u in final_dead_no_self.items():
                packet += UUID.pack(uuid.UUID(u))
                packet += String.pack(player)
                packet += VarInt(0)  # properties
                packet += VarInt(3)  # gamemode; spectator
                packet += VarInt(0)  # ping
                packet += Boolean(True)  # has display name
                packet += Chat.pack(self._get_dead_display_name(player))

            self.client.send_packet(0x38, packet)
        elif data == ["ON", "OFF"]:
            packet = VarInt.pack(4) + VarInt.pack(len(final_dead_no_self))
            for _, u in final_dead_no_self.items():
                packet += UUID.pack(uuid.UUID(u))

            self.client.send_packet(0x38, packet)

    @subscribe("cb_gamestate_update")
    async def _statcheck_event_cb_gamestate_update_teams(
        self, data: tuple[int, *tuple[bytes, ...]]
    ):
        if data[0] == 0x3E:
            self.keep_player_stats_updated()

    @listen_server(0x38, blocking=True)
    async def packet_player_list_item(self, buff: Buffer):
        action = buff.unpack(VarInt)
        num_players = buff.unpack(VarInt)

        for _ in range(num_players):
            _uuid = buff.unpack(UUID)
            if action == 0:  # add player
                name = buff.unpack(String)
                self.players[str(_uuid)] = name

                # read past properties
                num_properties = buff.unpack(VarInt)
                for _ in range(num_properties):
                    buff.unpack(String)  # name
                    buff.unpack(String)  # value
                    has_signature = buff.unpack(Boolean)
                    if has_signature:
                        buff.unpack(String)  # signature

                buff.unpack(VarInt)  # gamemode
                buff.unpack(VarInt)  # ping
                has_display_name = buff.unpack(Boolean)
                if has_display_name:
                    # replace display name with stats if available
                    if name in self.players_with_stats:
                        display_name = self.players_with_stats[name]["display_name"]
                        # get buffer up to this point + pack new display name
                        Buffer(buff.getvalue()[: buff.tell()]).write(
                            Chat.pack(display_name)
                        )

            elif action == 4:  # remove player
                try:
                    del self.players[str(_uuid)]
                except KeyError:
                    pass  # hypixel likes to remove players that aren't there

        self.client.send_packet(0x38, buff.getvalue())

    async def _get_player(self, player: str) -> dict[str, Player]:
        """Get a player from cache or fetch from API."""
        return {
            player: self._cached_players.get(player)
            or await self.hypixel_client.player(player)
        }

    @lru_cache()
    def get_team_color(self, player_name: str) -> TeamColor:
        """
        Return comprehensive team color information for a player.

        Returns a dictionary with:
        - letter: Single-letter team identifier (R, B, G, Y, A, W, P, S)
        - code: Minecraft color code (§c, §9, §a, etc.)
        - name: Full color name (Red, Blue, Green, etc.)

        Special handling for self.username using sidebar "YOU" detection.
        """
        team_name = None
        color_code = None

        # Special handling for current user - check sidebar for "YOU"
        if player_name == self.username:
            team_name, color_code = self._get_own_team_info()
        # Check for nicked player cached color
        elif player_name in self.nick_team_colors:
            team_name, color_code = self._get_nicked_player_team_info(player_name)
        # Handle regular players
        else:
            team_name, color_code = self._get_regular_player_team_info(player_name)

        # Convert team name to letter using constant mapping
        letter = TEAM_NAME_TO_LETTER.get(team_name.lower(), "?")

        # Ensure we have a color code - map from letter if needed
        if not color_code:
            color_code = TEAM_LETTER_TO_CODE.get(letter, "§f")

        return TeamColor(
            letter=letter,
            code=color_code,
            name=team_name.title(),
        )

    def _get_own_team_info(self) -> tuple[str, str]:
        """Get team name and color code for the current user."""
        try:
            # First try normal team detection
            team = self.get_team(self.username)
            if team:
                team_name = re.sub(r"\d+", "", team.name)
                m = COLOR_CODE.search(team.prefix)
                color_code = m.group(1) if m else ""
                return team_name, color_code
            raise ValueError("No team found")
        except (ValueError, AttributeError):
            # Fall back to sidebar detection
            sidebar_own_team = next(
                (
                    team
                    for team in self.gamestate.teams.values()
                    if "YOU" in team.suffix
                ),
                None,
            )
            if sidebar_own_team is None:
                raise ValueError(
                    "Player is not on a team; cannot determine own team color."
                )

            match_ = re.search(r"§[a-f0-9](\w+)(?=§f:)", sidebar_own_team.prefix)
            if match_:
                team_name = match_.group(1)
                m = COLOR_CODE.search(sidebar_own_team.prefix)
                color_code = m.group(1) if m else ""
                return team_name, color_code
            else:
                raise ValueError(
                    f"Could not determine own team color; regex did not match prefix {sidebar_own_team.prefix!r}"
                )

    def _get_nicked_player_team_info(self, player_name: str) -> tuple[str, str]:
        """Get team name and color code for a nicked player."""
        m = COLOR_CODE.search(self.nick_team_colors[player_name])
        color_code = m.group(1) if m else ""
        # Use constant mapping instead of inline dict
        team_name = COLOR_CODE_TO_NAME.get(color_code, "Unknown")
        return team_name, color_code

    def _get_regular_player_team_info(self, player_name: str) -> tuple[str, str]:
        """Get team name and color code for a regular player."""
        team = self.get_team(player_name)
        if not team:
            raise ValueError(f"Provided player {player_name} is not on a team!")

        team_name = re.sub(r"\d+", "", team.name)
        color_code = ""
        if team.prefix:
            m = COLOR_CODE.search(team.prefix)
            color_code = m.group(1) if m else ""

        return team_name, color_code

    async def _update_stats(self):
        """
        Update stats in tab list.
        Calls stat highlights function once all players from /who have stats
        """
        async with self.player_stats_lock:
            await self.received_locraw.wait()

            # CHECKS

            if not self.players_without_stats:
                # No players to update stats for
                return

            # update stats in tab in a game, bw supported so far
            if self.game.gametype not in {"bedwars"}:
                return

            # not in an updatable stats mode
            if not self.game.mode:
                return

            if not any(
                (
                    self.settings.bedwars.tablist.show_stats.get() != "OFF",
                    self.settings.bedwars.display_top_stats.get() != "OFF",
                )
            ):
                return

            player_stats = asyncio.as_completed(
                self._get_player(player) for player in self.players_without_stats
            )

            # the first 3 if cases here just run some checks on the players
            # TODO: could move out into like a _check_player function
            # ^ to improve readability
            # -----------
            # the rest of this for loop gets player display names
            for result in player_stats:
                expected_name = ""
                try:
                    result = await result
                    expected_name, player_result = result.copy().popitem()
                except PlayerNotFound as player:  # assume nick
                    # I don't actually know if we can assume this is a string
                    # but I want the type checker to be friendly to me
                    # later when I casefold it
                    nick_username: str = player.player
                    player_result = Nick(nick_username)
                    try:
                        player_result.uuid = next(
                            u
                            for u, p in self.players.items()
                            # casefold shouldn't technically be necessary here?
                            # but just in case...
                            if p.casefold() == nick_username.casefold()
                        )
                    except StopIteration:
                        # idk why this would happen tbh
                        # I think when I wrote this code initially I had a reason
                        continue
                except (
                    InvalidApiKey,
                    RateLimitError,
                    TimeoutError,
                    asyncio.TimeoutError,
                    ApiError,
                ) as player:
                    err_message = {
                        InvalidApiKey: TextComponent("Invalid API Key!").color("red"),
                        KeyRequired: TextComponent("No API Key provided!").color("red"),
                        RateLimitError: TextComponent("Rate limit!").color("red"),
                        TimeoutError: TextComponent(
                            f"Request timed out! ({player})"
                        ).color("red"),
                        asyncio.TimeoutError: TextComponent(
                            f"Request timed out! ({player})"
                        ).color("red"),
                        ApiError: TextComponent(
                            f"An API error occurred with the Hypixel API! ({player})"
                        ).color("red"),
                    }

                    # if an error message hasn't already been sent in this game
                    # game being hypixel sub-server, clears on packet_join_game
                    if not self.game_error:
                        self.game_error = player
                        self.client.chat(err_message[type(player)])

                    continue
                except Exception as player:
                    if not self.game_error:
                        self.game_error = player
                        self.client.chat(
                            TextComponent(
                                f"An unknown error occurred! ({player})"
                            ).color("red")
                        )

                    continue

                if not isinstance(player := player_result, (Player, Nick)):
                    # TODO log this -- also why does this occur?
                    # supposedly session is closed (?)
                    continue

                if expected_name and (expected_name != player.name):
                    # assume nick -- TODO: should we assume this?
                    # no I am NOT chat gpt despite the em dash ):
                    player = Nick(player.name)
                    # i really hope this owrks because I am NOT testing ts
                    # btw this diff is made by kavi but i am too lazy to
                    # change hte commiter btw 👍🏻

                if player.name in self.players.values():
                    # Only cache actual Player objects, not Nick objects
                    if not isinstance(player, (PlayerNotFound, Nick)):
                        self._cached_players[player.name] = player
                        bedwars_data = player._data.get("stats", {}).get("Bedwars", {})
                        fdict: dict[str, Any] | Nick = dict(
                            format_bedwars_dict(bedwars_data)
                        )
                        fdict["star"] = format_bw_star(player.bedwars.level)
                        fdict["raw_level"] = player.bedwars.level
                        fdict["raw_fkdr"] = player.bedwars.fkdr
                        fdict["rankname"] = get_rankname(player)
                        fdict["raw_name"] = player.name
                    else:  # if is a nicked player
                        # get team color for nicked player
                        for team in self.gamestate.teams.values():
                            if player.name in team.members:
                                self.nick_team_colors.update({player.name: team.prefix})
                                break
                        fdict = player

                    display_name = self._build_player_display_name(player.name, fdict)

                    self.players_with_stats[player.name] = {
                        "uuid": player.uuid,
                        "display_name": display_name,
                        "fplayer": fdict,
                    }

                    if self.settings.bedwars.tablist.show_stats.get() == "ON":
                        if player.name in self.dead | self.final_dead:
                            # dead players get grayed-out names
                            display_name = self._get_dead_display_name(player.name)
                        self._send_tablist_update(str(player.uuid), display_name)

        # if we've gotten everyone from /who, stat highlights can be called
        if self.settings.bedwars.display_top_stats.get() != "OFF":
            if not self.stats_highlighted:
                await self.stat_highlights()
                self.stats_highlighted = True

        self.update_stats_complete.set()  # emit an event to say we've finished statchecks

    async def highlight_adjacent_teams(self) -> None:
        """Waits until stats are updated; displays a title card with stats of adjacent team(s)."""
        await self.update_stats_complete.wait()
        if not self._api_key_valid:
            return
        if self.game.map is None:
            raise ValueError("Could not determine map!")
        try:
            side_rush, alt_rush = self.get_adjacent_teams()
        except ValueError:  # player is not on a team
            return
        side_players = self.get_players_on_team(side_rush)
        alt_players = self.get_players_on_team(alt_rush)

        if self.game.map.rush_direction == "side":
            first_rush, first_players = side_rush, side_players
            other_adjacent_rush, other_adjacent_players = alt_rush, alt_players
        elif self.game.map.rush_direction == "alt":
            first_rush, first_players = alt_rush, alt_players
            other_adjacent_rush, other_adjacent_players = side_rush, side_players
        else:
            raise ValueError(
                f'Expected Literal "side" or "alt" for self.game.map.rush_direction; got {self.game.map.rush_direction} instead.'
            )

        empty_team_dialogue_first = (
            TextComponent(f"{first_rush.upper()} TEAM")
            .color(first_rush)  # type: ignore
            .appends(TextComponent("is empty!").color("red"))
        )
        empty_team_dialogue_alt = (
            TextComponent(f"{other_adjacent_rush.upper()} TEAM")
            .color(other_adjacent_rush)  # type: ignore
            .appends(TextComponent("is empty!").color("red"))
        )

        # key to sort player stats with sorted()
        key: Callable[[dict], float]
        if self.settings.bedwars.display_top_stats.get() in {"OFF", "INDEX"}:
            key = lambda fp: fp["raw_fkdr"] ** 2 * fp["raw_level"]  # noqa: E731
        elif self.settings.bedwars.display_top_stats.get() == "STAR":
            key = lambda fp: fp["raw_level"]  # noqa: E731
        elif self.settings.bedwars.display_top_stats.get() == "FKDR":
            key = lambda fp: fp["raw_fkdr"]  # noqa: E731
        else:
            raise ValueError(
                f'Expected "OFF", "INDEX", "STAR", or "FKDR" for setting bedwars.display_top_stats; got {self.settings.bedwars.display_top_stats.get()} instead.'
            )

        subtitle = None

        match len(first_players):
            case 0:  # team empty or disconnected
                title = empty_team_dialogue_first
            case 1:  # solos or doubles with 1 disconnect
                title = self.players_with_stats[first_players[0]]["display_name"]
            case (
                2
            ):  # team of 2; calculate which one has better stats based on user pref
                fp1 = self.players_with_stats[first_players[0]]["fplayer"]
                fp2 = self.players_with_stats[first_players[1]]["fplayer"]

                if isinstance(fp1, Nick):
                    better = fp1
                    worse = fp2
                elif isinstance(fp2, Nick):
                    better = fp2
                    worse = fp1
                else:
                    better, worse = sorted((fp1, fp2), key=key, reverse=True)

                if isinstance(better, dict):
                    title = self.players_with_stats[better["raw_name"]]["display_name"]
                else:
                    title = self.players_with_stats[better.name]["display_name"]

                if self.settings.bedwars.announce_first_rush.get() == "FIRST RUSH":
                    # if we aren't showing alt rush team stats, we can show both players from first rush
                    if isinstance(worse, dict):
                        subtitle = self.players_with_stats[worse["raw_name"]][
                            "display_name"
                        ]
                    else:
                        subtitle = self.players_with_stats[worse.name]["display_name"]
            case _:
                raise ValueError(
                    f"wtf how are there {len(first_players)} ppl on that team???\nplayers on first rush team: {first_players}"
                )

        if self.settings.bedwars.announce_first_rush.get() == "BOTH ADJACENT":
            match len(other_adjacent_players):
                case 0:
                    subtitle = empty_team_dialogue_alt
                case 1:
                    subtitle = self.players_with_stats[other_adjacent_players[0]][
                        "display_name"
                    ]
                case 2:
                    fp1 = self.players_with_stats[other_adjacent_players[0]]["fplayer"]
                    fp2 = self.players_with_stats[other_adjacent_players[1]]["fplayer"]
                    if isinstance(fp1, Nick):
                        better = fp1
                        worse = fp2
                    elif isinstance(fp2, Nick):
                        better = fp2
                        worse = fp1
                    else:
                        better, worse = sorted((fp1, fp2), key=key, reverse=True)

                    if isinstance(better, dict):
                        subtitle = self.players_with_stats[better["raw_name"]][
                            "display_name"
                        ]
                    else:
                        subtitle = self.players_with_stats[better.name]["display_name"]
                case _:
                    raise ValueError(
                        f"wtf how are there {len(other_adjacent_players)} ppl on that team???\nplayers on alt rush team: {other_adjacent_players}"
                    )
        self.client.reset_title()
        self.client.set_title(title=title, subtitle=subtitle)
        # raise ValueError(
        #   f'Expected "FIRST RUSH", "BOTH ADJACENT", or "OFF" state for setting bedwars.announce_first_rush; got {self.settings.bedwars.announce_first_rush.state} instead.'
        # )
        self.adjacent_teams_highlighted = True

    def get_adjacent_teams(self) -> tuple[str, str]:
        """Get the (side_rush, alt_rush) teams for the current player.

        Returns:
            Tuple of (side_rush_color, alt_rush_color)

        Raises:
            ValueError: If player is not on a team
        """
        team = self.get_team_color(self.username)["name"].lower()
        # will raise ValueError if player is not on a team; handle!

        side_rush = RUSH_MAPPINGS["default_mappings"]["side_rushes"][team]
        alt_rush = RUSH_MAPPINGS["default_mappings"]["alt_rushes"][team]

        return (side_rush, alt_rush)

    def get_players_on_team(self, color: str) -> list[str]:
        """Get a de-duplicated list of player names on the given team color.

        Args:
            color: Team color name (case-insensitive: 'green', 'Green', 'GREEN', etc.)

        Returns:
            List of player names on that team
        """
        target = color.lower()
        players: set[str] = set()
        for team in self.gamestate.teams.values():
            # team names like 'Green8', 'Green9' -> strip digits to get color
            base_color = re.sub(r"\d", "", team.name).lower()
            if base_color == target:
                players.update(team.members)
        return list(players)

    async def stat_highlights(self):
        """Display top 3 enemy players and nicked players."""
        if not self.players_with_stats:
            return "No stats found!"

        own_team_color = self.get_team_color(self.username)["name"]

        # find team color as str (e.g. Pink, Blue, etc.)
        # TODO: move to method?

        enemy_players = []
        enemy_nicks = []

        # Process each player
        for player_name, player_data in self.players_with_stats.items():
            display_name = player_data["display_name"]
            # Skip the user's own nickname
            if player_name == self.username:
                continue

            # Get player's team
            player_team = self.get_team(player_name)

            if not player_team:
                continue

            # Skip teammates
            if own_team_color == re.sub(r"\d", "", player_team.name):
                continue

            # Handle nicked players
            if "[NICK]" in display_name:
                nick_team_color = self.nick_team_colors.get(player_name, "")
                enemy_nicks.append(f"{nick_team_color}{player_name}§f")
                continue

            # Handle regular players with stats
            fdict = player_data["fplayer"]
            if isinstance(fdict, dict):
                # Calculate ranking value
                if self.settings.bedwars.tablist.is_mode_specific.get() == "ON":
                    mode = self.game.mode[8:].lower()
                    fkdr = fdict[f"{mode}_fkdr"]
                    f_fkdr = fdict[f"{mode}_fkdr"]
                else:
                    fkdr = fdict["raw_fkdr"]
                    f_fkdr = fdict["fkdr"]

                fkdr = int(fdict["raw_fkdr"])
                stars = int(fdict["raw_level"])

                if self.settings.bedwars.display_top_stats.get() == "FKDR":
                    rank_value = fkdr
                elif self.settings.bedwars.display_top_stats.get() == "STARS":
                    rank_value = stars
                elif self.settings.bedwars.display_top_stats.get() == "INDEX":
                    rank_value = fkdr**2 * stars
                else:
                    rank_value = fkdr

                enemy_players.append(
                    {
                        "name": player_name,
                        "star_formatted": fdict["star"],
                        "fkdr_formatted": f_fkdr,
                        "rank_value": rank_value,
                        "team_color": player_team.prefix,
                    }
                )

        # Build output
        result = ""

        # Add nicks section
        if enemy_nicks:
            result += f"§5§lNICKS§r: {', '.join(enemy_nicks)}"
            if enemy_players:
                result += "\n\n"

        # Add top 3 enemy players
        if enemy_players:
            top_players = sorted(
                enemy_players, key=lambda x: x["rank_value"], reverse=True
            )[:3]
            for i, player in enumerate(top_players, 1):
                if i > 1:
                    result += "\n"
                result += f"§f§l{i}§r: {player['star_formatted']} {player['team_color']}{player['name']}; FKDR: {player['fkdr_formatted']}"
        elif not enemy_nicks:
            result = "No stats found!"

        self.client.chat(
            TextComponent("\nTop stats:\n\n")
            .color("gold")
            .bold()
            .append(result)
            .append("\n")
        )

    def get_team(self, user: str) -> Optional[Team]:
        """
        Get user's team. Returns team name or None if not found.
        Specifically, only looks for user's team in Bedwars games
        Currently only supports bedwars in-game.
        """

        real_player_teams: list[Team] = [
            team
            for team in self.gamestate.teams.values()
            if re.match("§.§l[A-Z] §r§.", team.prefix)
        ]
        return next(
            (team for team in real_player_teams if user in team.members),
            None,
        )

    def keep_player_stats_updated(self) -> None:
        """Update all living players' display names in the tab list.

        This ensures player stats stay updated even when Hypixel resets the tab list.
        """
        if self.settings.bedwars.tablist.show_stats.get() != "ON":
            return

        # Get all living players (not dead or final dead)
        living_players = [
            (d["uuid"], d["display_name"])
            for player_name, d in self.players_with_stats.items()
            if player_name not in self.dead and player_name not in self.final_dead
        ]

        self._send_bulk_tablist_update(living_players)

    @subscribe(r"chat:server:.* has joined .*!")  # listens, does not replace
    async def _statcheck_event_chat_server_player_joined(self, buff: Buffer):
        self.client.send_packet(0x02, buff.getvalue())
        if self.settings.bedwars.api_key_reminder.get() == "ON":
            message = buff.unpack(Chat)
            m = JOIN_RE.match(message)
            if m and m.group("ign").casefold() == self.username.casefold():
                # Ensure we have a recent validation
                now = asyncio.get_event_loop().time()
                needs_validation = self._api_key_valid is None or (
                    self._api_key_validated_at
                    and now - self._api_key_validated_at > 300
                )
                if needs_validation:
                    await self.validate_api_key()

                if self._api_key_valid is False:  # only warn if explicitly invalid
                    self.client.chat(
                        TextComponent("Invalid API key! ")
                        .color("red")
                        .append(
                            TextComponent("(developer.hypixel.net)")
                            .underlined()
                            .click_event(
                                "open_url", "https://developer.hypixel.net/dashboard/"
                            )
                            .color("gray")
                        )
                    )

    @subscribe("chat:server:ONLINE: .*")
    async def _statcheck_event_chat_server_who(self, buff: Buffer):
        message = buff.unpack(Chat)

        if not self.received_who.is_set():
            self.received_who.set()
        else:
            self.client.send_packet(0x02, buff.getvalue())

        self.players_without_stats.update(message.removeprefix("ONLINE: ").split(", "))
        self.players_without_stats.difference_update(
            set(self.players_with_stats.keys())
        )
        return await self._update_stats()

    def get_player_to_uuid_mapping(self) -> dict[str, str]:
        """Get a mapping of player names to UUIDs."""
        return {v: k for k, v in self.players.items()}

    @subscribe(
        "chat:server:(You will respawn in 10 seconds!|Your bed was destroyed so you are a spectator!)"
    )
    async def _statcheck_event_chat_server_bedwars_rejoin(self, buff: Buffer):
        self.client.send_packet(0x02, buff.getvalue())

        message = buff.unpack(Chat)
        # refresh stats
        self.players_without_stats.add(self.username)  # TODO: does not work with nicks
        self.server.send_packet(0x01, String("/who"))
        self.received_who.clear()

        self.game.started = True

        if "spectator" in message:
            # TODO: does not work with nicks
            self.final_dead[self.username] = self.get_player_to_uuid_mapping()[
                self.username
            ]
            self._send_tablist_update(
                self.get_player_to_uuid_mapping()[self.username],
                self._get_dead_display_name(self.username),
            )

    def in_bedwars_game(self):
        return self.game.gametype == "bedwars" and self.game.mode

    @subscribe(f"chat:server:({'|'.join(GAME_START_MESSAGES)})")
    async def _statcheck_event_chat_server_game_start(self, buff: Buffer):
        if self.game.gametype != "bedwars" or self.stats_highlighted:
            return self.client.send_packet(0x02, buff.getvalue())

        message = buff.unpack(Chat)

        if self.settings.bedwars.display_top_stats.get() == "OFF":
            self.client.send_packet(0x02, buff.getvalue())

        if message in {msg_set[-2] for msg_set in GAME_START_MESSAGE_SETS}:  # runs once
            if (
                self.settings.bedwars.announce_first_rush.get() != "OFF"
                and self.game.mode.lower() in {"bedwars_eight_one", "bedwars_eight_two"}
                and not self.adjacent_teams_highlighted
            ):
                # get first rush stats
                # there's no well-defined first rush for 3s/4s so we only do this for solos and doubles
                asyncio.create_task(self.highlight_adjacent_teams())

            # replace them with the statcheck overview
            if self.settings.bedwars.display_top_stats.get() != "OFF":
                self.client.chat(
                    TextComponent("Fetching top stats...").color("gold").bold()
                )
            self.server.send_packet(0x01, String("/who"))
            self.received_who.clear()
            self.game.started = True

    @command("key", "apikey")
    async def _command_key(self, key: str):
        """Set your Hypixel API key. Usage: /key <api_key>"""
        try:
            new_client = hypixel.Client(key)
            await new_client.player("gamerboy80")  # test key
        except (InvalidApiKey, KeyRequired, ApiError):
            raise CommandException("Invalid API Key!")
        else:
            if new_client:
                await new_client.close()

        if self.hypixel_client:
            await self.hypixel_client.close()

        self.hypixel_api_key = key  # type: ignore
        self.hypixel_client = hypixel.Client(key)
        self._api_key_valid = True
        self._api_key_validated_at = asyncio.get_event_loop().time()

        self.game_error = None
        self.client.chat(TextComponent("Updated API Key!").color("green"))

        await self._update_stats()
        if not self.stats_highlighted:
            if self.settings.bedwars.display_top_stats.get() != "OFF":
                await self.stat_highlights()

    def match_kill_message(self, message: str) -> Optional[re.Match]:
        """Match a kill message against known patterns.

        Returns:
            Match object if message matches a kill pattern, None otherwise
        """
        for pattern in KILL_MSGS:
            match = re.match(pattern, message)
            if match:
                return match  # Only 3 groups: victim, killer, final_kill
        return None

    async def respawn_timer(self, player: str, reconnect: bool = False) -> None:
        """Display a countdown timer in the tab list for respawning players."""
        if not self.settings.bedwars.tablist.show_respawn_timer.get() == "ON":
            return

        # "there are only two hard things in computer science: cache invalidation and naming things"
        u = minecraft_uuid_v2()
        self.dead[player] = str(u)

        # remove player from tablist
        # hypixel already does this for other players
        # but not for the user themselves
        real_u = self.get_player_to_uuid_mapping().get(player) or ""
        if real_u:
            self.client.send_packet(
                0x38,
                VarInt(4),
                VarInt(1),
                UUID.pack(uuid.UUID(real_u)),
            )

        # spawn player
        self.client.send_packet(
            0x38,
            VarInt(0),
            VarInt(1),
            UUID.pack(uuid.UUID(self.dead[player])),
            String(player),
            VarInt(0),  # 0 properties
            VarInt(3),  # gamemode
            VarInt(0),  # ping
            Boolean(True),
            Chat.pack(self._get_dead_display_name(player)),
        )

        timer_duration = 10 if reconnect else 5
        player_uuid = self.dead[player]

        for s in range(timer_duration, 0, -1):
            display_name = f"§6§l{s}s {self._get_dead_display_name(player)}"
            self._send_tablist_update(player_uuid, display_name)
            await asyncio.sleep(1)

        try:
            del self.dead[player]
        except KeyError:
            pass  # already removed; e.g. self.dead was cleared on new game join

        self.client.send_packet(
            0x38,
            VarInt(4),
            VarInt(1),
            UUID.pack(uuid.UUID(player_uuid)),
        )

    @subscribe(r"chat:server:(.+?) reconnected\.$")
    async def _statcheck_event_chat_server_player_recon(self, buff: Buffer):
        self.client.send_packet(0x02, buff.getvalue())

        await self.received_locraw.wait()  # so that we can run the next check
        if not self.in_bedwars_game():
            return

        message = buff.unpack(Chat)
        player = message.split(" ")[0]

        retries = 0
        while player not in self.get_player_to_uuid_mapping():
            if retries >= 50:
                return  # give up after 5 seconds
                # i don't *think* this should ever happen, but just in case
            await asyncio.sleep(0.1)
            retries += 1

        asyncio.create_task(self.respawn_timer(player, reconnect=True))

    @subscribe(f"chat:server:{'|'.join(KILL_MSGS)}")
    async def _statcheck_event_chat_server_kill_msg(self, buff: Buffer):
        if not self.in_bedwars_game():
            return self.client.send_packet(0x02, buff.getvalue())

        self.client.send_packet(0x02, buff.getvalue())
        message = buff.unpack(Chat)

        if message.startswith("BED DESTRUCTION >"):
            # some kill messages match bed destroy messages
            return

        m = self.match_kill_message(message)
        if not m:
            return
        killed = m.group(1)
        fk = message.endswith("FINAL KILL!")

        if message.endswith("disconnected."):
            return  # TODO: what to do here?

        if fk:
            self.final_dead[killed] = str(u := minecraft_uuid_v2())
            if self.settings.bedwars.tablist.show_eliminated_players.get() == "ON":
                self.client.send_packet(
                    0x38,
                    VarInt(0),  # spawn player
                    VarInt(1),  # number of players
                    UUID.pack(u),
                    String(killed),
                    VarInt(0),
                    VarInt(3),  # gamemode; spectator
                    VarInt(0),  # ping
                    Boolean(True),
                    Chat.pack(self._get_dead_display_name(killed)),
                )
        else:
            asyncio.create_task(self.respawn_timer(killed))
