from dataclasses import dataclass
from typing import Literal, Optional

from assets import load_json_asset
from proxhy.argtypes.hypixel import GAMETYPE_T


@dataclass
class BedwarsMap:
    name: str
    rush_direction: Optional[Literal["side", "alt"]] = None
    max_height: Optional[int] = None
    min_height: Optional[int] = None

    def __eq__(self, other: object):
        if not isinstance(other, BedwarsMap):
            return NotImplemented
        return self.name == other.name


_MAPS: dict[str, BedwarsMap] = {}


def _load_bedwars_maps():
    bw_maps_data: dict = load_json_asset("bedwars_maps.json")

    for map_name, map_data in bw_maps_data.items():
        _MAPS[map_name] = BedwarsMap(
            name=map_name,
            rush_direction=map_data.get("rush_direction"),
            max_height=map_data.get("max_height"),
            min_height=map_data.get("min_height"),
        )


_load_bedwars_maps()


@dataclass
class Game:
    server: str = ""
    gametype: GAMETYPE_T | Literal[""] = ""
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
                self.map = _MAPS.get(value.lower())
