import dataclasses
import json
import re
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
            "name", "display_name", "prefix", "suffix",
            "friendly_fire", "name_tag_visibility", "color"
        }

    def create(self):
        packet = b''.join((
            self.buff.pack_string(self.name),
            b'\x00', # mode
            self.buff.pack_string(self.display_name),
            self.buff.pack_string(self.prefix),
            self.buff.pack_string(self.suffix),
            self.friendly_fire.to_bytes(),
            self.buff.pack_string(self.name_tag_visibility),
            self.color.to_bytes(),
            self.buff.pack_varint(len(self.players)),
            *(self.buff.pack_string(player) for player in self.players)
        ))
        self.bridge.downstream.send_packet("teams", packet)

    def delete(self):
        packet = b''.join((
            self.buff.pack_string(self.name),
            b'\x01' # mode
        ))
        self.bridge.downstream.send_packet("teams", packet)

    def update(
            self, name: str = None, display_name: str = None,
            prefix: str = None, suffix: str = None, friendly_fire: int = None,
            name_tag_visibility: str = None, color: int = None
        ):
        self.name = name or self.name
        self.display_name = display_name or self.display_name
        self.prefix = prefix or self.prefix
        self.suffix = suffix or self.suffix
        self.friendly_fire = friendly_fire or self.friendly_fire
        self.name_tag_visibility = name_tag_visibility or self.name_tag_visibility
        self.color = color or self.color

        packet = b''.join((
            self.buff.pack_string(self.name),
            b'\x02', # mode
            self.buff.pack_string(self.display_name),
            self.buff.pack_string(self.prefix),
            self.buff.pack_string(self.suffix),
            self.friendly_fire.to_bytes(),
            self.buff.pack_string(self.name_tag_visibility),
            self.color.to_bytes()
        ))

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
                    pass # hehe
        
        packet = b''.join((
            self.buff.pack_string(self.name),
            b'\x03' if add else b'\x04', # mode
            self.buff.pack_varint(len(new_players)),
            *(self.buff.pack_string(player) for player in new_players)
        ))

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
            super().__setattr__(name, value.lower())


class Settings:
    def __init__(self):
        self.game = Game()
        self.rq_game = Game()
        self.teams = Teams()

        self.sent_commands = []
        self.waiting_for_locraw = True

        self.autoboops = []
        self.add_join_stats = True

        self.patterns = {
            # waiting_for_locraw
            "wflp": re.compile("^{.*}$"),
            # autoboop
            "abp": re.compile(r"^Friend >.* joined\."),
            # join lobby queue
            "lq": re.compile(r"^.*has joined (.*)!$")
        }

        self.checks = {
            "autoboop": (
                lambda x: bool(self.patterns["abp"].match(x)),
                self.autoboop
            ),
            "waiting_for_locraw": (
                lambda x: bool(self.patterns["wflp"].match(x)),
                self.update_game_from_locraw
            ),
            "join_queue": (
                lambda x: bool(self.patterns["lq"].match(x)),
                self.add_stats_to_join
            )
        }


    def autoboop(self, bridge, buff: Buffer1_7, join_message):
        buff.restore()
        bridge.downstream.send_packet("chat_message", buff.read())

        # wait for a second for player to join
        time.sleep(0.1)

        if (player := str(join_message.split()[2]).lower()) in self.autoboops:
            bridge.upstream.send_chat(f"/boop {player}")
    
    def update_game_from_locraw(
        self,
        bridge: type[Bridge],
        buff: Buffer1_7,
        chat_message
    ):
        if self.waiting_for_locraw:
            if 'limbo' in chat_message:
                return bridge.update_game(buff, self.locraw_retry + 1)

            game: dict = json.loads(chat_message)
            bridge.settings.game.server = game.get("server")
            bridge.settings.game.gametype = game.get("gametype")
            bridge.settings.game.mode = game.get("mode")
            bridge.settings.game.map = game.get("map")
            bridge.settings.game.lobbyname = game.get("lobbyname")

            # TODO determine if pregame

            if bridge.settings.game.mode:
                bridge.settings.rq_game = dataclasses.replace(
                    bridge.settings.game
                )

            self.waiting_for_locraw = False
        else:
            buff.restore()
            bridge.downstream.send_packet("chat_message", buff.read())

    def add_stats_to_join(self, bridge, buff: Buffer1_7, join_message: str):
        if not self.add_join_stats:
            return

        ign = join_message.split(' ')[0]
        nump1, nump2 = re.findall(r'\((\d+)/(\d+)\)', join_message)[0]

        player = bridge.client.player(ign)
        if isinstance(player, InvalidApiKey):
            buff.restore()
            bridge.downstream.send_packet("chat_message", buff.read())
            return bridge.downstream.send_packet(
                "chat_message",
                pack_chat("§4Invalid API Key!", 2)
            )
        elif isinstance(player, RateLimitError):
            buff.restore()
            bridge.downstream.send_packet("chat_message", buff.read())
            return bridge.downstream.send_packet(
                "chat_message",
                pack_chat("§4Your API key has been rate limited; please wait")
            )
        elif isinstance(player, PlayerNotFound):
            rc = next( # preserve rank color
                (t.prefix for t in bridge.settings.teams if ign in t.players), "§f"
            )
            stats_join_message = (
                f"§5[NICK] {rc}{ign} §ehas joined (§b{nump1}§e/§b{nump2}§e)!"
            )
            return bridge.downstream.send_chat(stats_join_message)
        elif isinstance(player, HypixelException):
            buff.restore()
            return bridge.downstream.send_packet("chat_message", buff.read())

        while self.waiting_for_locraw:
            time.sleep(0.01) 

        if self.game.gametype == "bedwars":
            fplayer = FormattedPlayer(player)
            stats_join_message = (
                f"{fplayer.bedwars.level} {fplayer.bedwars.fkdr} {fplayer.rankname} "
                + f"§ehas joined (§b{nump1}§e/§b{nump2}§e)!"
            )
            return bridge.downstream.send_chat(stats_join_message)
        elif self.game.gametype == "skywars":
            fplayer = FormattedPlayer(player)
            stats_join_message = (
                f"{fplayer.skywars.level} {fplayer.skywars.kdr} {fplayer.rankname} "
                + f"§ehas joined (§b{nump1}§e/§b{nump2}§e)!"
            )
            return bridge.downstream.send_chat(stats_join_message)

        buff.restore()
        bridge.downstream.send_packet("chat_message", buff.read())
