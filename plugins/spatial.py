import asyncio

import numpy as np

from core.events import listen_client, listen_server, subscribe
from core.plugin import Plugin
from protocol.datatypes import (
    Boolean,
    Buffer,
    Double,
    Float,
    Int,
)
from proxhy.mcmodels import Game, Teams
from proxhy.settings import ProxhySettings


class SpatialPlugin(Plugin):
    teams: Teams
    game: Game
    settings: ProxhySettings
    received_who: asyncio.Event
    username: str
    received_locraw: asyncio.Event

    def _init_spatial(self):
        self.check_height_task = None
        self.position: tuple[float, float, float] | None = None

    @subscribe("login_sucess")
    async def _spatial_on_login_success(self, _):
        self.check_height_task = asyncio.create_task(self.check_height_loop())

    @subscribe("close")
    async def _close_spatial(self, _):
        if self.check_height_task:
            self.check_height_task.cancel()
            try:
                await self.check_height_task
            except asyncio.CancelledError:
                pass

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

    @listen_client(0x06)  # player look and position
    async def sb_read_player_pos_look(self, buff: Buffer):
        x = buff.unpack(Double)
        y = buff.unpack(Double)
        z = buff.unpack(Double)
        self.position = (x, y, z)

        self.server.send_packet(0x06, buff.getvalue())

    @listen_server(0x08)
    async def cb_read_player_pos_look(self, buff: Buffer):
        x = buff.unpack(Double)
        y = buff.unpack(Double)
        z = buff.unpack(Double)
        self.position = (x, y, z)

        self.client.send_packet(0x08, buff.getvalue())

    async def check_height_loop(self):
        """Called once when the proxy is started; loops indefinitely"""
        while True:
            if (
                self.game.map is not None  # we are in a game & not lobby
                and self.settings.bedwars.visual.height_limit_warnings.get() == "ON"
                and self.game.started
            ):
                await self.height_limit_warnings()

            await asyncio.sleep(1 / 20)

    async def height_limit_warnings(self):
        """Display warnings when the player is near the height limit"""
        # should never happen but makes type checker happy
        if self.position is None or self.game.map is None:
            return
        y = self.position[1]
        max_height: int = self.game.map.max_height or 255
        min_height: int = self.game.map.max_height or 0

        if abs(min_height - y) <= 3 or abs(max_height - y) <= 5:
            limit_dist = round(max(min(abs(y - min_height), abs(max_height - y)), 0))
            color_mappings = {0: "§4", 1: "§c", 2: "§6", 3: "§e", 4: "§a", 5: "§2"}
            self.client.set_actionbar_text(
                f"§l{color_mappings[limit_dist]}{limit_dist} {'BLOCK' if limit_dist == 1 else 'BLOCKS'} §f§rfrom height limit!"
            )
            particle_y = (  # whichever height limit the player is closest to
                max_height
                if abs(max_height - self.position[1])
                < abs(min_height - self.position[1])
                else min_height
            )
            for _ in range(10):
                particle_x = self.position[0] + np.random.normal(0, 0.7) * 3
                particle_z = self.position[2] + np.random.normal(0, 0.7) * 3
                self.display_particle(
                    particle_id=30, pos=(particle_x, particle_y, particle_z)
                )

    def display_particle(
        self,
        particle_id: int,
        pos: tuple[float, float, float],
        offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
        particle_data=0.0,
        count=1,
        data: int = 0,
    ):
        if data != 0:
            raise NotImplementedError(
                "Data field is 0 for most particles. ironcrack, blockcrack, and blockdust not implemented."
            )
        self.client.send_packet(
            0x2A,  # display particle
            Int(particle_id),  # particle id
            Boolean(True),  # long distance?
            Float(pos[0]),  # xyz particle coords
            Float(pos[1]),
            Float(pos[2]),
            Float(offset[0]),  # xyz particle offset
            Float(offset[1]),
            Float(offset[2]),
            Float(particle_data),
            Int(count),  # num of particles
            # VarInt.pack(data),  # array of VarInt; most particles have length 0
        )
