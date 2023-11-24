from dataclasses import dataclass

from quarry.net.proxy import Bridge
from quarry.types.buffer import Buffer1_7


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
