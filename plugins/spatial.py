import asyncio
import time
import numpy as np
from core.events import listen_server, listen_client, subscribe
from core.plugin import Plugin
from proxhy.mcmodels import Game, Teams
from .command import command
from proxhy.settings import ProxhySettings
from protocol.datatypes import (
    Buffer,
    Double,
    Chat,
    TextComponent,
    Boolean,
    Float,
    Int,
)
from plugins.statcheck import BW_MAPS


class SpatialPlugin(Plugin):
    teams: Teams
    game: Game
    settings: ProxhySettings
    received_who: asyncio.Event
    username: str
    received_locraw: asyncio.Event

    def _init_spatial(self):
        self.position: tuple[float, float, float] | None = None
        self.check_height_task = asyncio.create_task(self.check_height_loop())

    @subscribe("close")
    async def _close_spatial(self, _):
        self.check_height_task.cancel()

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
                self.game.map  # we are in a game & not lobby
                and self.settings.bedwars.visual.height_limit_warnings.get() == "ON"
                and self.game.started
            ):
                await self.height_limit_warnings()

            await asyncio.sleep(1 / 20)

    async def height_limit_warnings(self):
        """Display warnings when the player is near the height limit"""
        # should never happen but makes type checker happy
        if self.position is None:
            return
        y = self.position[1]
        max_height: int = BW_MAPS[self.game.map]["max_height"] or 255
        min_height: int = BW_MAPS[self.game.map]["min_height"] or 0

        if abs(min_height - y) <= 3 or abs(max_height - y) <= 5:
            limit_dist = round(max(min(y - min_height, max_height - y), 0))
            color_mappings = {0: "§4", 1: "§c", 2: "§6", 3: "§e", 4: "§a", 5: "§2"}
            self.actionbar_text(
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

    def actionbar_text(self, msg: str | TextComponent):
        self.client.send_packet(0x02, Chat.pack(msg) + b"\x02")

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

    @command("ptest")
    async def spawn_redstone_particle(self):
        if self.position is None:
            return
        height_loop_tasks = [
            t
            for t in asyncio.all_tasks()
            if t.get_coro().__name__ == self.check_height_loop.__name__
        ]
        self.client.chat(
            f"{str(height_loop_tasks)}\nTotal tasks: {len(height_loop_tasks)}"
        )
        self.display_particle(particle_id=30, pos=self.position)
