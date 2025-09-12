import asyncio
import datetime
import json
import os
import re
import uuid
from pathlib import Path
from typing import Callable, Optional

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
from plugins.command import command
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
from proxhy.errors import CommandException
from proxhy.formatting import FormattedPlayer, format_bw_fkdr, format_bw_wlr
from proxhy.mcmodels import Game, Nick, Team, Teams
from proxhy.settings import ProxhySettings

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
with open(ASSETS_DIR / "bedwars_maps.json", "r", encoding="utf-8") as f:
    BW_MAPS: dict = json.load(f)
f.close()
with open(ASSETS_DIR / "rush_mappings.json", "r", encoding="utf-8") as f:
    RUSH_MAPPINGS = json.load(f)
f.close()

game_start_msgs = [  # block all the game start messages
    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    "                                  Bed Wars",
    "     Protect your bed and destroy the enemy beds.",
    "      Upgrade yourself and your team by collecting",
    "    Iron, Gold, Emerald and Diamond from generators",
    "                  to access powerful upgrades.",
    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
]

COLOR_CODE_RE = re.compile(r"§.")
JOIN_RE = re.compile(
    r"^(?:\[[A-Za-z0-9+]+\]\s*)?"  # optional rank tag like [MVP++]
    r"(?P<ign>[A-Za-z0-9_]{3,16}) has joined (?P<context>.+)!$"
)
COLOR_CODE = re.compile(r"(§[0-9a-fk-or])", re.IGNORECASE)


class StatCheckPlugin(Plugin):
    teams: Teams
    game: Game
    settings: ProxhySettings
    received_who: asyncio.Event
    username: str
    received_locraw: asyncio.Event

    def _init_statcheck(self):
        self.players_with_stats: dict[str, tuple[str, str, FormattedPlayer | Nick]] = {}
        self.nick_team_colors: dict[str, str] = {}  # Nicked player team colors
        self.players_without_stats: set[str] = set()  # players from /who
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
        self._api_key_ttl = 300  # seconds

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

    async def validate_api_key(self, force=False) -> bool:
        # what the hell is this LMAO
        now = asyncio.get_event_loop().time()
        if (
            not force
            and self._api_key_valid is not None
            and self._api_key_validated_at
            and now - self._api_key_validated_at < self._api_key_ttl
        ):
            return self._api_key_valid
        try:
            client = hypixel.Client(self.hypixel_api_key)
            await client.player("gamerboy80")
        except Exception:
            self._api_key_valid = False
        else:
            self._api_key_valid = True
        finally:
            try:
                await client.close()  # type:ignore
            except Exception:
                pass
        self._api_key_validated_at = now
        return self._api_key_valid

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, _):
        # flush player lists
        self.players.clear()
        self.players_with_stats.clear()
        self._cached_players.clear()

        self.received_player_stats.clear()
        self.game_error = None
        self.stats_highlighted = False
        self.adjacent_teams_highlighted = False

    @subscribe("update_teams")
    async def statcheck_event_update_teams(self, _):
        # statcheck
        self.keep_player_stats_updated()

    @subscribe("setting:bedwars.tablist.show_stats")
    async def bedwars_tablist_show_stats_callback(self, data: list):
        # data = [old_state, new_state]
        if data == ["OFF", "ON"]:
            self.received_who.clear()
            # self.server.chat("/who")
            await self._update_stats()
        elif data == ["ON", "OFF"]:
            await self._reset_stats()

    @subscribe("setting:bedwars.tablist.is_mode_specific")
    async def bedwars_tablist_is_mode_specific_callback(self, data: list):
        # data = [old_state, new_state]
        if self.settings.bedwars.tablist.show_stats.get() == "ON":
            # Recalculate display names with new mode-specific setting
            for player, (uuid, _, fplayer) in self.players_with_stats.items():
                if isinstance(fplayer, FormattedPlayer):
                    show_rankname = self.settings.bedwars.tablist.show_rankname.get()
                    color_code = self.get_team_color_code(fplayer.raw_name)

                    if self.settings.bedwars.tablist.is_mode_specific.get() == "ON":
                        fkdr = fplayer.bedwars.__getattribute__(
                            f"{self.game.mode[8:].lower()}_stats"
                        )["fkdr"]
                    else:
                        fkdr = fplayer.bedwars.fkdr

                    display_name = " ".join(
                        (
                            f"{fplayer.bedwars.level}{color_code}",
                            fplayer.rankname
                            if show_rankname == "ON"
                            else fplayer.raw_name,
                            f" §7| {fkdr}",
                        )
                    )
                    self.players_with_stats[player] = (uuid, display_name, fplayer)

            # Update the tab list immediately
            self.keep_player_stats_updated()

    async def _reset_stats(self):
        for player in self.players_with_stats:
            for team in self.teams:
                if player in team.players:
                    self.client.send_packet(
                        0x38,
                        VarInt(3),
                        VarInt(1),
                        UUID(uuid.UUID(str(self.players_with_stats[player][0]))),
                        Boolean(True),
                        Chat(team.prefix + player + team.suffix),
                    )

    @subscribe("setting:bedwars.tablist.show_rankname")
    async def bedwars_tablist_show_rankname_callback(self, data: list):
        show_rankname = self.settings.bedwars.tablist.show_rankname.get()
        for player, (_uuid, _dname, fplayer) in self.players_with_stats.items():
            if isinstance(fplayer, FormattedPlayer):
                color_code = self.get_team_color_code(fplayer.raw_name)
                display_name = " ".join(
                    (
                        f"{fplayer.bedwars.level}{color_code}",
                        fplayer.rankname if show_rankname == "ON" else fplayer.raw_name,
                        f" §7| {fplayer.bedwars.fkdr}",
                    )
                )
                self.players_with_stats[player] = (_uuid, display_name, fplayer)
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
            elif action == 4:  # remove player
                try:
                    del self.players[str(_uuid)]
                except KeyError:
                    pass  # some things fail idk

        self.client.send_packet(0x38, buff.getvalue())
        self.keep_player_stats_updated()

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

    async def _sc_internal(
        self,
        ign: str = "",
        mode: str = "bedwars",
        window: Optional[float] = -1.0,
        *stats,
    ):  # display_abridged=True
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

        fplayer = FormattedPlayer(current_player)

        hover_text = ""
        if window:  # "unless we are fetching lifetime stats"
            # Check that necessary cumulative keys exist.
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

            # Determine target timestamp (exactly one week ago).
            now = datetime.datetime.now()
            target_time = now - datetime.timedelta(days=window)

            # Read and parse the stat log file.
            if not os.path.exists(self.log_path):
                raise CommandException(
                    "No log file found; recent stats unavailable. For lifetime stats, use /sc <player>."
                )

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

            # Filter entries: they must be dated at most 3x the given window.
            valid_entries = [
                entry
                for entry in entries
                if now - entry["dt"] <= datetime.timedelta(days=window * 3)
            ]
            if not valid_entries:
                raise CommandException(
                    "Insufficient logged data: logged stats too old."
                )

            # Choose the entry whose timestamp is closest to one week ago.
            chosen_entry = min(
                valid_entries,
                key=lambda entry: abs((entry["dt"] - target_time).total_seconds()),
            )
            old_stats = chosen_entry["bedwars"]
            chosen_date = chosen_entry["dt"]

            # Compute weekly differences (deltas) for overall stats.
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

            # Compute weekly FKDR and WLR.
            try:
                weekly_fkdr = (
                    diffs["final_kills_bedwars"] / diffs["final_deaths_bedwars"]
                    if diffs["final_deaths_bedwars"] > 0
                    else float(diffs["final_kills_bedwars"])
                )
            except Exception:
                weekly_fkdr = 0
            try:
                weekly_wlr = (
                    diffs["wins_bedwars"] / diffs["losses_bedwars"]
                    if diffs["losses_bedwars"] > 0
                    else float(diffs["wins_bedwars"])
                )
            except Exception:
                weekly_wlr = 0

            weekly_fkdr = round(weekly_fkdr, 2)
            weekly_wlr = round(weekly_wlr, 2)

            # Override the live FKDR and WLR attributes on the player object.
            current_player.bedwars.fkdr = weekly_fkdr
            current_player.bedwars.wlr = weekly_wlr

            fplayer = FormattedPlayer(
                current_player
            )  # re-init formattedplayer with the overwritten attributes

            # Format the chosen log entry date as "Month Day, Year" with ordinal day.
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

            formatted_date = f"{chosen_date.strftime('%B')} {ordinal(chosen_date.day)}, {chosen_date.strftime('%Y')}"
            # Format the time as e.g. "8:42 PM" (remove any leading zero)
            formatted_time = chosen_date.strftime("%I:%M %p").lstrip("0")
            hover_text = f"Recent stats for {fplayer.rankname}\nCalculated using data from {formatted_date} ({formatted_time})\n"
        else:
            hover_text = f"Lifetime Stats for {fplayer.rankname}§f:\n"
            old_stats = {}

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

        # List of modes in the order to appear.
        modes = ["Solo", "Doubles", "3v3v3v3", "4v4v4v4"]
        # if not display_abridged:
        modes.extend(["4v4", "Rush", "Ultimate", "Lucky", "Castle", "Swap", "Voidless"])
        mode_lines = []

        dreams_linebreak_init, dreams_linebreak_complete = False, False
        for mode in modes:
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
                dreams_linebreak_init = True
                # For dream modes, aggregate over any key that includes the dream substring.
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

            try:
                mode_fkdr = diff_fk / diff_fd if diff_fd > 0 else float(diff_fk)
            except Exception:
                mode_fkdr = 0

            try:
                mode_wlr = (
                    diff_wins / diff_losses if diff_losses > 0 else float(diff_wins)
                )
            except Exception:
                mode_wlr = 0

            # Round the results and apply color formatting for the numeric values.
            mode_fkdr = round(mode_fkdr, 2)
            mode_wlr = round(mode_wlr, 2)
            formatted_mode_fkdr = format_bw_fkdr(mode_fkdr)
            formatted_mode_wlr = format_bw_wlr(mode_wlr)

            if dreams_linebreak_init and not dreams_linebreak_complete:
                mode_lines.append("\n")
                dreams_linebreak_complete = True

            mode_lines.append(
                f"\n§c§l[{mode.upper()}]  §r §fFKDR:§r {formatted_mode_fkdr} §fWLR:§r {formatted_mode_wlr}"
            )

        if mode_lines:
            hover_text += "".join(mode_lines)
        # if display_abridged:
        #     hover_text += "\n\n§7§oTo see all modes, use §l/scfull§r§7§o."

        # Format the hover text and send the chat message.
        return fplayer.format_stats(gamemode, *stats).hover_text(hover_text)

    @command("sc")
    async def statcheck(
        self, ign: str = "", mode: str = "bedwars", window: float = -1.0, *stats: str
    ):
        return await self._sc_internal(ign, mode, window, *stats)

    @command("scw")
    async def scweekly(self, ign: str = "", mode: str = "bedwars", *stats: str):
        return await self._sc_internal(ign, mode, 7.0, *stats)

    # @command("scfull")
    # async def statcheckfull(self, ign=None, mode=None, window=None, *stats):
    #     return await self._sc_internal(ign, mode, window, False, *stats)

    async def _get_player(self, player: str):
        return self._cached_players.get(player) or await self.hypixel_client.player(
            player
        )

    def get_team_color_code(self, player_name: str) -> str:
        """Return the Minecraft color code (e.g. '§c') for a player, or '' if unknown."""
        # Nicked player cached color (prefix)
        if player_name in self.nick_team_colors:
            m = COLOR_CODE.search(self.nick_team_colors[player_name])
            return m.group(1) if m else ""
        team = self.get_team(player_name)
        if not team or not team.prefix:
            return ""
        m = COLOR_CODE.search(team.prefix)
        return m.group(1) if m else ""

    def get_team_color_name(self, player_name: str) -> str:
        """Return plain color name (e.g. 'Red') if derivable, else raise ValueError."""
        team = self.get_team(player_name)
        if not team:
            raise ValueError("Provided player is not on a team!")
        # Team names look like 'Red8'; strip digits
        return re.sub(r"\d+", "", team.name)

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
                try:
                    player_result = await result
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

                if player.name in self.players.values():
                    # Only cache actual Player objects, not Nick objects
                    if not isinstance(player, (PlayerNotFound, Nick)):
                        self._cached_players[player.name] = player

                        fplayer = FormattedPlayer(player)

                        # technically we don't need this since only bedwars
                        # is currently supported. but... futureproofing !!!
                        if self.game.gametype == "bedwars":
                            show_rankname = (
                                self.settings.bedwars.tablist.show_rankname.get()
                            )
                            color_code = self.get_team_color_code(fplayer.raw_name)
                            if (
                                self.settings.bedwars.tablist.is_mode_specific.get()
                                == "ON"
                            ):
                                fkdr = fplayer.bedwars.__getattribute__(
                                    f"{self.game.mode[8:].lower()}_stats"
                                )["fkdr"]
                            else:
                                fkdr = fplayer.bedwars.fkdr
                            display_name = " ".join(
                                (
                                    f"{fplayer.bedwars.level}{color_code}",
                                    fplayer.rankname
                                    if show_rankname == "ON"
                                    else fplayer.raw_name,
                                    f" §7| {fkdr}",
                                )
                            )
                        # elif self.game.gametype == "skywars":
                        #     display_name = " ".join(
                        #         (
                        #             fplayer.skywars.level,
                        #             fplayer.rankname,
                        #             f" | {fplayer.skywars.kdr}",
                        #         )
                        #     )
                        else:  # also this shouldn't run because we already
                            # early return on self.game.gametype not being "bedwars"
                            display_name = fplayer.rankname
                    else:  # if is a nicked player
                        # get team color for nicked player
                        for team in self.teams:
                            if player.name in team.players:
                                self.nick_team_colors.update({player.name: team.prefix})
                                break

                        display_name = f"§5[NICK] {player.name}"
                        fplayer = player

                    # this is where we actually update player stats in tab
                    prefix, suffix = next(
                        (
                            (team.prefix, team.suffix)
                            for team in self.teams
                            if player.name in team.players
                        ),
                        # if cannot find prefix/suffix
                        # just return empty strings by default
                        ("", ""),
                    )

                    self.players_with_stats.update(
                        {
                            player.name: (
                                player.uuid,
                                prefix + display_name + suffix,
                                fplayer,
                            )
                        }
                    )

                    if self.settings.bedwars.tablist.show_stats.get() == "ON":
                        self.client.send_packet(
                            0x38,
                            VarInt(3),
                            VarInt(1),
                            UUID(uuid.UUID(str(player.uuid))),
                            Boolean(True),
                            Chat(display_name),
                        )

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
        try:
            side_rush, alt_rush = self.get_adjacent_teams()
        except ValueError:  # player is not on a team
            return
        side_players = self.get_players_on_team(side_rush)
        alt_players = self.get_players_on_team(alt_rush)

        map_data = BW_MAPS[self.game.map]
        rush_direction = map_data["rush_direction"]

        if rush_direction == "side":
            first_rush, first_players = side_rush, side_players
            other_adjacent_rush, other_adjacent_players = alt_rush, alt_players
        elif rush_direction == "alt":
            first_rush, first_players = alt_rush, alt_players
            other_adjacent_rush, other_adjacent_players = side_rush, side_players
        else:
            raise ValueError(
                f'Expected Literal "side" or "alt" for BW_MAPS["{self.game.map}"]["rush_direction"]; got {rush_direction} instead.'
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
                title = self.players_with_stats[first_players[0]][1]
            case (
                2
            ):  # team of 2; calculate which one has better stats based on user pref
                fp1 = self.players_with_stats[first_players[0]][2]
                fp2 = self.players_with_stats[first_players[1]][2]

                if isinstance(fp1, Nick):
                    better = fp1
                    worse = fp2
                elif isinstance(fp2, Nick):
                    better = fp2
                    worse = fp1
                else:
                    better, worse = sorted((fp1, fp2), key=key, reverse=True)

                if isinstance(better, FormattedPlayer):
                    title = self.players_with_stats[better.raw_name][1]
                else:
                    title = self.players_with_stats[better.name][1]

                if self.settings.bedwars.announce_first_rush.get() == "FIRST RUSH":
                    # if we aren't showing alt rush team stats, we can show both players from first rush
                    if isinstance(worse, FormattedPlayer):
                        subtitle = self.players_with_stats[worse.raw_name][1]
                    else:
                        subtitle = self.players_with_stats[worse.name][1]
            case _:
                raise ValueError(
                    f"wtf how are there {len(first_players)} ppl on that team???\nplayers on first rush team: {first_players}"
                )

        if self.settings.bedwars.announce_first_rush.get() == "BOTH ADJACENT":
            match len(other_adjacent_players):
                case 0:
                    subtitle = empty_team_dialogue_alt
                case 1:
                    subtitle = self.players_with_stats[other_adjacent_players[0]][1]
                case 2:
                    fp1 = self.players_with_stats[other_adjacent_players[0]][2]
                    fp2 = self.players_with_stats[other_adjacent_players[1]][2]
                    if isinstance(fp1, Nick):
                        better = fp1
                        worse = fp2
                    elif isinstance(fp2, Nick):
                        better = fp2
                        worse = fp1
                    else:
                        better, worse = sorted((fp1, fp2), key=key, reverse=True)

                    if isinstance(better, FormattedPlayer):
                        subtitle = self.players_with_stats[better.raw_name][1]
                    else:
                        subtitle = self.players_with_stats[better.name][1]
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
        """
        Returns (side_rush, alt_rush) teams
        """
        team = self.get_own_team_color().lower()
        # will raise valueerror if player is not on a team; handle!

        side_rush = RUSH_MAPPINGS["default_mappings"]["side_rushes"][team]
        alt_rush = RUSH_MAPPINGS["default_mappings"]["alt_rushes"][team]

        return (side_rush, alt_rush)

    def get_players_on_team(self, color: str) -> list[str]:
        """
        Return a de-duplicated list of player names on the given team color
        Accepts 'green', 'Green', 'GREEN', etc
        """
        # target = color.lower()
        # if not any(t.name == target for t in self.teams):
        #     raise ValueError(f'Expected a team in self.teams ({self.teams}); got {color} instead.')
        # players: set[str] = set()
        # for team in self.teams:
        #     if team.name == target:
        #         players.update(team.players)
        # return list(players)

        target = color.lower()
        players: set[str] = set()
        for team in self.teams:
            # team names like 'Green8', 'Green9' -> strip digits to get color
            base_color = re.sub(r"\d", "", team.name).lower()
            if base_color == target:
                players.update(team.players)
        return list(players)

    async def log_bedwars_stats(self, event: str) -> None:
        # chatgpt ahh comments
        """
        Fetch the current player's Bedwars stats via the API and append a log record only if the
        Bedwars data is different from the most recent log entry.
        The record includes a timestamp, the event ("login" or "logout"), the player's username,
        and the complete Bedwars stats as provided by the API.
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

    def get_own_team_color(self) -> str:
        """Returns stripped team color, like 'green' or 'pink'."""
        try:
            own_team = self.get_team_color_name(self.username)  # mostly works
            if own_team:  # fails if spectator
                return own_team
        except ValueError:
            pass  # nicked player probably

        sidebar_own_team = next(
            (team for team in self.teams if "YOU" in team.suffix), None
        )
        if sidebar_own_team is None:
            raise ValueError(
                "Player is not on a team; cannot determine own team color."
            )
        else:
            match_ = re.search(r"§[a-f0-9](\w+)(?=§f:)", sidebar_own_team.prefix)
            if match_:
                own_team_color = match_.group(1)
            else:
                raise ValueError(
                    f"Could not determine own team color; regex did not match prefix {sidebar_own_team.prefix!r}"
                )
        return own_team_color

    async def stat_highlights(self):
        """Display top 3 enemy players and nicked players."""
        if not self.players_with_stats:
            return "No stats found!"

        own_team_color = self.get_own_team_color()

        # find team color as str (e.g. Pink, Blue, etc.)
        # TODO: move to method?

        enemy_players = []
        enemy_nicks = []

        # Process each player
        for player_name, (_, display_name, _) in self.players_with_stats.items():
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

    def keep_player_stats_updated(self):
        # make sure player stats stays updated
        # hypixel resets sometimes
        n_players = len(self.players_with_stats.values())
        if self.settings.bedwars.tablist.show_stats.get() == "ON":
            self.client.send_packet(
                0x38,
                VarInt(3),
                VarInt(n_players),
                *(
                    UUID(uuid.UUID(str(uuid_))) + Boolean(True) + Chat(display_name)
                    for uuid_, display_name, _ in self.players_with_stats.values()
                ),
            )

    @subscribe(r"chat:server:.* has joined .*!")  # listens, does not replace
    async def on_queue(self, buff: Buffer):
        self.client.send_packet(0x02, buff.getvalue())
        if self.settings.bedwars.api_key_reminder.get() == "ON":
            raw = buff.unpack(Chat)
            plain = COLOR_CODE_RE.sub("", raw)

            m = JOIN_RE.match(plain)
            if m and m.group("ign").casefold() == self.username.casefold():
                # Ensure we have a recent validation
                now = asyncio.get_event_loop().time()
                needs_validation = self._api_key_valid is None or (
                    self._api_key_validated_at
                    and now - self._api_key_validated_at > self._api_key_ttl
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

    @subscribe(
        "chat:server:(You will respawn in 10 seconds!|Your bed was destroyed so you are a spectator!)"
    )
    async def on_chat_user_rejoin(self, buff: Buffer):
        self.server.send_packet(0x01, String("/who"))
        self.received_who.clear()
        self.client.send_packet(0x02, buff.getvalue())
        self.game.started = True

    @subscribe(f"chat:server:({'|'.join(game_start_msgs)})")
    async def on_chat_game_start(self, buff: Buffer):
        message = buff.unpack(Chat)

        if self.game.gametype != "bedwars" or self.stats_highlighted:
            return self.client.send_packet(0x02, buff.getvalue())

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
            await self.stat_highlights()
