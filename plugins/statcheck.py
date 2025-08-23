import asyncio
import datetime
import json
import os
import re
import uuid
from pathlib import Path
from typing import Optional

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
from protocol import auth
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
from proxhy.settings import Settings

game_start_msgs = [  # block all the game start messages
    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
    "                                  Bed Wars",
    "     Protect your bed and destroy the enemy beds.",
    "      Upgrade yourself and your team by collecting",
    "    Iron, Gold, Emerald and Diamond from generators",
    "                  to access powerful upgrades.",
    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬",
]


class StatCheckPlugin(Plugin):
    username: str
    teams: Teams
    game: Game
    received_who: asyncio.Event
    received_locraw: asyncio.Event
    settings: Settings

    def _init_statcheck(self):
        self.players_with_stats = {}
        self.nick_team_colors: dict[str, str] = {}  # Nicked player team colors
        self.players_without_stats: set[str] = set()  # players from /who
        self._cached_players: dict = {}
        # players from packet_player_list_item
        self.players: dict[str, str] = {}
        self._hypixel_api_key = ""

        self.game_error = None  # if error has been sent that game
        self.stats_highlighted = False

        self.received_player_stats = asyncio.Event()

        self.player_stats_lock = asyncio.Lock()

        self.log_path = (
            Path(user_cache_dir("proxhy", ensure_exists=True)) / "stat_log.jsonl"
        )

    @property
    def hypixel_api_key(self):
        if self._hypixel_api_key:
            return self._hypixel_api_key

        return keyring.get_password("proxhy", "hypixel_api_key")

    @hypixel_api_key.setter
    def hypixel_api_key(self, key):
        self._hypixel_api_key = key

        auth.safe_set("proxhy", "hypixel_api_key", key)

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, _):
        # flush player lists
        self.players.clear()
        self.players_with_stats.clear()
        self._cached_players.clear()

        self.received_player_stats.clear()
        self.game_error = None
        self.stats_highlighted = False

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

    async def _get_player(self, player: str):
        return self._cached_players.get(player) or await self.hypixel_client.player(
            player
        )

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
                    self.settings.bedwars.tablist.show_stats.state != "OFF",
                    self.settings.bedwars.display_top_stats.state != "OFF",
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
                    }

                    # if an error message hasn't already been sent in this game
                    # game being hypixel sub-server, clears on packet_join_game
                    if not self.game_error:
                        self.game_error = player
                        self.client.chat(err_message[type(player)])

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
                            )
                        }
                    )

                    if self.settings.bedwars.tablist.show_stats.state == "ON":
                        self.client.send_packet(
                            0x38,
                            VarInt(3),
                            VarInt(1),
                            UUID(uuid.UUID(str(player.uuid))),
                            Boolean(True),
                            Chat(display_name),
                        )

        # if we've gotten everyone from /who, stat highlights can be called
        if self.settings.bedwars.display_top_stats.state != "OFF":
            if not self.stats_highlighted:
                await self.stat_highlights()
                self.stats_highlighted = True

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

    async def stat_highlights(self):
        """Display top 3 enemy players and nicked players."""
        if not self.players_with_stats:
            return "No stats found!"

        own_team = self.get_team(self.username)

        # find team color as str (e.g. Pink, Blue, etc.)
        # TODO: move to method?
        if own_team is not None:
            # teams in bedwars are like:
            # Pink8, Blue7, Green3, etc. per player
            # so pink team might have two players in teams Pink8 and Pink9
            own_team_color = re.sub(r"\d", "", own_team.name)
        else:
            # fall back team in sidebar
            # this might happen, for example, if player is in spec
            # since the above player teams do not apply in spec mode
            # so we look for "YOU" in sidebar
            sidebar_own_team = next(
                (team for team in self.teams if "YOU" in team.suffix), None
            )
            if sidebar_own_team is None:
                own_team_color = ""  # this shouldn't happen
            else:
                match_ = re.search(r"§[a-f0-9](\w+)(?=§f:)", sidebar_own_team.prefix)
                if match_:
                    own_team_color = match_.group(1)
                else:
                    own_team_color = ""  # this also shouldn't happen

        enemy_players = []
        enemy_nicks = []

        # Process each player
        for player_name, (_, display_name) in self.players_with_stats.items():
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
        if self.settings.bedwars.tablist.show_stats.state == "ON":
            self.client.send_packet(
                0x38,
                VarInt(3),
                VarInt(n_players),
                *(
                    UUID(uuid.UUID(str(uuid_))) + Boolean(True) + Chat(display_name)
                    for uuid_, display_name in self.players_with_stats.values()
                ),
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

    @subscribe(f"chat:server:({'|'.join(game_start_msgs)})")
    async def on_chat_game_start(self, buff: Buffer):
        message = buff.unpack(Chat)

        if self.game.gametype != "bedwars" or self.stats_highlighted:
            return self.client.send_packet(0x02, buff.getvalue())

        if self.settings.bedwars.display_top_stats.state == "OFF":
            self.client.send_packet(0x02, buff.getvalue())

        if message == game_start_msgs[-2]:
            # replace them with the statcheck overview
            if self.settings.bedwars.display_top_stats.state != "OFF":
                self.client.chat(
                    TextComponent("Fetching top stats...").color("gold").bold()
                )
            self.server.send_packet(0x01, String("/who"))
            self.received_who.clear()

    @command()
    async def key(self, key):
        try:
            new_client = hypixel.Client(key)
            await new_client.player("gamerboy80")  # test key
            # await new_client.validate_keys()
        except (InvalidApiKey, KeyRequired, ApiError):
            raise CommandException("Invalid API Key!")
        else:
            if new_client:
                await new_client.close()

        if self.hypixel_client:
            await self.hypixel_client.close()

        self.hypixel_api_key = key
        self.hypixel_client = hypixel.Client(key)
        api_key_msg = TextComponent("Updated API Key!").color("green")
        self.client.chat(api_key_msg)

        await self._update_stats()
