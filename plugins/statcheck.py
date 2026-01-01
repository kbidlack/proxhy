import asyncio
import datetime
import json
import os
import re
import uuid
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Callable, Optional, TypedDict

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
from core.plugin import Plugin
from protocol.datatypes import (
    UUID,
    Boolean,
    Buffer,
    Chat,
    String,
    TextComponent,
    VarInt,
)
from proxhy.aliases import Gamemode
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.formatting import FormattedPlayer, format_bw_fkdr, format_bw_wlr
from proxhy.mcmodels import Game, Nick, Team, Teams
from proxhy.settings import ProxhySettings

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

game_start_msgs = [  # block all the game start messages
    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    "                                  Bed Wars",
    "     Protect your bed and destroy the enemy beds.",
    "      Upgrade yourself and your team by collecting",
    "    Iron, Gold, Emerald and Diamond from generators",
    "                  to access powerful upgrades.",
    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
]

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
    fplayer: FormattedPlayer | Nick


class TeamColor(TypedDict):
    letter: str
    code: str
    name: str


def minecraft_uuid_v2():
    u: int = uuid.uuid4().int  # pyright:ignore[reportAssignmentType]
    # Set version bits (4 bits starting at bit 76) to 2
    u &= ~(0xF << 76)  # clear version bits
    u |= 0x2 << 76  # set version=2
    return uuid.UUID(int=u)


class StatCheckPlugin(Plugin):
    teams: Teams
    game: Game
    settings: ProxhySettings
    received_who: asyncio.Event
    username: str
    received_locraw: asyncio.Event

    def _init_statcheck(self):
        self.players_with_stats: dict[str, PlayersWithStats] = {}
        self.nick_team_colors: dict[str, str] = {}  # Nicked player team colors
        self.players_without_stats: set[str] = set()  # players from /who

        self.final_dead: dict[str, str] = {}  # name: uuid
        self.dead: dict[str, str] = {}  # name: uuid

        self._cached_players: dict = {}
        # players from packet_player_list_item
        self.players: dict[str, str] = {}
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

    def _build_player_display_name(
        self, player_name: str, fplayer: FormattedPlayer | Nick
    ) -> str:
        """Build the display name for a player based on settings and stats.

        Args:
            player_name: The player's name
            fplayer: The formatted player object or Nick object

        Returns:
            The formatted display name string with color codes
        """

        # Get team color
        try:
            color = self.get_team_color(player_name)
        except ValueError:
            color = {"code": "", "letter": "", "name": ""}

        if isinstance(fplayer, Nick):
            return f"{color['code']}§l{color['letter']}§r §5[NICK] {player_name}"

        # Determine which FKDR to display
        if (
            self.settings.bedwars.tablist.is_mode_specific.get() == "ON"
            and self.game.mode
        ):
            mode_key = f"{self.game.mode[8:].lower()}_stats"
            fkdr = fplayer.bedwars.__getattribute__(mode_key)["fkdr"]
        else:
            fkdr = fplayer.bedwars.fkdr

        # Determine which name to display
        show_rankname = self.settings.bedwars.tablist.show_rankname.get()
        name = fplayer.rankname if show_rankname == "ON" else fplayer.raw_name

        # Build the display name
        display_name = " ".join(
            (
                f"{fplayer.bedwars.level}{color['code']}",
                name,
                f" §7| {fkdr}",
            )
        )

        # Add team prefix
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
    async def bedwars_tablist_show_stats_callback(self, data: list):
        # data = [old_state, new_state]
        if data == ["OFF", "ON"]:
            self.received_who.clear()
            # self.server.chat("/who")
            await self._update_stats()
        elif data == ["ON", "OFF"]:
            await self._reset_stats()

        self._update_dead_players_in_tablist()

    @subscribe("setting:bedwars.tablist.is_mode_specific")
    async def bedwars_tablist_is_mode_specific_callback(self, data: list) -> None:
        """Callback when is_mode_specific setting changes - rebuild display names."""
        if self.settings.bedwars.tablist.show_stats.get() == "ON":
            # Recalculate display names with new mode-specific setting
            for player, player_data in self.players_with_stats.items():
                fplayer = player_data["fplayer"]
                if isinstance(fplayer, FormattedPlayer):
                    # Rebuild display name with new setting
                    display_name = self._build_player_display_name(player, fplayer)
                    self.players_with_stats[player] = {
                        "uuid": player_data["uuid"],
                        "display_name": display_name,
                        "fplayer": fplayer,
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
    async def bedwars_tablist_show_rankname_callback(self, data: list) -> None:
        """Callback when show_rankname setting changes - rebuild display names."""
        for player, player_data in self.players_with_stats.items():
            fplayer = player_data["fplayer"]
            if isinstance(fplayer, FormattedPlayer):
                # Rebuild display name with new setting
                display_name = self._build_player_display_name(player, fplayer)
                self.players_with_stats[player] = {
                    "uuid": player_data["uuid"],
                    "display_name": display_name,
                    "fplayer": fplayer,
                }
        self.keep_player_stats_updated()
        self._update_dead_players_in_tablist()

    @subscribe("setting:bedwars.tablist.show_eliminated_players")
    async def bedwars_tablist_show_eliminated_players_callback(
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

    @subscribe("update_teams")
    async def on_update_teams(self, _):
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

    @subscribe("login_success")
    async def log_stats_on_login(self, _):
        self.hypixel_client = hypixel.Client(self.hypixel_api_key)
        asyncio.create_task(self.log_bedwars_stats("login"))

    @subscribe("close")
    async def statcheck_on_close(self, _):
        try:
            if self.hypixel_client:
                await self.log_bedwars_stats("logout")
                await self.hypixel_client.close()
        except AttributeError:
            pass  # TODO: log

    # Helper methods for _sc_internal stat calculation

    def _find_closest_stat_log(
        self, ign: str, window: float
    ) -> tuple[dict, datetime.datetime]:
        """Find the closest stat log entry for a player within the time window.

        Args:
            ign: Player's username
            window: Time window in days

        Returns:
            Tuple of (old_stats_dict, chosen_datetime)

        Raises:
            CommandException: If no suitable log entry is found
        """
        if not os.path.exists(self.log_path):
            raise CommandException(
                "No log file found; recent stats unavailable. For lifetime stats, use /sc <player>."
            )

        now = datetime.datetime.now()
        target_time = now - datetime.timedelta(days=window)

        # Read and parse the stat log file
        entries = []
        with open(self.log_path, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get(
                        "player", ""
                    ).casefold() == ign.casefold() and entry.get("bedwars"):
                        entry["dt"] = datetime.datetime.fromisoformat(
                            entry["timestamp"]
                        )
                        entries.append(entry)
                except Exception:
                    continue

        if not entries:
            raise CommandException("No logged stats available for this player.")

        # Filter entries: they must be dated at most 3x the given window
        valid_entries = [
            entry
            for entry in entries
            if now - entry["dt"] <= datetime.timedelta(days=window * 3)
        ]
        if not valid_entries:
            raise CommandException("Insufficient logged data: logged stats too old.")

        # Choose the entry whose timestamp is closest to the target time
        chosen_entry = min(
            valid_entries,
            key=lambda entry: abs((entry["dt"] - target_time).total_seconds()),
        )

        return chosen_entry["bedwars"], chosen_entry["dt"]

    def _calculate_stat_deltas(
        self, current_stats: dict, old_stats: dict, required_keys: list[str]
    ) -> dict:
        """Calculate the difference between current and old stats.

        Args:
            current_stats: Current player stats
            old_stats: Old player stats from log
            required_keys: List of stat keys to calculate deltas for

        Returns:
            Dictionary mapping stat keys to their deltas

        Raises:
            CommandException: If stats are inconsistent (current < old)
        """
        diffs = {}
        for key in required_keys:
            try:
                current_val = float(current_stats.get(key, 0))
                old_val = float(old_stats.get(key, 0))
                diff = current_val - old_val
                if diff < 0:
                    raise CommandException(
                        "Logged cumulative values are inconsistent (current value lower than logged value)."
                    )
                diffs[key] = diff
            except Exception:
                diffs[key] = 0
        return diffs

    def _calculate_ratios(
        self, kills: float, deaths: float, wins: float, losses: float
    ) -> tuple[float, float]:
        """Calculate FKDR and WLR from stat values.

        Args:
            kills: Final kills or kills
            deaths: Final deaths or deaths
            wins: Wins
            losses: Losses

        Returns:
            Tuple of (fkdr, wlr) rounded to 2 decimal places
        """
        try:
            fkdr = kills / deaths if deaths > 0 else float(kills)
        except Exception:
            fkdr = 0.0

        try:
            wlr = wins / losses if losses > 0 else float(wins)
        except Exception:
            wlr = 0.0

        return round(fkdr, 2), round(wlr, 2)

    def _format_date_with_ordinal(self, dt: datetime.datetime) -> str:
        """Format a datetime as 'Month Dayth, Year (H:MM AM/PM)'.

        Args:
            dt: Datetime to format

        Returns:
            Formatted string like 'January 1st, 2024 (8:42 PM)'
        """

        def ordinal(n: int) -> str:
            if 11 <= (n % 100) <= 13:
                return f"{n}th"
            last_digit = n % 10
            if last_digit == 1:
                return f"{n}st"
            elif last_digit == 2:
                return f"{n}nd"
            elif last_digit == 3:
                return f"{n}rd"
            else:
                return f"{n}th"

        formatted_date = f"{dt.strftime('%B')} {ordinal(dt.day)}, {dt.strftime('%Y')}"
        formatted_time = dt.strftime("%I:%M %p").lstrip("0")
        return f"{formatted_date} ({formatted_time})"

    def _calculate_mode_stats(
        self,
        mode: str,
        current_stats: dict,
        old_stats: dict,
        non_dream_mapping: dict,
        dream_mapping: dict,
    ) -> tuple[float, float]:
        """Calculate FKDR and WLR for a specific game mode.

        Args:
            mode: Mode name (e.g., "Solo", "Doubles", "Rush")
            current_stats: Current player stats
            old_stats: Old player stats from log
            non_dream_mapping: Mapping for standard modes
            dream_mapping: Mapping for dream modes

        Returns:
            Tuple of (fkdr, wlr) for the mode
        """
        if mode in non_dream_mapping:
            prefix = non_dream_mapping[mode]
            fk_key = f"{prefix}_final_kills_bedwars"
            fd_key = f"{prefix}_final_deaths_bedwars"
            wins_key = f"{prefix}_wins_bedwars"
            losses_key = f"{prefix}_losses_bedwars"

            diff_fk = float(current_stats.get(fk_key, 0)) - float(
                old_stats.get(fk_key, 0)
            )
            diff_fd = float(current_stats.get(fd_key, 0)) - float(
                old_stats.get(fd_key, 0)
            )
            diff_wins = float(current_stats.get(wins_key, 0)) - float(
                old_stats.get(wins_key, 0)
            )
            diff_losses = float(current_stats.get(losses_key, 0)) - float(
                old_stats.get(losses_key, 0)
            )
        else:
            # For dream modes, aggregate over any key that includes the dream substring
            dream_sub = dream_mapping[mode]
            diff_fk = sum(
                float(current_stats.get(key, 0)) - float(old_stats.get(key, 0))
                for key in current_stats
                if key.endswith("_final_kills_bedwars") and f"_{dream_sub}_" in key
            )
            diff_fd = sum(
                float(current_stats.get(key, 0)) - float(old_stats.get(key, 0))
                for key in current_stats
                if key.endswith("_final_deaths_bedwars") and f"_{dream_sub}_" in key
            )
            diff_wins = sum(
                float(current_stats.get(key, 0)) - float(old_stats.get(key, 0))
                for key in current_stats
                if key.endswith("_wins_bedwars") and f"_{dream_sub}_" in key
            )
            diff_losses = sum(
                float(current_stats.get(key, 0)) - float(old_stats.get(key, 0))
                for key in current_stats
                if key.endswith("_losses_bedwars") and f"_{dream_sub}_" in key
            )

        return self._calculate_ratios(diff_fk, diff_fd, diff_wins, diff_losses)

    async def _sc_internal(
        self,
        ign: str = "",
        mode: str = "bedwars",
        window: Optional[float] = -1.0,
        *stats,
        display_abridged=True,
    ):
        """
        Calculates weekly FKDR and WLR by comparing the current cumulative Bedwars stats with the estimated
        cumulative values from approximately one week ago. It then overrides the player's live FKDR and WLR attributes,
        uses FormattedPlayer.format_stats to generate the main text, and sends a JSON chat message with a hover event.

        The chosen log entry is the one whose timestamp is closest to one week ago,
        provided its age is between 0 and 30 days old.

        Also hovertext supports per-mode weekly stats for all bw modes with updated data
        Modes that represent dreams variants (Ultimate, Lucky, Castle, Swap, Voidless) aggregate any split stats.

        """

        if not (isinstance(window, float) or window is None):
            try:
                window = float(window)
            except ValueError:
                raise CommandException(
                    f"Received type {type(window)} for time window; could not convert to float."
                )

        if window == -1.0:
            window = None

        # Use player's name and assume gamemode is bedwars.
        ign = ign or self.username

        if (gamemode := Gamemode(mode)) != "bedwars":
            raise CommandException("Currently only Bedwars stats are supported!")

        # verify stats
        if not stats:
            if gamemode == "bedwars":
                if window:
                    stats = ("FKDR", "WLR")
                else:
                    stats = ("Finals", "FKDR", "Wins", "WLR")
            elif gamemode == "skywars":
                stats = ("Kills", "KDR", "Wins", "WLR")

        # Retrieve current player stats from the API.
        try:
            current_player = await self.hypixel_client.player(ign)
            current_stats = current_player._data.get("stats", {}).get("Bedwars", {})
        except Exception as e:
            raise CommandException(f"Failed to fetch current stats: {e}")

        # Calculate time-based stats if window is specified
        if window:
            # Check that necessary cumulative keys exist
            required_keys = [
                "final_kills_bedwars",
                "final_deaths_bedwars",
                "wins_bedwars",
                "losses_bedwars",
            ]
            if not all(key in current_stats for key in required_keys):
                raise CommandException(
                    "Current stats are missing required data for stat calculation!"
                )

            # Find the closest stat log entry within the time window
            old_stats, chosen_date = self._find_closest_stat_log(ign, window)

            # Calculate stat deltas
            diffs = self._calculate_stat_deltas(current_stats, old_stats, required_keys)

            # Calculate weekly FKDR and WLR
            weekly_fkdr, weekly_wlr = self._calculate_ratios(
                diffs["final_kills_bedwars"],
                diffs["final_deaths_bedwars"],
                diffs["wins_bedwars"],
                diffs["losses_bedwars"],
            )

            # Override the live FKDR and WLR attributes on the player object
            current_player.bedwars.fkdr = weekly_fkdr
            current_player.bedwars.wlr = weekly_wlr

            # Re-initialize FormattedPlayer with the overwritten attributes
            fplayer = FormattedPlayer(current_player)

            # Build hover text header
            formatted_date = self._format_date_with_ordinal(chosen_date)
            hover_text = f"Recent stats for {fplayer.rankname}\nCalculated using data from {formatted_date}\n"
        else:
            # Lifetime stats
            fplayer = FormattedPlayer(current_player)
            hover_text = f"Lifetime Stats for {fplayer.rankname}§f:\n"
            old_stats = {}

        # Build per-mode stats for hover text
        non_dream_mapping = {
            "Solo": "eight_one",
            "Doubles": "eight_two",
            "3v3v3v3": "four_three",
            "4v4v4v4": "four_four",
            "4v4": "two_four",
        }
        dream_mapping = {
            "Rush": "rush",
            "Ultimate": "ultimate",
            "Lucky": "lucky",
            "Castle": "castle",
            "Swap": "swap",
            "Voidless": "voidless",
        }

        # List of modes in the order to appear
        modes = ["Solo", "Doubles", "3v3v3v3", "4v4v4v4"]
        if not display_abridged:
            modes.extend(
                ["4v4", "Rush", "Ultimate", "Lucky", "Castle", "Swap", "Voidless"]
            )

        mode_lines = []
        dreams_linebreak_added = False

        for mode in modes:
            # Add linebreak before dream modes (if showing all modes)
            if (
                mode in dream_mapping
                and not dreams_linebreak_added
                and not display_abridged
            ):
                mode_lines.append("\n")
                dreams_linebreak_added = True

            # Calculate mode-specific stats using helper
            mode_fkdr, mode_wlr = self._calculate_mode_stats(
                mode, current_stats, old_stats, non_dream_mapping, dream_mapping
            )

            # Format with color codes
            formatted_mode_fkdr = format_bw_fkdr(mode_fkdr)
            formatted_mode_wlr = format_bw_wlr(mode_wlr)

            mode_lines.append(
                f"\n§c§l[{mode.upper()}]  §r §fFKDR:§r {formatted_mode_fkdr} §fWLR:§r {formatted_mode_wlr}"
            )

        if mode_lines:
            hover_text += "".join(mode_lines)
        if display_abridged:
            hover_text += "\n\n§7§oTo see all modes, use §l/scfull§r§7§o."

        # Format the hover text and send the chat message
        return fplayer.format_stats(gamemode, *stats).hover_text(hover_text)

    @command("sc")
    async def statcheck(
        self, ign: str = "", mode: str = "bedwars", window: float = -1.0, *stats: str
    ):
        return await self._sc_internal(ign, mode, window, *stats)

    @command("scw")
    async def scweekly(self, ign: str = "", mode: str = "bedwars", *stats: str):
        return await self._sc_internal(ign, mode, 7.0, *stats)

    @command("scfull")
    async def statcheckfull(
        self, ign: str = "", mode: str = "bedwars", window: float = -1.0, *stats
    ):
        return await self._sc_internal(ign, mode, window, *stats, display_abridged=True)

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
                (team for team in self.teams if "YOU" in team.suffix), None
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
                    expected_name, player_result = await result
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
                        fplayer = FormattedPlayer(player)
                    else:  # if is a nicked player
                        # get team color for nicked player
                        for team in self.teams:
                            if player.name in team.players:
                                self.nick_team_colors.update({player.name: team.prefix})
                                break
                        fplayer = player

                    # Build display name using helper method
                    display_name = self._build_player_display_name(player.name, fplayer)

                    self.players_with_stats[player.name] = {
                        "uuid": player.uuid,
                        "display_name": display_name,
                        "fplayer": fplayer,
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
        key: Callable[[FormattedPlayer], float]
        if self.settings.bedwars.display_top_stats.get() in {"OFF", "INDEX"}:
            key = lambda fp: fp.bedwars.raw_fkdr**2 * fp.bedwars.raw_level  # noqa: E731
        elif self.settings.bedwars.display_top_stats.get() == "STAR":
            key = lambda fp: fp.bedwars.raw_level  # noqa: E731
        elif self.settings.bedwars.display_top_stats.get() == "FKDR":
            key = lambda fp: fp.bedwars.raw_fkdr  # noqa: E731
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

                if isinstance(better, FormattedPlayer):
                    title = self.players_with_stats[better.raw_name]["display_name"]
                else:
                    title = self.players_with_stats[better.name]["display_name"]

                if self.settings.bedwars.announce_first_rush.get() == "FIRST RUSH":
                    # if we aren't showing alt rush team stats, we can show both players from first rush
                    if isinstance(worse, FormattedPlayer):
                        subtitle = self.players_with_stats[worse.raw_name][
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

                    if isinstance(better, FormattedPlayer):
                        subtitle = self.players_with_stats[better.raw_name][
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
        for team in self.teams:
            # team names like 'Green8', 'Green9' -> strip digits to get color
            base_color = re.sub(r"\d", "", team.name).lower()
            if base_color == target:
                players.update(team.players)
        return list(players)

    async def log_bedwars_stats(self, event: str) -> None:
        """Log Bedwars stats to file if they've changed since the last log entry.

        Args:
            event: Event type ('login' or 'logout')
        """
        try:
            # Fetch the latest player data via the API.
            player = await self.hypixel_client.player(self.username)
            # Extract the Bedwars statistics.
            bedwars_stats = player._data.get("stats", {}).get("Bedwars", {})
        except Exception:
            # print(f"Failed to log stats on {event}: {e}") # TODO: log this
            return

        # Create the new log entry.
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "event": event,
            "player": self.username,
            "bedwars": bedwars_stats,
        }

        # Check if the most recent log entry is identical in its 'bedwars' data.
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r") as f:
                    lines = f.readlines()
                if lines:
                    last_line = lines[-1].strip()
                    last_entry = json.loads(last_line)
                    # If the bedwars stats haven't changed, skip logging.
                    if last_entry.get("bedwars") == bedwars_stats:
                        return
            except Exception:
                # print(f"Error checking last log entry: {e}")
                pass  # TODO: log this

        # Append the new log entry as a JSON line.
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            # print(f"Error writing stat log: {e}")
            pass  # TODO: log this

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
            if player_name in self._cached_players:
                player = self._cached_players[player_name]
                fplayer = FormattedPlayer(player)

                # Calculate ranking value
                if self.settings.bedwars.tablist.is_mode_specific.get() == "ON":
                    fkdr = fplayer.bedwars.__getattribute__(
                        f"raw_{self.game.mode[8:].lower()}_stats"
                    )["fkdr"]
                    f_fkdr = fplayer.bedwars.__getattribute__(
                        f"{self.game.mode[8:].lower()}_stats"
                    )["fkdr"]
                else:
                    fkdr = fplayer.bedwars.raw_fkdr
                    f_fkdr = fplayer.bedwars.fkdr

                fkdr = int(fplayer.bedwars.raw_fkdr)
                stars = int(fplayer.bedwars.raw_level)

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
                        "star_formatted": fplayer.bedwars.level,
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
            team for team in self.teams if re.match("§.§l[A-Z] §r§.", team.prefix)
        ]
        return next(
            (team for team in real_player_teams if user in team.players),
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
    async def on_queue(self, buff: Buffer):
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
    async def on_chat_who(self, buff: Buffer):
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
    async def on_chat_user_rejoin(self, buff: Buffer):
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

    @subscribe(f"chat:server:({'|'.join(game_start_msgs)})")
    async def on_chat_game_start(self, buff: Buffer):
        if self.game.gametype != "bedwars" or self.stats_highlighted:
            return self.client.send_packet(0x02, buff.getvalue())

        message = buff.unpack(Chat)

        if self.settings.bedwars.display_top_stats.get() == "OFF":
            self.client.send_packet(0x02, buff.getvalue())

        if message == game_start_msgs[-2]:  # runs once
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

    @command()
    async def key(self, key):
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

        self.hypixel_api_key = key
        self.hypixel_client = hypixel.Client(key)
        # Mark as valid immediately (already tested)
        self._api_key_valid = True
        self._api_key_validated_at = asyncio.get_event_loop().time()

        api_key_msg = TextComponent("Updated API Key!").color("green")
        self.game_error = None
        self.client.chat(api_key_msg)

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
    async def on_player_recon(self, buff: Buffer):
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
    async def on_chat_kill_message(self, buff: Buffer):
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
