import dataclasses
import json
import random
import re
import string
import time
from dataclasses import dataclass

from hypixel import HypixelException, InvalidApiKey, PlayerNotFound, RateLimitError
from quarry.net.proxy import Bridge
from quarry.types.buffer import Buffer1_7

from formatting import FormattedPlayer
from patches import pack_chat


class Teams(list):
    def __getitem__(self, key):
        return next((team for team in self if team.name == key), None)

    def __delitem__(self, key):
        team = self[key]
        if team:
            self.remove(team)


@dataclass
class Team:
    name: str
    display_name: str
    prefix: str
    suffix: str
    friendly_fire: int
    name_tag_visibility: str
    color: int
    players: set[str]

    bridge: type[Bridge]
    buff: Buffer1_7 = Buffer1_7()

    def __post_init__(self):
        self.team_attrs: set = {
            "name",
            "display_name",
            "prefix",
            "suffix",
            "friendly_fire",
            "name_tag_visibility",
            "color",
        }

    def create(self):
        packet = b"".join(
            (
                self.buff.pack_string(self.name),
                b"\x00",  # mode
                self.buff.pack_string(self.display_name),
                self.buff.pack_string(self.prefix),
                self.buff.pack_string(self.suffix),
                self.friendly_fire.to_bytes(),
                self.buff.pack_string(self.name_tag_visibility),
                self.color.to_bytes(),
                self.buff.pack_varint(len(self.players)),
                *(self.buff.pack_string(player) for player in self.players),
            )
        )
        self.bridge.downstream.send_packet("teams", packet)

    def delete(self):
        packet = b"".join((self.buff.pack_string(self.name), b"\x01"))  # mode
        self.bridge.downstream.send_packet("teams", packet)

    def update(
        self,
        name: str = None,
        display_name: str = None,
        prefix: str = None,
        suffix: str = None,
        friendly_fire: int = None,
        name_tag_visibility: str = None,
        color: int = None,
    ):
        self.name = name or self.name
        self.display_name = display_name or self.display_name
        self.prefix = prefix or self.prefix
        self.suffix = suffix or self.suffix
        self.friendly_fire = friendly_fire or self.friendly_fire
        self.name_tag_visibility = name_tag_visibility or self.name_tag_visibility
        self.color = color or self.color

        packet = b"".join(
            (
                self.buff.pack_string(self.name),
                b"\x02",  # mode
                self.buff.pack_string(self.display_name),
                self.buff.pack_string(self.prefix),
                self.buff.pack_string(self.suffix),
                self.friendly_fire.to_bytes(),
                self.buff.pack_string(self.name_tag_visibility),
                self.color.to_bytes(),
            )
        )

        self.bridge.downstream.send_packet("teams", packet)

    def update_players(self, add=True, *new_players: str):
        # add=True; add players, add=False; remove players
        for player in new_players:
            if add:
                self.players.add(player)
            else:
                try:
                    self.players.remove(player)
                except KeyError:
                    pass  # hehe

        packet = b"".join(
            (
                self.buff.pack_string(self.name),
                b"\x03" if add else b"\x04",  # mode
                self.buff.pack_varint(len(new_players)),
                *(self.buff.pack_string(player) for player in new_players),
            )
        )

        self.bridge.downstream.send_packet("teams", packet)


@dataclass
class Game:
    server: str | None = None
    gametype: str | None = None
    mode: str | None = None
    map: str | None = None
    lobbyname: str | None = None

    pregame: bool | None = None

    def __setattr__(self, name: str, value) -> None:
        if isinstance(value, str):
            super().__setattr__(name, value.casefold())
        else:
            super().__setattr__(name, value)


class Settings:
    def __init__(self):
        self.game = Game()
        self.rq_game = Game()
        self.teams = Teams()

        self.sent_commands = []
        self.waiting_for_locraw = True
        self.adding_stats_in_tab = False

        self.autoboops = []
        self.add_join_stats = True
        self.stats_in_tab = True

        self.patterns = {
            # waiting_for_locraw
            "wflp": re.compile("^{.*}$"),
            # autoboop
            "abp": re.compile(r"^Friend >.* joined\."),
            # join lobby queue
            "lq": re.compile(r"^.*has joined (.*)!$"),
        }

        self.checks = {
            "autoboop": (lambda x: bool(self.patterns["abp"].match(x)), self.autoboop),
            "waiting_for_locraw": (
                lambda x: bool(self.patterns["wflp"].match(x)),
                self.update_game_from_locraw,
            ),
            "join_queue": (
                lambda x: bool(self.patterns["lq"].match(x)),
                self.add_stats,
            ),
        }

    def autoboop(self, bridge, buff: Buffer1_7, join_message):
        buff.restore()
        bridge.downstream.send_packet("chat_message", buff.read())

        # wait for a second for player to join
        time.sleep(0.1)

        if (player := str(join_message.split()[2]).lower()) in self.autoboops:
            bridge.upstream.send_chat(f"/boop {player}")

    def update_game_from_locraw(
        self, bridge: type[Bridge], buff: Buffer1_7, chat_message
    ):
        if self.waiting_for_locraw:
            if "limbo" in chat_message:
                return bridge.update_game(buff, self.locraw_retry + 1)

            game: dict = json.loads(chat_message)
            self.game.server = game.get("server")
            self.game.gametype = game.get("gametype")
            self.game.mode = game.get("mode")
            self.game.map = game.get("map")
            self.game.lobbyname = game.get("lobbyname")

            if (
                self.game.gametype == "bedwars"
                and "§7v1.8" in self.teams["team_3"].prefix
            ):
                self.game.pregame = True
            # TODO add more gamemode pregame checks

            if not self.game.mode:
                # not pregame; remove stats from tab
                self.game.pregame = False
                for team in self.teams:
                    if "proxhyqs" in team.name:
                        team.delete()
                        del self.teams[team.name]

            if self.game.mode:
                self.rq_game = dataclasses.replace(self.game)

            self.waiting_for_locraw = False
        else:
            buff.restore()
            bridge.downstream.send_packet("chat_message", buff.read())

    def add_stats(self, *args, **kwargs):
        self.add_stats_to_join(*args, **kwargs)
        self.add_stats_in_tab(*args, **kwargs)

    def add_stats_to_join(self, bridge, buff: Buffer1_7, join_message: str):
        if not self.add_join_stats:
            return

        ign = join_message.split(" ")[0]
        nump1, nump2 = re.findall(r"\((\d+)/(\d+)\)", join_message)[0]
        player = bridge.client.player(ign)
        if isinstance(player, InvalidApiKey):
            buff.restore()
            bridge.downstream.send_packet("chat_message", buff.read())
            bridge.downstream.send_packet(
                "chat_message", pack_chat("§4Invalid API Key!", 2)
            )
            return
        elif isinstance(player, RateLimitError):
            buff.restore()
            bridge.downstream.send_packet("chat_message", buff.read())
            bridge.downstream.send_packet(
                "chat_message", pack_chat("§4Your API key has been rate limited!", 2)
            )
            return
        elif isinstance(player, PlayerNotFound):
            rc = next(  # preserve rank color
                (t.prefix for t in bridge.settings.teams if ign in t.players), "§f"
            )
            stats_join_message = (
                f"§5[NICK] {rc}{ign} §ehas joined (§b{nump1}§e/§b{nump2}§e)!"
            )
            return bridge.downstream.send_chat(stats_join_message)
        elif isinstance(player, HypixelException):
            buff.restore()
            bridge.downstream.send_packet("chat_message", buff.read())
            return

        while self.waiting_for_locraw:
            time.sleep(0.01)
        self.game.pregame = True

        if self.game.gametype == "bedwars":
            fplayer = FormattedPlayer(player)
            stats_join_message = (
                f"{fplayer.bedwars.level} {fplayer.bedwars.fkdr} {fplayer.rankname} "
                + f"§ehas joined (§b{nump1}§e/§b{nump2}§e)!"
            )
            bridge.downstream.send_chat(stats_join_message)
            return
        elif self.game.gametype == "skywars":
            fplayer = FormattedPlayer(player)
            stats_join_message = (
                f"{fplayer.skywars.level} {fplayer.skywars.kdr} {fplayer.rankname} "
                + f"§ehas joined (§b{nump1}§e/§b{nump2}§e)!"
            )
            bridge.downstream.send_chat(stats_join_message)
            return

        buff.restore()
        bridge.downstream.send_packet("chat_message", buff.read())

    def add_stats_in_tab(self, bridge, buff: Buffer1_7, _):
        if not self.stats_in_tab or not self.game.pregame:
            return

        for _ in range(30):
            # wait a little for other stats to be added
            # only do 30 times so program exits properly
            if not self.adding_stats_in_tab:
                break
            time.sleep(0.1)

        self.adding_stats_in_tab = True
        # team names in pregame are rank colors
        teams_players: dict = {}
        for color_code_team in ("§a", "§b", "§6", "§c", "§2", "§c", "§d", "§7"):
            if team := self.teams[color_code_team]:
                teams_players[color_code_team] = team.players.copy()

        players_in_queue = set()
        for team in teams_players.values():
            players_in_queue.update(team)

        players = [player for player in bridge.client.players(*players_in_queue)]
        for player in players:
            if isinstance(player, PlayerNotFound):
                continue
            elif isinstance(player, InvalidApiKey):
                return bridge.downstream.send_packet(
                    "chat_message", pack_chat("§4Invalid API Key!", 2)
                )
            elif isinstance(player, RateLimitError):
                return bridge.downstream.send_packet(
                    "chat_message",
                    pack_chat("§4Your API key has been rate limited!", 2),
                )
            elif isinstance(player, HypixelException):
                return

            fplayer = FormattedPlayer(player)

            # hash player name to (potentially?) identify later;
            # also makes shorter for team name char limit
            playername_hash = hash(fplayer.raw_name)
            random.seed(playername_hash)
            not_number_hash = "".join(
                random.choice(string.ascii_letters) for _ in range(6)
            )
            prefix = f"{fplayer.bedwars.level} {fplayer.rank_color}"
            if len(prefix) > 16:
                continue
            team = Team(
                # proxhy queuestats
                f"proxhyqs{not_number_hash}",
                "",
                f"{fplayer.bedwars.level} {fplayer.rank_color}",
                f"§f | {fplayer.bedwars.fkdr}",
                friendly_fire=3,
                name_tag_visibility="always",
                color=15,
                players=set((fplayer.raw_name,)),
                bridge=bridge,
            )
            team.create()
            self.teams.append(team)

        nicks = players_in_queue - {
            player.name for player in players if not isinstance(player, PlayerNotFound)
        }
        if self.teams["proxhyqsnicks"]:
            nick_team = self.teams["proxhyqsnicks"]
            nick_team.update(*nicks)
        else:
            nick_team = Team(
                "proxhyqsnicks",
                "",
                f"§5[NICK] ",
                "",
                friendly_fire=3,
                name_tag_visibility="always",
                color=15,
                players=nicks,
                bridge=bridge,
            )
            nick_team.create()
            self.teams.append(nick_team)

        self.adding_stats_in_tab = False
