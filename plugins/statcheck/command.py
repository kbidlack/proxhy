import asyncio
import datetime
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

import hypixel
import orjson

from petty.events import subscribe
from petty.protocol.datatypes import TextComponent
from plugins.commands import CommandContext, CommandException, Lazy, command
from proxhy.argtypes import Gamemode, HypixelPlayer, Statistic
from proxhy.argtypes.hypixel import GAMETYPE_T, Stat
from proxhy.utils import APIClient
from proxhypixel.formatting import (
    format_bedwars_dict,
    format_bw_star,
    format_skywars_dict,
    get_rankname,
)
from proxhypixel.mappings import (
    BEDWARS_DREAM_MAPPING_SIMPLE,
    BEDWARS_MAPPING_SIMPLE,
    BEDWARS_NON_DREAM_MAPPING,
    SKYWARS_MODE_MAPPING,
    SKYWARS_MODE_MAPPING_EXTRA,
    SKYWARS_MODE_MAPPING_FULL,
)

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin


class SCSupportedGamemode(Gamemode):
    SUPPORTED: set[GAMETYPE_T] = {"bedwars", "skywars"}

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> SCSupportedGamemode:
        gamemode = await super().convert(ctx, value)
        if gamemode.mode_str not in cls.SUPPORTED:
            raise CommandException(
                TextComponent(gamemode.display_name)
                .color("gold")
                .appends("is not a supported gamemode!")
            )
        return cls(gamemode.mode_str)

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        s = partial.lower().strip()
        return [
            cls.GAMES[mode]["main_alias"]
            for mode in cls.SUPPORTED
            if cls.GAMES[mode]["main_alias"].startswith(s)
        ]


class StatcheckCommandPlugin:
    log_path: Path
    log_stats: Callable[[str], Coroutine[Any, Any, None]]

    def _resolve_mode(
        self: ProxhyPlugin, mode: Optional[SCSupportedGamemode]
    ) -> SCSupportedGamemode:
        if mode is not None:
            return mode
        if self.game.gametype in SCSupportedGamemode.SUPPORTED:
            return SCSupportedGamemode(self.game.gametype)  # type: ignore ???
        return SCSupportedGamemode("bedwars")

    @command("lastlogin", "ll")
    async def _command_lastlogin(
        self: ProxhyPlugin,
        _player: Optional[Lazy[HypixelPlayer]] = None,
    ):
        """Check when a player last logged in to Hypixel."""
        try:
            if _player is not None:
                player = (await _player)._player
            else:
                player = await self.hypixel_client.player(self.username)
        except Exception as e:
            raise CommandException(f"Failed to fetch player: {e}")

        rankname = get_rankname(player)

        if player.last_login is None:
            raise CommandException(
                TextComponent(rankname).appends("has their online status hidden.")
            )

        online = player.last_logout is None or player.last_login > player.last_logout
        if online:
            return (
                TextComponent(rankname)
                .color("white")
                .appends(TextComponent("is currently online.").color("green"))
            )
        else:
            local_login = player.last_login.astimezone()
            formatted = self._format_date_with_ordinal(local_login)
            tz_name = local_login.strftime("%Z")
            return (
                TextComponent(rankname)
                .color("white")
                .appends("last logged in")
                .appends(TextComponent(formatted).color("gold"))
                .appends(TextComponent(f"({tz_name})").color("gray"))
            )

    @command("sc", "statcheck")
    async def _command_statcheck(
        self: ProxhyPlugin,
        _player: Optional[Lazy[HypixelPlayer]] = None,
        mode: Optional[SCSupportedGamemode] = None,
        window: Optional[float] = None,
        *stats: Statistic,
    ):
        """Check player stats."""
        player = await _player if _player else None
        return await self._sc_internal(
            player=player,
            mode=self._resolve_mode(mode),
            window=window,
            stat_names=stats,
        )

    @command("scw", "scweekly")
    async def _command_scweekly(
        self: ProxhyPlugin,
        _player: Optional[Lazy[HypixelPlayer]] = None,
        mode: Optional[SCSupportedGamemode] = None,
        *stats: Statistic,
    ):
        """Check player stats for the past 7 days."""
        player = await _player if _player else None
        return await self._sc_internal(
            player=player,
            mode=self._resolve_mode(mode),
            window=7.0,
            stat_names=stats,
        )

    @command("scwfull", "scweeklyfull")
    async def _command_scweeklyfull(
        self: ProxhyPlugin,
        _player: Optional[Lazy[HypixelPlayer]] = None,
        mode: Optional[SCSupportedGamemode] = None,
        *stats: Statistic,
    ):
        """Check player stats for the past 7 days with all modes."""
        player = await _player if _player else None
        return await self._sc_internal(
            player=player,
            mode=self._resolve_mode(mode),
            window=7.0,
            stat_names=stats,
            display_abridged=False,
        )

    @command("scfull")
    async def _command_scfull(
        self: ProxhyPlugin,
        _player: Optional[Lazy[HypixelPlayer]] = None,
        mode: Optional[SCSupportedGamemode] = None,
        window: Optional[float] = None,
        *stats: Statistic,
    ):
        """Check player stats with all modes."""
        player = await _player if _player else None
        return await self._sc_internal(
            player=player,
            mode=self._resolve_mode(mode),
            window=window,
            stat_names=stats,
            display_abridged=False,
        )

    @subscribe("login_success")
    async def _statcheck_event_login_success(self: ProxhyPlugin, _match, _data):
        self.create_task(self._login_success_helper())

    async def _login_success_helper(self: ProxhyPlugin):
        self.hypixel_client = hypixel.Client(
            self.hypixel_api_key, cache_h=False, cache_m=False
        )
        self.create_task(self.migrate_log_stats())
        self.create_task(self.log_stats("login"))

    @subscribe("close")
    async def _statcheck_event_close(self: ProxhyPlugin, _match, _data):
        self.create_task(self._close_statcheck_helper())

    async def _close_statcheck_helper(self: ProxhyPlugin):
        try:
            if self.hypixel_client:
                try:
                    await asyncio.wait_for(self.log_stats("logout"), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                try:
                    await asyncio.wait_for(self.hypixel_client.close(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass  # force close anyways
        except AttributeError:
            pass  # TODO: log

    async def log_stats(self: ProxhyPlugin, event: str) -> None:
        if self.dev_mode:
            return

        try:
            player = await self.hypixel_client.player(self.username)
            bedwars_stats = player._data.get("stats", {}).get("Bedwars", {})
            skywars_stats = player._data.get("stats", {}).get("Skywars", {})
            duels_stats = player._data.get("stats", {}).get("Duels", {})
        except Exception as e:
            self.logger.debug(f"Failed to log stats on {event}: {e}")
            return

        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "event": event,
            "player": player.uuid,
            "bedwars": bedwars_stats,
            "skywars": skywars_stats,
            "duels": duels_stats,
        }

        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r") as f:
                    lines = f.readlines()
                if lines:
                    last_line = lines[-1].strip()
                    last_entry = orjson.loads(last_line)
                    if (
                        last_entry.get("bedwars") == bedwars_stats
                        and last_entry.get("skywars") == skywars_stats
                        and last_entry.get("duels") == duels_stats
                    ):
                        return
            except Exception as e:
                print(f"Error checking last log entry: {e}")
                pass  # TODO: log this

        try:
            with open(self.log_path, "a") as f:
                f.write(orjson.dumps(log_entry).decode() + "\n")
        except Exception as e:
            print(f"Error writing stat log: {e}")
            pass  # TODO: log this

    @staticmethod
    def _is_uuid(value: str) -> bool:
        return bool(re.fullmatch(r"[0-9a-f]{32}", value, re.IGNORECASE))

    async def migrate_log_stats(self: ProxhyPlugin) -> None:
        """Migrate stat log entries that use player names to use UUIDs instead."""
        if not os.path.exists(self.log_path):
            return

        with open(self.log_path, "r") as f:
            lines = f.readlines()

        # Collect unique names that need migration
        names_to_resolve: set[str] = set()
        for line in lines:
            try:
                entry = orjson.loads(line.strip())
                player = entry.get("player", "")
                if player and not self._is_uuid(player):
                    names_to_resolve.add(player)
            except Exception:
                continue

        if not names_to_resolve:
            return

        # Resolve names to UUIDs via Mojang API
        name_to_uuid: dict[str, str] = {}
        async with APIClient() as client:
            for name in names_to_resolve:
                try:
                    info = await client.get_profile(name)
                    name_to_uuid[name] = info.uuid
                except Exception as e:
                    print(f"Failed to resolve UUID for '{name}': {e}")

        if not name_to_uuid:
            return

        # Rewrite the log file with UUIDs
        new_lines = []
        for line in lines:
            try:
                entry = orjson.loads(line.strip())
                player = entry.get("player", "")
                if player in name_to_uuid:
                    entry["player"] = name_to_uuid[player]
                new_lines.append(orjson.dumps(entry).decode() + "\n")
            except Exception:
                new_lines.append(line)

        with open(self.log_path, "w") as f:
            f.writelines(new_lines)

    def _find_closest_stat_log(
        self, uuid: str, window: float, gamemode: GAMETYPE_T
    ) -> tuple[dict, datetime.datetime]:
        now = datetime.datetime.now()
        target_time = now - datetime.timedelta(days=window)

        # Read and parse the stat log file
        entries = []
        with open(self.log_path, "r") as f:
            for line in f:
                try:
                    entry = orjson.loads(line.strip())
                    if entry.get("player", "").casefold() == uuid and entry.get(
                        gamemode
                    ):
                        entry["dt"] = datetime.datetime.fromisoformat(
                            entry["timestamp"]
                        )
                        entries.append(entry)
                except Exception:
                    continue

        if not entries:
            raise CommandException("No logged stats available for this player.")

        valid_entries = [
            entry
            for entry in entries
            if now - entry["dt"] <= datetime.timedelta(days=window * 3)
        ]
        if not valid_entries:
            raise CommandException("Insufficient logged data: logged stats too old.")

        chosen_entry = min(
            valid_entries,
            key=lambda entry: abs((entry["dt"] - target_time).total_seconds()),
        )

        return chosen_entry[gamemode], chosen_entry["dt"]

    def _calculate_stat_deltas(
        self, current_stats: dict, old_stats: dict, required_keys: list[str]
    ) -> dict:
        diffs = {}
        for key in required_keys:
            current_val = float(current_stats.get(key, 0))
            old_val = float(old_stats.get(key, 0))
            diff = current_val - old_val
            diffs[key] = diff
        return diffs

    def _calculate_ratios(
        self, kills: float, deaths: float, wins: float, losses: float
    ) -> tuple[float, float]:
        try:
            fkdr = kills / deaths if deaths > 0 else kills
        except Exception:
            fkdr = 0.0

        try:
            wlr = wins / losses if losses > 0 else wins
        except Exception:
            wlr = 0.0

        return round(fkdr, 2), round(wlr, 2)

    def _format_date_with_ordinal(self: ProxhyPlugin, dt: datetime.datetime) -> str:
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
        self: ProxhyPlugin,
        player: Optional[HypixelPlayer] = None,
        window: Optional[float] = None,
        mode: SCSupportedGamemode = SCSupportedGamemode("bedwars"),
        stat_names: tuple[Statistic, ...] = tuple(),
        display_abridged=True,
    ):
        gamemode = mode.mode_str

        # resolve player
        _GAMEMODE_API_KEY = {
            "bedwars": "Bedwars",
            "skywars": "SkyWars",
        }

        try:
            if player is not None:
                current_player = player._player
            else:
                current_player = await self.hypixel_client.player(self.username)
            api_key = _GAMEMODE_API_KEY.get(gamemode, gamemode.capitalize())
            current_stats = current_player._data.get("stats", {}).get(api_key, {})
        except (hypixel.KeyRequired, hypixel.InvalidApiKey):
            raise CommandException("Invalid Hypixel API key!")
        except Exception as e:
            raise CommandException(f"Failed to fetch current stats: {e}")

        stats = tuple(s.stat for s in stat_names)

        if gamemode == "bedwars":
            return await self._sc_bedwars(
                current_player, current_stats, window, stats, display_abridged
            )
        elif gamemode == "skywars":
            return await self._sc_skywars(
                current_player, current_stats, window, stats, display_abridged
            )

    async def _sc_bedwars(
        self: ProxhyPlugin,
        player: hypixel.Player,
        current_stats: dict,
        window: Optional[float],
        stats: tuple[Stat, ...],
        display_abridged=True,
    ):
        if not stats:
            STATS = Statistic.STATS["bedwars"]
            stats = (STATS["finals"], STATS["fkdr"], STATS["wins"], STATS["wlr"])

        required_modes = list(BEDWARS_NON_DREAM_MAPPING.values())
        if not display_abridged:
            required_modes.extend(BEDWARS_DREAM_MAPPING_SIMPLE.values())

        RATIO_DEPENDENCIES = {
            "fkdr": ("final_kills_bedwars", "final_deaths_bedwars"),
            "kdr": ("kills_bedwars", "deaths_bedwars"),
            "wlr": ("wins_bedwars", "losses_bedwars"),
            "bblr": ("beds_broken_bedwars", "beds_lost_bedwars"),
        }

        required_keys: list[str] = []
        for mode in [""] + [m.lower() for m in required_modes]:
            prefix = f"{mode}_" if mode else ""
            for s in stats:
                if s.json_key in RATIO_DEPENDENCIES:
                    for dep in RATIO_DEPENDENCIES[s.json_key]:
                        required_keys.append(f"{prefix}{dep}")
                else:
                    required_keys.append(f"{prefix}{s.json_key}")

        rankname = get_rankname(player)
        online = player.last_login and (
            player.last_logout is None or player.last_login > player.last_logout
        )
        online_suffix = " §a(ONLINE)" if online else ""

        if window is not None:
            old_stats, chosen_date = self._find_closest_stat_log(
                player.uuid, window, "bedwars"
            )
            diffs = self._calculate_stat_deltas(current_stats, old_stats, required_keys)
            fdict = format_bedwars_dict(diffs)

            formatted_date = self._format_date_with_ordinal(chosen_date)
            hover_text = f"Recent stats for {rankname}\nCalculated using data from {formatted_date}\n"
        else:
            fdict = format_bedwars_dict(current_stats)
            hover_text = f"Lifetime Stats for {rankname}§f:{online_suffix}\n"
            old_stats = {}

        modes = (
            BEDWARS_NON_DREAM_MAPPING if display_abridged else BEDWARS_MAPPING_SIMPLE
        )

        mode_stats = [s for s in stats if not s.overall_only]
        mode_lines = []
        dreams_linebreak_added = False

        for mode_, mode_key in modes.items():
            if (
                mode_ in BEDWARS_DREAM_MAPPING_SIMPLE
                and not dreams_linebreak_added
                and not display_abridged
            ):
                mode_lines.append("\n")
                dreams_linebreak_added = True

            mode_line = f"\n§c§l[{mode_.upper()}] "

            for stat in mode_stats:
                stat_json_key = f"{mode_key}_{stat.json_key}"
                stat_value = fdict.get(stat_json_key, 0)
                mode_line += f"§r§f{stat.name}: §r{stat_value} "

            mode_lines.append(mode_line)

        if mode_stats and mode_lines:
            hover_text += "".join(mode_lines)
        if mode_stats and display_abridged:
            hover_text += "\n\n§7§oTo see all modes, use §l/scfull§r§7§o."

        # TODO: reduce code duplication here
        stat_message = f"{format_bw_star(player.bedwars.level)} {rankname}: "
        for stat in stats:
            stat_value = fdict.get(stat.json_key, 0)
            stat_message += f"§r§f{stat.name}: §r{stat_value} "

        tc = TextComponent.from_legacy(stat_message)
        if mode_stats:
            tc = tc.hover_text(hover_text)
        return tc

    async def _sc_skywars(
        self: ProxhyPlugin,
        player: hypixel.Player,
        current_stats: dict,
        window: Optional[float],
        stats: tuple[Stat, ...],
        display_abridged=True,
    ):
        if not stats:
            STATS = Statistic.STATS["skywars"]
            stats = (STATS["kills"], STATS["kdr"], STATS["wins"], STATS["wlr"])

        SW_RATIO_DEPENDENCIES = {
            "kdr": ("kills", "deaths"),
            "wlr": ("wins", "losses"),
        }

        required_keys: list[str] = []
        for mode_suffix in [""] + list(SKYWARS_MODE_MAPPING_FULL.values()):
            suffix = f"_{mode_suffix}" if mode_suffix else ""
            for s in stats:
                if s.json_key in SW_RATIO_DEPENDENCIES:
                    for dep in SW_RATIO_DEPENDENCIES[s.json_key]:
                        required_keys.append(f"{dep}{suffix}")
                else:
                    required_keys.append(f"{s.json_key}{suffix}")

        rankname = get_rankname(player)
        online = player.last_login and (
            player.last_logout is None or player.last_login > player.last_logout
        )
        online_suffix = " §a(ONLINE)" if online else ""

        if window is not None:
            old_stats, chosen_date = self._find_closest_stat_log(
                player.uuid, window, "skywars"
            )
            diffs = self._calculate_stat_deltas(current_stats, old_stats, required_keys)
            fdict = format_skywars_dict(diffs)
            formatted_date = self._format_date_with_ordinal(chosen_date)
            hover_text = f"Recent stats for {rankname}\nCalculated using data from {formatted_date}\n"
        else:
            fdict = format_skywars_dict(current_stats)
            hover_text = f"Lifetime Stats for {rankname}§f:{online_suffix}\n"

        mode_stats = [s for s in stats if not s.overall_only]

        def _mode_line(mode_: str, mode_key: str) -> str:
            line = f"\n§c§l[{mode_.upper()}] "
            for stat in mode_stats:
                stat_value = fdict.get(f"{stat.json_key}_{mode_key}", 0)
                line += f"§r§f{stat.name}: §r{stat_value} "
            return line

        if mode_stats:
            hover_text += "".join(
                _mode_line(m, k) for m, k in SKYWARS_MODE_MAPPING.items()
            )
            if display_abridged:
                hover_text += "\n\n§7§oTo see all modes, use §l/scfull§r§7§o."
            else:
                hover_text += "\n"
                hover_text += "".join(
                    _mode_line(m, k) for m, k in SKYWARS_MODE_MAPPING_EXTRA.items()
                )

        star = (current_stats.get("levelFormattedWithBrackets") or "").rstrip()
        stat_message = f"{star} {rankname}: "
        for stat in stats:
            stat_value = fdict.get(stat.json_key, 0)
            stat_message += f"§r§f{stat.name}: §r{stat_value} "

        tc = TextComponent.from_legacy(stat_message)
        if mode_stats:
            tc = tc.hover_text(hover_text)
        return tc
