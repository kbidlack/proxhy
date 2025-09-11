import asyncio
from core.events import listen_server, listen_client
from core.plugin import Plugin
from proxhy.mcmodels import Game, Teams
from proxhy.settings import ProxhySettings
from protocol.datatypes import Buffer, Double, Chat, TextComponent
from plugins.statcheck import BW_MAPS
# from typing import TYPE_CHECKING


# if TYPE_CHECKING:
#     from protocol.datatypes import Color_T


class SpatialPlugin(Plugin):
    teams: Teams
    game: Game
    settings: ProxhySettings
    received_who: asyncio.Event
    username: str
    received_locraw: asyncio.Event

    def _init_spatial(self):
        self.position: tuple[float, float, float] | None = None

    # =========================
    #   TRACK PLAYER POSITION
    # =========================
    @listen_client(0x04)  # player position (for when look is unchanged)
    async def sb_read_player_pos(self, buff: Buffer):
        x = buff.unpack(Double)
        y = buff.unpack(Double)
        z = buff.unpack(Double)
        self.position = (x, y, z)

        # self.client.chat(f"Player Position: {x}, {y}, {z}")
        self.server.send_packet(0x04, buff.getvalue())
        self.updated_position()

    @listen_client(0x06)  # player look and position
    async def sb_read_player_pos_look(self, buff: Buffer):
        x = buff.unpack(Double)
        y = buff.unpack(Double)
        z = buff.unpack(Double)
        self.position = (x, y, z)

        self.server.send_packet(0x06, buff.getvalue())
        self.updated_position()

    @listen_server(0x08)
    async def cb_read_player_pos_look(self, buff: Buffer):
        x = buff.unpack(Double)
        y = buff.unpack(Double)
        z = buff.unpack(Double)
        self.position = (x, y, z)

        self.client.send_packet(0x08, buff.getvalue())
        self.updated_position()

    def updated_position(self):
        # display height limit warnings
        if (
            self.game.map  # we are in a game & not lobby
            and self.settings.bedwars.visual.height_limit_warnings.get() == "ON"
            and self.game.started
        ):
            # should never happen but makes type checker happy
            if self.position is None:
                return
            y = self.position[1]

            max_height: int = BW_MAPS[self.game.map]["max_height"] or 255
            min_height: int = BW_MAPS[self.game.map]["min_height"] or 0

            if not (min_height + 3 < y < max_height - 5):
                limit_dist = round(max(min(y - min_height, max_height - y), 0))
                color_mappings = {
                    0: "§4",
                    1: "§c",
                    2: "§6",
                    3: "§e",
                    4: "§a",
                    5: "§2",
                }
                self.actionbar_text(
                    f"§l{color_mappings[limit_dist]}{limit_dist} {'BLOCK' if limit_dist == 1 else 'BLOCKS'} §f§rfrom height limit!"
                )

    def actionbar_text(self, msg: str | TextComponent):
        self.client.send_packet(0x02, Chat.pack(msg) + b"\x02")
