import asyncio
import base64
import datetime
import json
import os
import random
import re
import uuid
from pathlib import Path
from typing import Self
from unittest.mock import Mock

import hypixel
import keyring
from hypixel import Player
from hypixel.errors import (
    ApiError,
    HypixelException,
    InvalidApiKey,
    KeyRequired,
    PlayerNotFound,
    RateLimitError,
)
from msmcauth.errors import InvalidCredentials, MsMcAuthException, NotPremium

from . import auth
from .aliases import Gamemode, Statistic
from .command import command, commands
from .datatypes import (
    UUID,
    Boolean,
    Buffer,
    Byte,
    ByteArray,
    Chat,
    Double,
    Float,
    Int,
    Pos,
    Position,
    String,
    UnsignedByte,
    UnsignedShort,
    VarInt,
)
from .errors import CommandException
from .formatting import FormattedPlayer, format_bw_fkdr, format_bw_wlr
from .mcmodels import Game, Team, Teams
from .net import Stream
from .proxy import Proxy, State, listen_client, listen_server


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.client = ""
        self.hypixel_client = None
        self._hypixel_api_key = ""

        self.game = Game()
        self.rq_game = Game()

        self.players: dict[str, str] = {}
        self.players_getting_stats = []
        self.players_with_stats = {}
        self.teams: list[Team] = Teams()

        self.waiting_for_locraw = False
        self.game_error = None  # if error has been sent that game
        self.logged_in = False
        self.logging_in = False

        self.client_stream: Stream

        # TODO move to config file or something similar
        self.CONNECT_HOST = ("mc.hypixel.net", 25565)
        self.log_path = "stat_log.jsonl"
        self.null_log_path = "null_stats.json"

    async def close(self):
        if not self.open:
            return

        await super().close()

        if self.hypixel_client:
            await self.log_bedwars_stats("logout")
            await self.hypixel_client.close()

    async def login_keep_alive(self):
        while True:
            await asyncio.sleep(10)
            if self.state == State.PLAY and self.client_stream.open:
                self.client_stream.send_packet(0x00, VarInt(random.randint(0, 256)))
            else:
                await self.close()
                break

    async def login(self):
        # immediately send login start to enter login server
        self.state = State.PLAY
        self.logging_in = True

        # fake server stream
        self.server_stream = Mock()
        self.client_stream.send_packet(
            0x02, String(str(uuid.uuid4())), String(self.username)
        )

        self.client_stream.send_packet(
            0x01,
            Int(0),
            UnsignedByte(3),
            Byte(b"\x01"),
            UnsignedByte(0),
            UnsignedByte(1),
            String("default"),
            Boolean(True),
        )

        self.client_stream.send_packet(0x05, Position(Pos(0, 0, 0)))
        self.client_stream.send_packet(
            0x08, Double(0), Double(0), Double(0), Float(0), Float(0), Byte(b"\x00")
        )

        asyncio.create_task(self.login_keep_alive())

        self.client_stream.chat(
            "You have not logged into Proxhy with this account yet!"
        )
        self.client_stream.chat("Use /login <email> <password> to log in.")

    @listen_client(0x00, State.HANDSHAKING, blocking=True)
    async def packet_handshake(self, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)

    @listen_client(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        self.username = buff.unpack(String)

        if not auth.user_exists(self.username):
            return await self.login()

        reader, writer = await asyncio.open_connection(
            self.CONNECT_HOST[0], self.CONNECT_HOST[1]
        )
        self.server_stream = Stream(reader, writer)
        self.server_stream.destination = 1
        asyncio.create_task(self.handle_server())

        self.server_stream.send_packet(
            0x00,
            VarInt(47),
            String(self.CONNECT_HOST[0]),
            UnsignedShort(self.CONNECT_HOST[1]),
            VarInt(State.LOGIN.value),
        )

        self.access_token, self.username, self.uuid = auth.load_auth_info(self.username)
        self.server_stream.send_packet(0x00, String(self.username))

    @listen_server(0x02, State.LOGIN, blocking=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.logged_in = True

        self.hypixel_client = hypixel.Client(self.hypixel_api_key)

        await self.log_bedwars_stats("login")

        self.client_stream.send_packet(0x02, buff.read())

    @listen_client(0x17)
    async def packet_plugin_channel(self, buff: Buffer):
        self.server_stream.send_packet(0x17, buff.getvalue())

        channel = buff.unpack(String)
        data = buff.unpack(ByteArray)
        if channel == "MC|Brand":
            if b"lunarclient" in data:
                self.client = "lunar"
            elif b"vanilla" in data:
                self.client = "vanilla"

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, buff: Buffer):
        self.entity_id = buff.unpack(Int)

        # flush player lists
        self.players.clear()
        self.players_with_stats.clear()
        self.players_getting_stats.clear()

        self.game_error = None
        self.client_stream.send_packet(0x01, buff.getvalue())

        if not self.client == "lunar":
            self.waiting_for_locraw = True
            self.server_stream.send_packet(0x01, String("/locraw"))

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
            self.client_stream.send_packet(
                0x38,
                VarInt(3),
                VarInt(1),
                UUID(uuid.UUID(str(_uuid))),
                Boolean(True),
                Chat(prefix + display_name + suffix),
            )
        self.client_stream.send_packet(0x3E, buff.getvalue())

        if mode in {b"\x03", b"\x04"}:
            asyncio.create_task(self._update_stats())

    @listen_server(0x02)
    async def packet_server_chat_message(self, buff: Buffer):
        message = buff.unpack(Chat)

        async def _update_game(self: Self, game: dict):
            self.game.update(game)
            if game.get("mode"):
                return self.rq_game.update(game)
            else:
                return

        if re.match(r"^\{.*\}$", message):  # locraw
            if self.waiting_for_locraw:
                if "limbo" in message:  # sometimes returns limbo right when you join
                    if not self.teams:  # probably in limbo
                        return
                    elif self.client != "lunar":
                        await asyncio.sleep(0.1)
                        return self.server_stream.send_packet(0x01, String("/locraw"))
                else:
                    self.waiting_for_locraw = False
                    await _update_game(self, json.loads(message))
            else:
                await _update_game(self, json.loads(message))

        self.client_stream.send_packet(0x02, buff.getvalue())

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
                    self.client_stream.chat(f"§9§l∎ §4{err.message}")
                else:
                    if output:
                        if segments[0].startswith("//"):  # send output of command
                            # remove chat formatting
                            output = re.sub(r"§.", "", output)
                            self.server_stream.chat(output)
                        else:
                            self.client_stream.chat(output)
            else:
                self.server_stream.send_packet(0x01, buff.getvalue())
        else:
            self.server_stream.send_packet(0x01, buff.getvalue())

    @listen_client(0x14)
    async def packet_tab_complete(self, buff: Buffer):
        text = buff.unpack(String)
        if text.startswith("//"):
            self.server_stream.send_packet(0x14, String(text[1:]), buff.read())
        else:
            self.server_stream.send_packet(0x14, buff.getvalue())

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

        self.client_stream.send_packet(0x38, buff.getvalue())

    @command("login")
    async def login_command(self, email, password):
        self.client_stream.chat("§6Logging in...")
        if not self.logging_in:
            raise CommandException("You can't use that right now!")

        try:
            access_token, username, uuid = auth.login(email, password)
        except InvalidCredentials:
            raise CommandException("Login failed; invalid credentials!")
        except MsMcAuthException:
            raise CommandException(
                "An unknown error occurred while logging in! Try again?"
            )
        except NotPremium:
            raise CommandException("This account is not premium!")

        if username != self.username:
            raise CommandException(
                f"Wrong account! Logged into {username}; expected {self.username}"
            )

        self.access_token = access_token
        self.uuid = uuid

        self.client_stream.chat("§aLogged in; rejoin proxhy to play!")

    @command("rq")
    async def requeue(self):
        if not self.rq_game.mode:
            raise CommandException("No game to requeue!")
        else:
            self.server_stream.send_packet(0x01, String(f"/play {self.rq_game.mode}"))

    @command()  # Mmm, garlic bread.
    async def garlicbread(self):  # Mmm, garlic bread.
        return "§eMmm, garlic bread."  # Mmm, garlic bread.

    @command("scold")
    async def statcheck_old(self, ign=None, mode=None, *stats):
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

    async def _sc_internal(
        self, ign=None, mode=None, window=None, display_abridged=True, *stats
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

        # Use player's name and assume gamemode is bedwars.
        ign = ign or self.username
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
            hover_text = f"Recent stats for {fplayer.rankname}\nCalculated using data from §e{formatted_date}§f §7({formatted_time})§f\n"
        else:
            hover_text = f"Lifetime Stats for {fplayer.rankname}"
            with open(self.null_log_path, "r") as f:
                null_stats = json.load(f)
                old_stats = null_stats["bedwars"]

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
        if not display_abridged:
            modes.extend(
                ["4v4", "Rush", "Ultimate", "Lucky", "Castle", "Swap", "Voidless"]
            )
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

            # Skip mode if no difference in any stat.
            if diff_fk == 0 and diff_fd == 0 and diff_wins == 0 and diff_losses == 0:
                continue

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
        if display_abridged:
            hover_text += f"\n\n§7§oTo see all modes, use §l/scfull§r§7§o."
        # ---------------------------------------------------

        # Generate the main text using FormattedPlayer.format_stats
        main_text = fplayer.format_stats(gamemode, *stats)
        # Construct the JSON chat payload with hoverEvent.
        json_payload = {
            "text": main_text,
            "hoverEvent": {"action": "show_text", "value": hover_text},
        }
        json_message = json.dumps(json_payload)
        # Build the chat packet manually and send it.
        packet = String(json_message) + b"\x00"
        self.client_stream.send_packet(0x02, packet)
        # Return None so that the default chat routine doesn't resend.
        return None

    @command("sc")
    async def statcheck(self, ign=None, mode=None, window=None, *stats):
        await self._sc_internal(ign, mode, window, *stats)

    @command("scw")
    async def scweekly(self, ign=None, mode=None, *stats):
        await self._sc_internal(ign, mode, window=7, *stats)

    @command("scfull")
    async def statcheckfull(self, ign=None, mode=None, window=None, *stats):
        await self._sc_internal(ign, mode, window, display_abridged=False, *stats)

    # sorta debug commands
    @command("game")
    async def _game(self):
        self.client_stream.chat("§aGame:")
        for key in self.game.__annotations__:
            if value := getattr(self.game, key):
                self.client_stream.chat(f"§b{key.capitalize()}: §e{value}")

    @command("rqgame")
    async def _rqgame(self):
        self.client_stream.chat("§aRequeue Game:")
        for key in self.rq_game.__annotations__:
            if value := getattr(self.rq_game, key):
                self.client_stream.chat(f"§b{key.capitalize()}: §e{value}")

    @command("setting")
    async def edit_settings(self, s_name):
        try:
            setting_obj = getattr(settings, s_name)
            old_state = setting_obj.state
            old_state_color = setting_obj.states_dict[old_state]
            new_state = setting_obj.next_state()
            new_state_color = setting_obj.states_dict[new_state]
            self.client_stream.chat(
                f"Changed §e{setting_obj.display_name}§r from {old_state_color + '§l' + old_state.upper()}§r to {new_state_color + '§l' + new_state.upper()}§r!"
            )
            if s_name == "tablist_fkdr":
                if new_state.lower() == "on":
                    await self._update_stats()
                # TODO: implement reset_tablist() below
                # elif new_state.lower() == "off":
                #     await self.reset_tablist()
        except AttributeError as e:
            raise CommandException(e)

    @property
    def hypixel_api_key(self):
        if self._hypixel_api_key:
            return self._hypixel_api_key

        return keyring.get_password("proxhy", "hypixel_api_key")

    @hypixel_api_key.setter
    def hypixel_api_key(self, key):
        self._hypixel_api_key = key

        auth.safe_set("proxhy", "hypixel_api_key", key)

    @command()
    async def key(self, key):
        try:
            new_client = hypixel.Client(key)
            await new_client.player("gamerboy80")  # test key
            # await new_client.validate_keys()
        except (InvalidApiKey, KeyRequired, ApiError):
            raise CommandException("Invalid API Key!")
        finally:
            if new_client:
                await new_client.close()

        if self.hypixel_client:
            await self.hypixel_client.close()

        self.hypixel_api_key = key
        self.hypixel_client = hypixel.Client(key)
        self.client_stream.chat("§aUpdated API Key!")

        await self._update_stats()

    async def _update_stats(self):
        if self.waiting_for_locraw:
            return

        # update stats in tab in a game, bw supported so far
        if (
            self.game.gametype in {"bedwars"}
            and self.game.mode
            and settings.tablist_fkdr.state == "on"
        ):
            # players are in these teams in pregame
            real_player_teams: list[Team] = [
                team for team in self.teams if re.match("§.§l[A-Z] §r§.", team.prefix)
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
                        self.client_stream.chat(err_message[type(player)])
                    continue
                elif not isinstance(player, Player):
                    # TODO log this
                    # Session is closed probably, this is pointless
                    continue

                if player.name in self.players.values():
                    if not isinstance(player, PlayerNotFound):  # nick, probably
                        fplayer = FormattedPlayer(player)

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
                    self.client_stream.send_packet(
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
        except Exception as e:
            print(f"Failed to log stats on {event}: {e}")
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
            except Exception as e:
                print(f"Error checking last log entry: {e}")

        # Append the new log entry as a JSON line.
        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            print(f"Error writing stat log: {e}")
