import asyncio
import datetime
import json
import os
import re
import uuid

from hypixel import (
    InvalidApiKey,
    KeyRequired,
    Player,
    PlayerNotFound,
    RateLimitError,
    TimeoutError,
)

from ..aliases import Gamemode
from ..command import command
from ..datatypes import UUID, Boolean, Chat, TextComponent, VarInt
from ..errors import CommandException
from ..formatting import FormattedPlayer, format_bw_fkdr, format_bw_wlr
from ..mcmodels import Nick
from ..proxhy import Proxhy
from ._methods import method


class StatCheck(Proxhy):
    _cached_players: dict
    nick_team_colors: dict[str, str]  # Nicked player team colors

    @method
    async def _sc_internal(
        self, ign=None, mode=None, window=None, *stats
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

        # Use player's name and assume gamemode is bedwars.
        ign = ign or self.username

        if (Gamemode(mode) or "bedwars") != "bedwars":
            raise CommandException("Currently only Bedwars stats are supported!")

        gamemode = "bedwars"

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
    async def statcheck(self, ign=None, mode=None, window=None, *stats):
        return await self._sc_internal(ign, mode, window, *stats)

    @command("scw")
    async def scweekly(self, ign=None, mode=None, *stats):
        return await self._sc_internal(ign, mode, 7, *stats)

    # @command("scfull")
    # async def statcheckfull(self, ign=None, mode=None, window=None, *stats):
    #     return await self._sc_internal(ign, mode, window, False, *stats)

    @method
    async def _update_stats(self):
        async with self.player_stats_lock:
            await self.received_locraw.wait()
            await self.received_who.wait()

            if not self.players_without_stats:
                # No players to update stats for
                return

            # update stats in tab in a game, bw supported so far
            if (
                (self.game.gametype in {"bedwars"})
                and self.game.mode
                and (self.settings.bedwars.tablist.show_fkdr.state == "ON")
            ):
                # Initialize cache if it doesn't exist
                if not hasattr(self, "_cached_players"):
                    self._cached_players = {}

                player_stats = await asyncio.gather(
                    *[
                        self.hypixel_client.player(player)
                        for player in self.players_without_stats
                    ],
                    return_exceptions=True,
                )

                for player in player_stats:
                    if isinstance(player, PlayerNotFound):
                        real_player = player.player
                        player = Nick(real_player)
                        try:
                            player.uuid = next(
                                u
                                for u, p in self.players.items()
                                if p.casefold() == real_player.casefold()
                            )
                        except StopIteration:
                            continue
                    elif isinstance(
                        player, (InvalidApiKey, RateLimitError, TimeoutError)
                    ):
                        err_message = {
                            InvalidApiKey: TextComponent("Invalid API Key!").color(
                                "red"
                            ),
                            KeyRequired: TextComponent("No API Key provided!").color(
                                "red"
                            ),
                            RateLimitError: TextComponent("Rate limit!").color("red"),
                            TimeoutError: TextComponent(
                                f"Request timed out! ({player})"
                            ).color("red"),
                        }

                        if not self.game_error:
                            self.game_error = player
                            self.client.chat(err_message[type(player)])
                        continue
                    elif not isinstance(player, Player):
                        # TODO log this
                        # Session is closed probably, this is pointless
                        continue

                    if player.name in self.players.values():
                        # Only cache actual Player objects, not Nick objects
                        if not isinstance(player, (PlayerNotFound, Nick)):
                            self._cached_players[player.name] = player

                        if not isinstance(player, (PlayerNotFound, Nick)):
                            fplayer = FormattedPlayer(player)

                            if self.game.gametype == "bedwars":
                                display_name = " ".join(
                                    (
                                        fplayer.bedwars.level,
                                        fplayer.rankname,
                                        f" §7| {fplayer.bedwars.fkdr}",
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
                            else:
                                display_name = fplayer.rankname
                        else:
                            # Get team color for nicked player
                            for team in self.teams:
                                if player.name in team.players:
                                    self.nick_team_colors.update(
                                        {player.name: team.prefix}
                                    )
                                    break

                            display_name = f"§5[NICK] {player.name}"

                        self.client.send_packet(
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

            self.received_player_stats.set()

    @method
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

    @method
    async def stat_highlights(self):
        """Display top 3 enemy players and nicked players."""
        await self.received_player_stats.wait()

        if not self.players_with_stats:
            return "No stats found!"

        own_team = self.get_own_team()
        enemy_players = []
        enemy_nicks = []

        # Process each player
        for player_name, (player_uuid, display_name) in self.players_with_stats.items():
            # Skip the user's own nickname
            if player_name == self.username:
                continue

            # Get player's team
            player_team = ""
            for team in self.teams:
                if player_name in team.players:
                    player_team = team.prefix
                    break

            # Skip teammates
            if player_team == own_team and own_team != "":
                continue

            # Handle nicked players
            if "[NICK]" in display_name:
                nick_team_color = self.nick_team_colors.get(player_name, "")
                enemy_nicks.append(f"{nick_team_color}{player_name}§f")
                continue

            # Handle regular players with stats
            if hasattr(self, "_cached_players") and player_name in self._cached_players:
                player = self._cached_players[player_name]
                fplayer = FormattedPlayer(player)

                # Calculate ranking value
                fkdr = int(fplayer.bedwars.raw_fkdr)
                stars = int(fplayer.bedwars.raw_level)

                if self.settings.bedwars.display_top_stats.state == "FKDR":
                    rank_value = fkdr
                elif self.settings.bedwars.display_top_stats.state == "STARS":
                    rank_value = stars
                elif self.settings.bedwars.display_top_stats.state == "INDEX":
                    rank_value = fkdr * stars
                else:
                    rank_value = fkdr

                enemy_players.append(
                    {
                        "name": player_name,
                        "star_formatted": fplayer.bedwars.level,
                        "fkdr_formatted": fplayer.bedwars.fkdr,
                        "rank_value": rank_value,
                        "team_color": player_team,
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

        return result

    @method
    def get_own_team(self):
        """Get the user's own team prefix. Returns team prefix or empty string if not found."""
        # First try to use the cached team prefix from the "(YOU)" marker
        if hasattr(self, "_user_team_prefix") and self._user_team_prefix:
            return self._user_team_prefix

        # Fallback: look for team with "(YOU)" in suffix
        for team in self.teams:
            clean_suffix = re.sub(r"§.", "", team.suffix)
            if any(
                marker in team.suffix or marker in clean_suffix
                for marker in ["(YOU)", "(You)", " YOU", " You"]
            ):
                self._user_team_prefix = team.prefix
                return team.prefix

        # Last resort: try to find user by username (less reliable when nicked)
        for team in self.teams:
            if self.username in team.players:
                return team.prefix

        return ""
