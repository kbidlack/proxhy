from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Optional, Literal


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

    def __eq__(self, other: object):
        if not isinstance(other, Team):
            raise TypeError("Comparisons must be between two Team objects")

        return self.name == other.name


class Teams(list[Team]):
    def get(self, key) -> Team:
        return next(team for team in self if team.name == key)

    def delete(self, key):
        team = self.get(key)
        if team:
            self.remove(team)


bw_maps_path = Path(__file__).parent.parent / "assets/bedwars_maps.json"

with bw_maps_path.open("r") as file:
    bw_maps: dict = json.load(file)
maps = []


@dataclass
class BedwarsMap:
    name: str
    rush_direction: Optional[Literal["side", "alt"]] = None
    max_height: Optional[int] = None
    min_height: Optional[int] = None

    @classmethod
    def get(cls, name: str) -> BedwarsMap:
        """Get any BedwarsMap obj from a map name"""
        name = name.lower()
        for m in maps:
            if m.name == name:
                return m
        if name not in bw_maps.keys():
            raise ValueError(f"Unknown map {name}.")
        map_dict: dict = bw_maps[name]
        new = BedwarsMap(
            name=name,
            rush_direction=map_dict.get("rush_direction"),
            max_height=map_dict.get("max_height"),
            min_height=map_dict.get("min_height"),
        )
        maps.append(new)
        return new

    def __eq__(self, other: object):
        if not isinstance(other, BedwarsMap):
            return NotImplemented  # i was gonna do False but apparently this is more correct
        return self.name == other.name


@dataclass
class Game:
    server: str = ""
    gametype: str = ""
    mode: str = ""
    map: Optional[BedwarsMap] = None
    lobbyname: str = ""
    started: bool = False

    def __setattr__(self, name: str, value) -> None:
        if isinstance(value, str):
            super().__setattr__(name.casefold(), value.casefold())
        else:
            super().__setattr__(name, value)

    def update(self, data: dict):
        # reset
        self.server = ""
        self.gametype = ""
        self.mode = ""
        self.map = None
        self.lobbyname = ""

        for key, value in data.items():
            if key != "map":
                setattr(self, key, value)
            else:
                self.map = BedwarsMap(name=value)


@dataclass
class Nick:
    name: str
    uuid: str = field(init=False)
