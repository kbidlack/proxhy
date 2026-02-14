import asyncio

import numba
import numpy as np

from core.events import subscribe
from protocol.datatypes import (
    Boolean,
    Float,
    Int,
)
from proxhy.plugin import ProxhyPlugin


@numba.njit(cache=True, fastmath=True)
def _compute_height_warning(
    y: float, min_height: int, max_height: int
) -> tuple[bool, int, float]:
    """Compute height warning data. Returns (should_warn, limit_dist, particle_y)."""
    near_min = abs(min_height - y) <= 3
    near_max = abs(max_height - y) <= 5
    if not (near_min or near_max):
        return False, 0, 0.0

    dist_to_min = abs(y - min_height)
    dist_to_max = abs(max_height - y)
    limit_dist = round(max(min(dist_to_min, dist_to_max), 0))
    particle_y = max_height if dist_to_max < dist_to_min else min_height
    return True, limit_dist, float(particle_y)


class SpatialPlugin(ProxhyPlugin):
    @subscribe("login_success")
    async def _spatial_event_login_success(self, _match, _data):
        self.create_task(self.check_height_loop())

    async def check_height_loop(self):
        """Called once when the proxy is started; loops indefinitely"""
        while True:
            if (
                self.game.map is not None  # we are in a game & not lobby
                and self.settings.bedwars.visual.height_limit_warnings.get() == "ON"
                and self.game.started
            ):
                self.height_limit_warnings()

            await asyncio.sleep(1 / 20)

    def height_limit_warnings(self):
        """Display warnings when the player is near the height limit"""
        # should never happen but makes type checker happy
        if self.game.map is None:
            return
        y = self.gamestate.position.y
        max_height: int = self.game.map.max_height or 255
        min_height: int = self.game.map.min_height or 0

        should_warn, limit_dist, particle_y = _compute_height_warning(
            y, min_height, max_height
        )
        if not should_warn:
            return

        color_mappings = {0: "§4", 1: "§c", 2: "§6", 3: "§e", 4: "§a", 5: "§2"}
        self.client.set_actionbar_text(
            f"§l{color_mappings[limit_dist]}{limit_dist} {'BLOCK' if limit_dist == 1 else 'BLOCKS'} §f§rfrom height limit!"
        )
        for _ in range(10):
            particle_x = self.gamestate.position.x + np.random.normal(0, 0.7) * 3
            particle_z = self.gamestate.position.z + np.random.normal(0, 0.7) * 3
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
