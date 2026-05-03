import asyncio
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

import hypixel
import keyring
from hypixel import (
    ApiError,
    InvalidApiKey,
    KeyRequired,
    MalformedApiKey,
    Player,
    PlayerNotFound,
    RateLimitError,
    TimeoutError,
)
from petty.events import listen_server, subscribe
from petty.protocol.datatypes import (
    UUID,
    Boolean,
    Buffer,
    Byte,
    Chat,
    String,
    TextComponent,
    VarInt,
)
from platformdirs import user_cache_dir

from assets import load_json_asset
from plugins.commands import CommandException, command
from proxhy.utils import offline_uuid
from proxhypixel.formatting import (
    format_player_dict,
)

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin

BW_MAPS: dict = load_json_asset("bedwars_maps.json")
RUSH_MAPPINGS = load_json_asset("rush_mappings.json")
KILL_MSGS: list[str] = load_json_asset("bedwars_chat.json")["kill_messages"]

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
        "                              Bed Wars Rush",
        "     All generators are maxed! Your bed has three",
        "       layers of protection! Left click while holding",
        "                 wool to activate bridge building!",
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ],
    [
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "                           Bed Wars Ultimate",
        "          Select an ultimate in the store! They will",
        "                     be enabled in 10 seconds!",
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
        "     Every few seconds brings a new surprise! Use",
        "        these items to defend your bed or destroy",
        "                                enemy beds.",
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    ],
    [
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
        "                             Bed Wars Duels",
        "      Protect your bed and destroy the enemy bed.",
        "         Upgrade yourself by collecting Iron, Gold,",
        "    Emerald and Diamond from generators to access",
        "                          powerful upgrades.",
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
TEAM_COLOR_CODE = re.compile(r"(§[0-9a-f])", re.IGNORECASE)
TEAM_COLOR_NAME = re.compile(
    r"\b(?:green|yellow|aqua|white|pink|gray|red|blue)\d+\b", re.IGNORECASE
)

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


@dataclass
class TeamColor:
    letter: str
    code: str
    name: str
    prefix: str = field(init=False)

    def __post_init__(self):
        self.prefix = f"{self.code}§l{self.letter}"

    @classmethod
    def from_letter(cls, letter: str):
        letter = letter.upper()
        if letter not in TEAM_LETTER_TO_CODE:
            raise ValueError(f"Invalid team letter: {letter}")

        code = TEAM_LETTER_TO_CODE[letter]
        name = COLOR_CODE_TO_NAME.get(code, "Unknown")

        return cls(letter=letter, code=code, name=name)

    @classmethod
    def from_name(cls, name: str):
        key = name.lower()
        if key not in TEAM_NAME_TO_LETTER:
            raise ValueError(f"Invalid team name: {name}")

        letter = TEAM_NAME_TO_LETTER[key]
        code = TEAM_LETTER_TO_CODE[letter]
        display_name = COLOR_CODE_TO_NAME.get(code, name.capitalize())

        return cls(letter=letter, code=code, name=display_name)


@dataclass
class PlayerWithStats:
    uuid: str
    display_name: str
    fplayer: dict[str, str | int | float] | Nick
    team: TeamColor


class GamePlayerStatus(StrEnum):
    ALIVE = auto()
    RESPAWNING = auto()
    FINALED = auto()


@dataclass
class Nick:
    name: str
    uuid: str


@dataclass
class GamePlayer:
    username: str
    uuid: str  # offline_uuid for respawning / finaled
    team: TeamColor
    status: GamePlayerStatus

    display_name: Optional[str] = None
    fplayer: Optional[dict[str, Any] | Nick] = None
    offline_uuid: str = field(init=False)

    def __post_init__(self):
        self.default_display_name = f"{self.team.prefix} {self.username}"
        self.offline_uuid = str(offline_uuid(self.username))


class StatCheckPlugin:
    nick_team_colors: dict[str, str]
    final_dead: dict[str, str]
    dead: dict[str, str]
    _cached_players: dict
    game_players: dict[str, GamePlayer]
    _hypixel_api_key: str
    game_error: Optional[Exception]
    stats_highlighted: bool
    adjacent_teams_highlighted: bool
    _api_key_valid: bool | None
    update_stats_complete: asyncio.Event
    hypixel_client: hypixel.Client
    hypixel_api_key: str
    _build_player_display_name: Callable[[str, dict | Nick], str]

    def _init_statcheck(self: ProxhyPlugin):
        self._cached_players: dict = {}
        # players from packet_player_list_item
        self.game_players = {}  # username: player object (see above)
        self._hypixel_api_key = ""

        self.game_error = None  # if error has been sent that game
        self.stats_highlighted = False
        self.adjacent_teams_highlighted = False

        self.player_stats_queue: asyncio.Queue[GamePlayer] = asyncio.Queue()

        self.log_path = (
            Path(user_cache_dir("proxhy", ensure_exists=True)) / "stat_log.jsonl"
        )
        self._api_key_valid: bool | None = None

        self.update_stats_complete = asyncio.Event()

        # _update_stats
        self.player_stats_task: Optional[asyncio.Task[None]] = None
        # list of tasks spawned by _update_player_stats
        self.player_stats_tasks: list[asyncio.Task[None]] = list()
        # players from /who
        self.who_players: set[str] = set()

        self.who_players_statted = asyncio.Event()

    @property
    def dead(self: ProxhyPlugin) -> dict[str, GamePlayer]:
        return {
            player.username: player
            for player in self.game_players.values()
            if player.status == GamePlayerStatus.RESPAWNING
        }

    @property
    def final_dead(self: ProxhyPlugin) -> dict[str, GamePlayer]:
        return {
            player.username: player
            for player in self.game_players.values()
            if player.status == GamePlayerStatus.FINALED
        }

    @property
    def all_players(self: ProxhyPlugin) -> set[str]:
        all_players = self.real_players()

        if self.settings.bedwars.tablist.show_eliminated_players.get() == "ON":
            all_players |= set(self.final_dead.keys())
        if self.settings.bedwars.tablist.show_respawn_timer.get() == "ON":
            all_players |= set(self.dead.keys())

        return all_players

    @property
    def players_with_stats(self: ProxhyPlugin) -> dict[str, PlayerWithStats]:
        return {
            player.username: PlayerWithStats(
                player.uuid, player.display_name, player.fplayer, player.team
            )
            for player in self.game_players.values()
            if player.fplayer is not None and player.display_name is not None
        }

    @property
    def hypixel_api_key(self) -> str:
        if self._hypixel_api_key:
            return self._hypixel_api_key

        return keyring.get_password("proxhy", "hypixel_api_key") or ""

    @hypixel_api_key.setter
    def hypixel_api_key(self: ProxhyPlugin, key: str):
        self._hypixel_api_key = key

        keyring.set_password("proxhy", "hypixel_api_key", key)

    async def validate_api_key(self: ProxhyPlugin) -> bool:
        """Validate the Hypixel API key by making a test request."""

        try:
            await self.hypixel_client.player_count()
            self._api_key_valid = True
        except (InvalidApiKey, KeyRequired):
            self._api_key_valid = False

        return self._api_key_valid

    # Helper methods for common operations

    def _send_tablist_update(
        self: ProxhyPlugin, player_uuid: str, display_name: str, listed: bool = True
    ) -> None:
        """Send a packet to update a player's display name in the tab list."""
        self.downstream.send_packet(
            0x38,
            VarInt.pack(3),
            VarInt.pack(1),
            UUID.pack(uuid.UUID(player_uuid)),
            Boolean.pack(listed),
            Chat.pack(display_name),
        )

    def _send_bulk_tablist_update(self: ProxhyPlugin, updates: list[tuple[str, str]]):
        """Send a packet to update multiple players' display names in the tab list.

        Args:
            updates: List of (player_uuid, display_name) tuples
        """
        if not updates:
            return

        self.downstream.send_packet(
            0x38,
            VarInt.pack(3),
            VarInt.pack(len(updates)),
            *(
                UUID.pack(uuid.UUID(str(player_uuid)))
                + Boolean.pack(True)
                + Chat.pack(display_name)
                for player_uuid, display_name in updates
            ),
        )

    def _build_player_display_name(self: ProxhyPlugin, player: GamePlayer) -> str:
        fdict = player.fplayer

        if fdict is None:
            return player.default_display_name

        team_color = player.team

        if isinstance(fdict, Nick):
            return f"{team_color.prefix} §5[NICK] {player.username}"

        if (
            self.settings.bedwars.tablist.is_mode_specific.get() == "ON"
            and self.game.mode
        ):
            mode = self.game.mode[8:].lower()
            fkdr = fdict[f"{mode}_fkdr"]
        else:
            fkdr = fdict["fkdr"]

        show_rankname = self.settings.bedwars.tablist.show_rankname.get() == "ON"
        name = fdict["rankname"] if show_rankname else fdict["raw_name"]

        display_name = " ".join(
            (
                f"{fdict['star']}{team_color.code}",
                name,
                f"§7| {fkdr}",
            )
        )

        return f"{team_color.prefix} {display_name}"

    def _get_dead_display_name(self: ProxhyPlugin, player: GamePlayer) -> str:
        # TODO: merge with _build_player_display_name?
        # that way logic can be consolidated, just build
        # player display name for any player
        # or could just make player.display_name this when finaled etc. idk
        """Get the grayed-out display name for a dead player.

        Args:
            player_name: The player's name

        Returns:
            The formatted display name with gray color codes
        """
        # Use bold+italic for current user, just italic for others
        color = "§7§l§o" if player.username == self.username else "§7§o"

        if (
            player.display_name is not None
            and self.settings.bedwars.tablist.show_stats.get() == "ON"
        ):
            display_name = player.display_name
        else:
            display_name = f"{player.team.prefix} {player.username}"

        unformatted_name = re.sub(r"§[0-9a-fr]", "", display_name)
        return color + unformatted_name

    def _update_dead_players_in_tablist(self: ProxhyPlugin):
        """Update all final dead players in the tab list with grayed-out display names."""
        # TODO: this should update respawning players
        for player in self.final_dead.values():
            display_name = self._get_dead_display_name(player)
            self._send_tablist_update(player.uuid, display_name)

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self: ProxhyPlugin, _):
        for player in (self.dead | self.final_dead).values():
            self.downstream.send_packet(
                0x38,
                VarInt.pack(4),
                VarInt.pack(1),
                UUID.pack(uuid.UUID(player.uuid)),
            )

        # flush player lists
        self.game_players.clear()
        self.who_players.clear()

        self.who_players_statted.clear()
        self.game_error = None
        self.stats_highlighted = False
        self.adjacent_teams_highlighted = False

        if self.player_stats_task:
            self.player_stats_task.cancel()
        while not self.player_stats_queue.empty():
            self.player_stats_queue.get_nowait()

        for task in self.player_stats_tasks:
            task.cancel()

        self.player_stats_task = self.create_task(self._update_stats())

    def _rebuild_stats(self: ProxhyPlugin):
        for player in self.game_players.values():
            # if has stats, refresh display name
            if player.fplayer is not None:
                player.display_name = self._build_player_display_name(player)

        if self.settings.bedwars.tablist.show_stats.get() == "ON":
            # if we are showing stats, go ahead and ONLY update
            # those who have stats
            updates = [
                (player.uuid, player.display_name)
                for player in self.game_players.values()
                if player.display_name
            ]
            self._send_bulk_tablist_update(updates)
        else:
            # if we are not showing stats, remove display names
            # from all players who have stats
            self.downstream.send_packet(
                0x38,
                VarInt.pack(3),
                VarInt.pack(len(self.game_players.values())),
                # TODO: change to only players_with_stats
                *(
                    UUID.pack(uuid.UUID(str(player.uuid))) + Boolean.pack(False)
                    for player in self.game_players.values()
                ),
            )

        self._update_dead_players_in_tablist()

    @subscribe("setting:bedwars.tablist.show_stats")
    async def _statcheck_event_setting_bedwars_tablist_show_stats(
        self: ProxhyPlugin, _match, data: list
    ):
        if not await self.validate_api_key():
            self.downstream.chat(
                TextComponent(
                    "Invalid Hypixel API Key; will not be able to refresh stats in tab!"
                ).color("red")
            )

        self._rebuild_stats()

    @subscribe("setting:bedwars.tablist.is_mode_specific")
    async def _statcheck_event_setting_bedwars_tablist_is_mode_specific(
        self: ProxhyPlugin, _match, data: list
    ) -> None:
        self._rebuild_stats()

    async def _reset_stats(self: ProxhyPlugin) -> None:
        self._rebuild_stats()

    @subscribe("setting:bedwars.tablist.show_rankname")
    async def _statcheck_event_setting_bedwars_tablist_show_rankname(
        self: ProxhyPlugin, _match, data: list
    ) -> None:
        """Callback when show_rankname setting changes - rebuild display names."""
        self._rebuild_stats()

    @subscribe("setting:bedwars.tablist.show_eliminated_players")
    async def _statcheck_event_setting_bedwars_tablist_show_eliminated_players(
        self: ProxhyPlugin, _match, data: list
    ) -> None:
        # remove self from final_dead
        final_dead_no_self = self.final_dead.copy()
        if self.username in final_dead_no_self:
            # TODO: does not work with nicks
            del final_dead_no_self[self.username]

        if data == ["OFF", "ON"]:
            packet = VarInt.pack(0) + VarInt.pack(len(final_dead_no_self))
            for player in final_dead_no_self.values():
                packet += UUID.pack(uuid.UUID(player.uuid))
                packet += String.pack(player.username)
                packet += VarInt.pack(0)  # properties
                packet += VarInt.pack(3)  # gamemode; spectator
                packet += VarInt.pack(0)  # ping
                packet += Boolean.pack(True)  # has display name
                packet += Chat.pack(self._get_dead_display_name(player))

            self.downstream.send_packet(0x38, packet)
        elif data == ["ON", "OFF"]:
            packet = VarInt.pack(4) + VarInt.pack(len(final_dead_no_self))
            for player in final_dead_no_self.values():
                packet += UUID.pack(uuid.UUID(player.uuid))

            self.downstream.send_packet(0x38, packet)

    @listen_server(0x3E, blocking=True)
    async def packet_teams(self: ProxhyPlugin, buff: Buffer):
        self.downstream.send_packet(0x3E, buff.getvalue())

        name = buff.unpack(String)
        mode = buff.unpack(Byte)
        if mode == 3 and TEAM_COLOR_NAME.match(name):
            player_count = buff.unpack(VarInt)
            for _ in range(player_count):
                username = buff.unpack(String)
                team_name = re.sub(r"\d+", "", name)
                player = self.gamestate.get_player_by_name_from_player_list(username)
                if player is None:
                    self.logger.warning(
                        "packet_teams: "
                        f"hypixel tried to add {username} "
                        "but they were not found in gamestate"
                    )
                    continue
                elif player.name in self.game_players:
                    continue

                player = GamePlayer(
                    username=username,
                    uuid=player.uuid,
                    team=TeamColor.from_name(team_name),
                    status=GamePlayerStatus.ALIVE,
                )
                self.game_players[username] = player
                self.player_stats_queue.put_nowait(player)

        self.keep_player_stats_updated()

    @listen_server(0x38, blocking=True)
    async def packet_player_list_item(self: ProxhyPlugin, buff: Buffer):
        action = buff.unpack(VarInt)
        num_players = buff.unpack(VarInt)

        if action == 0:
            out = Buffer()
            out.write(VarInt.pack(action))
            out.write(VarInt.pack(num_players))

            for _ in range(num_players):
                _uuid = buff.unpack(UUID)
                out.write(UUID.pack(_uuid))

                if action == 0:  # add player
                    name = buff.unpack(String)
                    out.write(String.pack(name))

                    num_properties = buff.unpack(VarInt)
                    out.write(VarInt.pack(num_properties))
                    for _ in range(num_properties):
                        prop_name = buff.unpack(String)
                        prop_value = buff.unpack(String)
                        has_signature = buff.unpack(Boolean)
                        out.write(String.pack(prop_name))
                        out.write(String.pack(prop_value))
                        out.write(Boolean.pack(has_signature))
                        if has_signature:
                            out.write(String.pack(buff.unpack(String)))

                    gamemode = buff.unpack(VarInt)
                    ping = buff.unpack(VarInt)
                    has_display_name = buff.unpack(Boolean)
                    out.write(VarInt.pack(gamemode))
                    out.write(VarInt.pack(ping))

                    if player := self.players_with_stats.get(name):
                        out.write(Boolean.pack(True))
                        out.write(Chat.pack(player.display_name))
                        if has_display_name:
                            buff.unpack(Chat)  # discard original
                    else:
                        out.write(Boolean.pack(has_display_name))
                        if has_display_name:
                            out.write(Chat.pack(buff.unpack(Chat)))
        else:
            out = buff

        self.downstream.send_packet(0x38, out.getvalue())

    async def _update_stats(self: ProxhyPlugin):
        await self.received_locraw.wait()

        if not self.in_bedwars_game():
            return

        await self.validate_api_key()

        while player := await self.player_stats_queue.get():
            while not self._api_key_valid:
                await asyncio.sleep(0.1)
            self.create_task(self._update_player_stats(player))

    async def _update_player_stats(self: ProxhyPlugin, player: GamePlayer):
        try:
            player_result: Player | Nick = await self.hypixel_client.player(
                player.username
            )
        except PlayerNotFound as err:  # assume nick
            # I don't actually know if we can assume this is a string
            # but I want the type checker to be friendly to me
            # later when I casefold it
            nick_username: str = err.player
            nick_uuid = self.gamestate.players[nick_username].uuid
            player_result = Nick(nick_username, nick_uuid)
        except (
            InvalidApiKey,
            RateLimitError,
            TimeoutError,
            KeyRequired,
            asyncio.TimeoutError,
            ApiError,
        ) as err:
            err_message: dict[type, TextComponent] = {
                InvalidApiKey: TextComponent("Invalid API Key!").color("red"),
                KeyRequired: TextComponent("No API Key provided!").color("red"),
                RateLimitError: TextComponent("Rate limit!").color("red"),
                TimeoutError: TextComponent(
                    f"Request timed out while fetching stats for {player.username!r}!"
                ).color("red"),
                asyncio.TimeoutError: TextComponent(
                    f"Request timed out for {player.username!r}!"
                ).color("red"),
                ApiError: TextComponent(
                    f"An API error occurred with the Hypixel API while fetching stats for {player.username!r}!"
                ).color("red"),
            }

            # if an error message hasn't already been sent in this game
            # game being hypixel sub-server, clears on packet_join_game
            if isinstance(err, (InvalidApiKey, KeyRequired)):
                self._api_key_valid = False
                if not self.game_error:
                    self.downstream.chat(err_message[type(player)])
                    self.game_error = err

            self.logger.debug(err_message)

            if not isinstance(err, (InvalidApiKey, KeyRequired)):
                self.downstream.chat(err_message[type(player)])

            self.player_stats_queue.put_nowait(player)

            return
        except Exception as err:
            if not self.game_error:
                self.game_error = err
                msg = f"An unknown error occurred while fetching stats for {player.username}: {player!r}"
                self.logger.debug(msg)
                self.downstream.chat(TextComponent(msg).color("red"))

            return

        if player.username != player_result.name:
            self.logger.debug(
                f"_update_player_stats: expected '{player.username}', got '{player_result.name}'; assuming nick"
            )
            # assume nick -- TODO: should we assume this?
            # no I am NOT chat gpt despite the em dash ):
            player_result = Nick(player.username, player.uuid)
            # i really hope this owrks because I am NOT testing ts
            # btw this diff is made by kavi but i am too lazy to
            # change hte commiter btw 👍🏻

        if isinstance(player_result, Nick):
            fdict = player_result
        else:
            fdict = format_player_dict(player_result, "bedwars")

        player.fplayer = fdict
        display_name = self._build_player_display_name(player)
        player.display_name = display_name

        if self.settings.bedwars.tablist.show_stats.get() == "ON":
            if player.status in {GamePlayerStatus.FINALED, GamePlayerStatus.RESPAWNING}:
                display_name = self._get_dead_display_name(player)
            self._send_tablist_update(str(player.uuid), display_name)

        await self.emit("statcheck:update", player)

    @subscribe("statcheck:update")
    async def _event_statcheck_update(self: ProxhyPlugin, _match, data: GamePlayer):
        if set(self.players_with_stats.keys()) == self.who_players:
            self.who_players_statted.set()

            if self.settings.bedwars.display_top_stats.get() != "OFF":
                if not self.stats_highlighted:
                    await self.stat_highlights()

    async def highlight_adjacent_teams(self: ProxhyPlugin) -> None:
        """Displays a title card with stats of adjacent team(s)."""

        await self.who_players_statted.wait()

        if self.game.map is None:
            self.logger.warning("highlight_adjacent_teams: could not determine map")
            return
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
            self.logger.warning(
                f"highlight_adjacent_teams: unexpected rush_direction {self.game.map.rush_direction!r}"
            )
            return

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
            self.logger.warning(
                f"highlight_adjacent_teams: unexpected display_top_stats value {self.settings.bedwars.display_top_stats.get()!r}"
            )
            return

        subtitle = None

        match len(first_players):
            case 0:  # team empty or disconnected
                title = empty_team_dialogue_first
            case 1:  # solos or doubles with 1 disconnect
                title = self.players_with_stats[first_players[0]].display_name
            case (
                2
            ):  # team of 2; calculate which one has better stats based on user pref
                fp1 = self.players_with_stats[first_players[0]].fplayer
                fp2 = self.players_with_stats[first_players[1]].fplayer

                better: dict[str, Any] | Nick
                worse: dict[str, Any] | Nick
                if isinstance(fp1, Nick):
                    better = fp1
                    worse = fp2
                elif isinstance(fp2, Nick):
                    better = fp2
                    worse = fp1
                else:
                    better, worse = sorted((fp1, fp2), key=key, reverse=True)

                if isinstance(better, Nick):
                    title = self.players_with_stats[better.name].display_name
                else:
                    title = self.players_with_stats[
                        str(better["raw_name"])
                    ].display_name

                if self.settings.bedwars.announce_first_rush.get() == "FIRST RUSH":
                    # if we aren't showing alt rush team stats, we can show both players from first rush
                    if isinstance(worse, Nick):
                        subtitle = self.players_with_stats[worse.name].display_name
                    else:
                        subtitle = self.players_with_stats[
                            str(worse["raw_name"])
                        ].display_name
            case _:
                self.logger.warning(
                    f"highlight_adjacent_teams: unexpected first rush team size {len(first_players):d}: {first_players}"
                )
                return

        if self.settings.bedwars.announce_first_rush.get() == "BOTH ADJACENT":
            match len(other_adjacent_players):
                case 0:
                    subtitle = empty_team_dialogue_alt
                case 1:
                    subtitle = self.players_with_stats[
                        other_adjacent_players[0]
                    ].display_name
                case 2:
                    fp1 = self.players_with_stats[other_adjacent_players[0]].fplayer
                    fp2 = self.players_with_stats[other_adjacent_players[1]].fplayer
                    better: dict[str, Any] | Nick
                    worse: dict[str, Any] | Nick
                    if isinstance(fp1, Nick):
                        better = fp1
                        worse = fp2
                    elif isinstance(fp2, Nick):
                        better = fp2
                        worse = fp1
                    else:
                        better, worse = sorted((fp1, fp2), key=key, reverse=True)

                    if isinstance(better, Nick):
                        subtitle = self.players_with_stats[better.name].display_name
                    else:
                        subtitle = self.players_with_stats[
                            str(better["raw_name"])
                        ].display_name
                case _:
                    self.logger.warning(
                        f"highlight_adjacent_teams: unexpected alt rush team size {len(other_adjacent_players):d}: {other_adjacent_players}"
                    )
                    return
        self.downstream.reset_title()
        self.downstream.set_title(title=title, subtitle=subtitle)
        # raise ValueError(
        #   f'Expected "FIRST RUSH", "BOTH ADJACENT", or "OFF" state for setting bedwars.announce_first_rush; got {self.settings.bedwars.announce_first_rush.state} instead.'
        # )
        self.adjacent_teams_highlighted = True

    def _get_own_team_info(self: ProxhyPlugin) -> TeamColor:
        """Get team name and color code for the current user."""
        sidebar_own_team = next(
            (team for team in self.gamestate.teams.values() if "YOU" in team.suffix),
            None,
        )
        if sidebar_own_team is None:
            raise ValueError(
                "Player is not on a team; cannot determine own team color."
            )

        match_ = re.search(r"§[a-f0-9](\w+)(?=§f:)", sidebar_own_team.prefix)
        if match_:
            team_name = match_.group(1)
            return TeamColor.from_name(team_name)
        else:
            raise ValueError(
                f"Could not determine own team color; regex did not match prefix {sidebar_own_team.prefix!r}"
            )

    def get_adjacent_teams(self: ProxhyPlugin) -> tuple[str, str]:
        """Get the (side_rush, alt_rush) teams for the current player.

        Returns:
            Tuple of (side_rush_color, alt_rush_color)

        Raises:
            ValueError: If player is not on a team
        """
        team = self._get_own_team_info()
        # TODO will raise ValueError if player is not on a team; handle!

        side_rush = RUSH_MAPPINGS["default_mappings"]["side_rushes"][team.name.lower()]
        alt_rush = RUSH_MAPPINGS["default_mappings"]["alt_rushes"][team.name.lower()]

        return (side_rush, alt_rush)

    def get_players_on_team(self: ProxhyPlugin, color: str) -> list[str]:
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

    async def stat_highlights(self: ProxhyPlugin) -> None:
        """Display top 3 enemy players and nicked players."""
        if self.settings.bedwars.display_top_stats.get() == "OFF":
            return
        if self.game.mode == "bedwars_two_one_duels":
            return
        if not self.players_with_stats:
            return  # no stats

        try:
            own_team_color = self._get_own_team_info().name
        except ValueError as e:
            self.logger.warning(
                f"stat_highlights: could not determine own team color: {e}"
            )
            return

        enemy_players = []
        enemy_nicks = []

        # Process each player
        for player_name, player_data in self.players_with_stats.items():
            display_name = player_data.display_name
            # Skip the user's own nickname
            if player_name == self.username:
                continue

            # Get player's team
            player_team = player_data.team

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
            fdict = player_data.fplayer
            if isinstance(fdict, Nick):
                continue

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
                result += f"§f§l{i}§r: {player['star_formatted']} {player['team_color']} {player['name']}; FKDR: {player['fkdr_formatted']}"
        elif not enemy_nicks:
            result = "No stats found!"

        self.downstream.chat(
            TextComponent("Top stats:\n\n")
            .color("gold")
            .bold()
            .append(result)
            .append("\n")
        )
        self.stats_highlighted = True

    def keep_player_stats_updated(self: ProxhyPlugin) -> None:
        if self.settings.bedwars.tablist.show_stats.get() != "ON":
            return

        living_players = [
            (player.uuid, player.display_name)
            for player in self.game_players.values()
            if player.status == GamePlayerStatus.ALIVE
            and player.display_name is not None
        ]

        self._send_bulk_tablist_update(living_players)

    @subscribe(r"chat:server:.* has joined .*!")
    async def _statcheck_event_chat_server_player_joined(
        self: ProxhyPlugin, _match, buff: Buffer
    ):
        self.downstream.send_packet(0x02, buff.getvalue())
        if self.settings.bedwars.api_key_reminder.get() == "ON":
            message = buff.unpack(Chat)
            m = JOIN_RE.match(message)
            if m and m.group("ign").casefold() == self.username.casefold():
                await self.validate_api_key()

                if self._api_key_valid is False:  # only warn if explicitly invalid
                    self.downstream.chat(
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
    async def _statcheck_event_chat_server_who(
        self: ProxhyPlugin, _match, buff: Buffer
    ):
        message = buff.unpack(Chat)

        if not self.received_who.is_set():
            self.received_who.set()
        else:
            self.downstream.send_packet(0x02, buff.getvalue())

        self.who_players.update(message.removeprefix("ONLINE: ").split(", "))

    def get_player_to_uuid_mapping(self: ProxhyPlugin) -> dict[str, str]:
        """Get a mapping of player names to UUIDs."""
        return {player.username: player.uuid for player in self.game_players.values()}

    @subscribe(
        "chat:server:(You will respawn in 10 seconds!|Your bed was destroyed so you are a spectator!)"
    )
    async def _statcheck_event_chat_server_bedwars_rejoin(
        self: ProxhyPlugin, _match, buff: Buffer
    ):
        self.downstream.send_packet(0x02, buff.getvalue())
        message = buff.unpack(Chat)

        status = GamePlayerStatus.RESPAWNING
        if "spectator" in message:
            status = GamePlayerStatus.FINALED

        # refresh stats
        # TODO: does not work with nicks
        self_team = self._get_own_team_info()
        self_game_player = GamePlayer(
            self.username, self.uuid, self_team, status=status
        )
        self.logger.debug("statcheck_event_chat_server_bedwars_rejoin: putting self")
        self.player_stats_queue.put_nowait(self_game_player)

        self.upstream.send_packet(0x01, String.pack("/who"))
        self.received_who.clear()

        self.game.started = True

        if status == GamePlayerStatus.FINALED:
            self._update_dead_players_in_tablist()

    def in_bedwars_game(self: ProxhyPlugin):
        return self.game.gametype == "bedwars" and self.game.mode

    @subscribe(f"chat:server:({'|'.join(GAME_START_MESSAGES)})")
    async def _statcheck_event_chat_server_game_start(
        self: ProxhyPlugin, _match, buff: Buffer
    ):
        if self.game.gametype != "bedwars" or self.stats_highlighted:
            return self.downstream.send_packet(0x02, buff.getvalue())

        message = buff.unpack(Chat)
        is_duels = self.game.mode == "bedwars_two_one_duels"
        suppress = (
            self.settings.bedwars.display_top_stats.get() != "OFF" and not is_duels
        )
        if message in {msg_set[-2] for msg_set in GAME_START_MESSAGE_SETS}:  # runs once
            self.upstream.send_packet(0x01, String.pack("/who"))
            self.received_who.clear()
            self.game.started = True

            if suppress:
                if (
                    self.settings.bedwars.announce_first_rush.get() != "OFF"
                    and self.game.mode.lower()
                    in {"bedwars_eight_one", "bedwars_eight_two"}
                    and not self.adjacent_teams_highlighted
                ):
                    self.create_task(self.highlight_adjacent_teams())

                self.downstream.chat(
                    TextComponent("Fetching top stats...").color("gold").bold()
                )

        if not suppress:
            self.downstream.send_packet(0x02, buff.getvalue())

    @command("resetkey")
    async def _command_reset_key(self: ProxhyPlugin):
        """Reset your Hypixel API key."""
        self.hypixel_client.remove_key(self.hypixel_api_key)
        self.hypixel_api_key = ""
        return TextComponent("Reset your Hypixel API key!").color("green")

    @command("key", "apikey")
    async def _command_key(self: ProxhyPlugin, key: str = ""):
        """Set or view your Hypixel API key."""

        if not key:
            if self.hypixel_api_key:
                return (
                    TextComponent("Hypixel API Key:")
                    .color("yellow")
                    .appends(
                        TextComponent("[Click to Reveal]")
                        .color("green")
                        .click_event("suggest_command", self.hypixel_api_key)
                    )
                    .appends(
                        TextComponent("[Click to Reset]")
                        .color("red")
                        .click_event("run_command", "/resetkey")
                    )
                )
            else:
                raise CommandException("You have not set your Hypixel API key yet!")

        try:
            self.hypixel_client.remove_key(self.hypixel_api_key)
            self.hypixel_client.add_key(key)
            # hypixel.Client.validate_keys does not work anymore
            await self.validate_api_key()
        except (MalformedApiKey, InvalidApiKey):
            self.hypixel_client.remove_key(key)
            self.hypixel_client.add_key(self.hypixel_api_key)
            raise CommandException("Invalid API Key!")

        self.hypixel_api_key = key
        self._api_key_valid = True

        self.game_error = None
        self.downstream.chat(TextComponent("Updated API Key!").color("green"))

    def match_kill_message(self: ProxhyPlugin, message: str) -> Optional[re.Match]:
        """Match a kill message against known patterns.

        Returns:
            Match object if message matches a kill pattern, None otherwise
        """
        for pattern in KILL_MSGS:
            match = re.match(pattern, message)
            if match:
                return match  # Only 3 groups: victim, killer, final_kill
        return None

    async def respawn_timer(
        self: ProxhyPlugin, player: GamePlayer, reconnect: bool = False
    ) -> None:
        """Display a countdown timer in the tab list for respawning players."""
        if not self.settings.bedwars.tablist.show_respawn_timer.get() == "ON":
            return

        # remove player from tablist
        # hypixel already does this for other players
        # but not for the user themselves
        self.downstream.send_packet(
            0x38,
            VarInt.pack(4),
            VarInt.pack(1),
            UUID.pack(uuid.UUID(player.uuid)),
        )

        # spawn player for timer
        self.downstream.send_packet(
            0x38,
            VarInt.pack(0),
            VarInt.pack(1),
            UUID.pack(uuid.UUID(player.offline_uuid)),
            String.pack(player.username),
            VarInt.pack(0),  # 0 properties
            VarInt.pack(3),  # gamemode
            VarInt.pack(0),  # ping
            Boolean.pack(True),
            Chat.pack(self._get_dead_display_name(player)),
        )

        timer_duration = 10 if reconnect else 5

        for s in range(timer_duration, 0, -1):
            display_name = f"§6§l{s}s {self._get_dead_display_name(player)}"
            self._send_tablist_update(player.offline_uuid, display_name)
            await asyncio.sleep(1)

        player.status = GamePlayerStatus.ALIVE

        self.downstream.send_packet(
            0x38,
            VarInt.pack(4),
            VarInt.pack(1),
            UUID.pack(uuid.UUID(player.offline_uuid)),
        )

    @subscribe(r"chat:server:(.+?) reconnected\.$")
    async def _statcheck_event_chat_server_player_recon(
        self: ProxhyPlugin, _match, buff: Buffer
    ):
        self.downstream.send_packet(0x02, buff.getvalue())

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

        self.create_task(self.respawn_timer(player, reconnect=True))

    @subscribe(f"chat:server:{'|'.join(KILL_MSGS)}")
    async def _statcheck_event_chat_server_kill_msg(
        self: ProxhyPlugin, _match, buff: Buffer
    ):
        if not self.in_bedwars_game():
            return self.downstream.send_packet(0x02, buff.getvalue())

        self.downstream.send_packet(0x02, buff.getvalue())
        message = buff.unpack(Chat)

        if message.startswith("BED DESTRUCTION >"):
            # some kill messages match bed destroy messages
            return

        m = self.match_kill_message(message)
        if not m:
            return
        killed = self.game_players[m.group(1)]
        fk = message.endswith("FINAL KILL!")

        if message.endswith("disconnected."):
            return  # TODO: what to do here?

        if fk:
            killed.status = GamePlayerStatus.FINALED
            if self.settings.bedwars.tablist.show_eliminated_players.get() == "ON":
                self.downstream.send_packet(
                    0x38,
                    VarInt.pack(0),  # spawn player
                    VarInt.pack(1),  # number of players
                    UUID.pack(uuid.UUID(killed.offline_uuid)),
                    String.pack(killed.username),
                    VarInt.pack(0),
                    VarInt.pack(3),  # gamemode; spectator
                    VarInt.pack(0),  # ping
                    Boolean.pack(True),
                    Chat.pack(self._get_dead_display_name(killed)),
                )
        else:
            self.create_task(self.respawn_timer(killed))
