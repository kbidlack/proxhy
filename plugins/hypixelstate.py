import asyncio
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Literal, Optional

from core.events import listen_client, listen_server, subscribe
from protocol.datatypes import Buffer, ByteArray, Chat, Int, String
from proxhy.plugin import ProxhyPlugin


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
    bw_maps_path = files("proxhy").joinpath("assets/bedwars_maps.json")

    with bw_maps_path.open("r") as file:
        bw_maps_data: dict = json.load(file)

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
                self.map = _MAPS.get(value.lower())


class HypixelStatePluginState:
    client_type: str
    game: Game
    rq_game: Game
    received_locraw: asyncio.Event
    received_who: asyncio.Event
    entity_id: int


class HypixelStatePlugin(ProxhyPlugin):
    def _init_hypixelstate(self):
        self.client_type = ""

        self.game = Game()
        self.rq_game = Game()

        self.received_locraw = asyncio.Event()
        self.received_locraw.set()

        self.received_who = asyncio.Event()
        self.received_who.set()

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, buff: Buffer):
        self.entity_id = buff.unpack(Int)
        self.received_locraw.clear()

        if not self.client_type == "lunar":
            self.server.send_packet(0x01, String("/locraw"))

    def _update_game(self, game: dict):
        self.game.update(game)
        if game.get("mode"):
            return self.rq_game.update(game)
        else:
            return

    @subscribe(r"chat:server:\{.*\}$")
    async def _hypixelstate_event_chat_server_locraw(self, buff: Buffer):
        message = buff.unpack(Chat)

        if not self.received_locraw.is_set():
            if "limbo" in message:  # sometimes returns limbo right when you join
                if not self.gamestate.teams.values():  # probably in limbo
                    return
                elif self.client_type != "lunar":
                    await asyncio.sleep(0.1)
                    return self.server.send_packet(0x01, String("/locraw"))
            else:
                self.received_locraw.set()
                self._update_game(json.loads(message))
        else:
            self.client.send_packet(0x02, buff.getvalue())
            self._update_game(json.loads(message))

    @listen_client(0x17)
    async def packet_plugin_channel(self, buff: Buffer):
        self.server.send_packet(0x17, buff.getvalue())

        channel = buff.unpack(String)
        data = buff.unpack(ByteArray)
        if channel == "MC|Brand":
            if b"lunarclient" in data:
                self.client_type = "lunar"
            elif b"vanilla" in data:
                self.client_type = "vanilla"
