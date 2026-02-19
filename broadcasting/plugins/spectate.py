import asyncio
import math
import random
from typing import Callable, Literal, Optional, TypedDict

import hypixel
import numba
import numpy as np
from numpy.typing import NDArray

from broadcasting.plugin import BroadcastPeerPlugin
from core.events import listen_client as listen
from core.events import subscribe
from gamestate.state import Entity, Player, PlayerAbilityFlags, Rotation, Vec3d
from plugins.commands import CommandException, command
from plugins.window import Window
from protocol import nbt
from protocol.datatypes import (
    Angle,
    Boolean,
    Buffer,
    Byte,
    Double,
    Float,
    Int,
    Item,
    Short,
    Slot,
    SlotData,
    TextComponent,
    UnsignedByte,
    VarInt,
)
from proxhy.argtypes import ServerPlayer
from proxhy.utils import uuid_version
from proxhypixel.formatting import (
    SUPPORTED_MODES,
    format_player_dict,
    get_rankname,
)

# camera candidates: 8 azimuths x 4 elevations x 2 radii = 64 positions
# elevations: 45°, 35°, 25°, 15° from horizontal
_CANDIDATES = np.array(
    [
        (
            r * math.cos(el) * math.cos(az),
            r * math.sin(el),
            r * math.cos(el) * math.sin(az),
            ri * 10 + ei,
        )
        for ri, r in enumerate((6.0, 8.0))
        for ei, el in enumerate((0.785, 0.611, 0.436, 0.262))
        for az in np.linspace(0, 2 * math.pi, 8, endpoint=False)
    ],
    dtype=np.float64,
)

# body visibility check points: (dy_offset, is_critical)
_BODY_OFFSETS = np.array([(1.62, 1), (0.0, 1), (0.9, 0), (-0.9, 0)], dtype=np.float64)


@numba.njit(cache=True, fastmath=True)
def _ray_blocked(
    bitmask: NDArray[np.uint8],
    x0: float,
    y0: float,
    z0: float,
    x1: float,
    y1: float,
    z1: float,
) -> bool:
    """3D DDA raycast returning True if ray hits solid block."""
    size = bitmask.shape[0]
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0

    if abs(dx) < 1e-6 and abs(dy) < 1e-6 and abs(dz) < 1e-6:
        ix, iy, iz = int(x0), int(y0), int(z0)
        return (
            0 <= ix < size
            and 0 <= iy < size
            and 0 <= iz < size
            and bitmask[ix, iy, iz] != 0
        )

    x, y, z = int(math.floor(x0)), int(math.floor(y0)), int(math.floor(z0))
    ex, ey, ez = int(math.floor(x1)), int(math.floor(y1)), int(math.floor(z1))
    sx = 1 if dx > 0 else -1 if dx < 0 else 0
    sy = 1 if dy > 0 else -1 if dy < 0 else 0
    sz = 1 if dz > 0 else -1 if dz < 0 else 0

    INF = 1e30
    tmx = ((x + (sx > 0)) - x0) / dx if abs(dx) > 1e-10 else INF
    tmy = ((y + (sy > 0)) - y0) / dy if abs(dy) > 1e-10 else INF
    tmz = ((z + (sz > 0)) - z0) / dz if abs(dz) > 1e-10 else INF
    tdx = abs(1.0 / dx) if abs(dx) > 1e-10 else INF
    tdy = abs(1.0 / dy) if abs(dy) > 1e-10 else INF
    tdz = abs(1.0 / dz) if abs(dz) > 1e-10 else INF

    for _ in range(abs(ex - x) + abs(ey - y) + abs(ez - z) + 2):
        if 0 <= x < size and 0 <= y < size and 0 <= z < size and bitmask[x, y, z] != 0:
            return True
        if x == ex and y == ey and z == ez:
            break
        if tmx <= tmy and tmx <= tmz:
            tmx, x = tmx + tdx, x + sx
        elif tmy <= tmz:
            tmy, y = tmy + tdy, y + sy
        else:
            tmz, z = tmz + tdz, z + sz
    return False


@numba.njit(cache=True, fastmath=True)
def _find_camera_offset(
    bitmask: NDArray[np.uint8],
    others: NDArray[np.float64],
    candidates: NDArray[np.float64],
    body_offsets: NDArray[np.float64],
    look_x: float,
    look_z: float,
    speed: float,
) -> tuple[float, float, float]:
    """Find optimal camera offset behind player with clear sightlines."""
    c = float((bitmask.shape[0] - 1) // 2)  # center of bitmask
    speed_factor = min(speed / 0.28, 1.5)
    best, fallback = (0.0, 0.0, 0.0, 1e9), (0.0, 0.0, 0.0, 1e9)

    for i in range(candidates.shape[0]):
        ox, oy, oz, pref = (
            candidates[i, 0],
            candidates[i, 1],
            candidates[i, 2],
            candidates[i, 3],
        )
        cx, cy, cz = c + ox, c + oy, c + oz

        # Check body visibility (critical points block candidate entirely)
        crit_blocked, blocked = False, 0
        for j in range(body_offsets.shape[0]):
            if _ray_blocked(bitmask, cx, cy, cz, c, c + body_offsets[j, 0], c):
                if body_offsets[j, 1] > 0.5:
                    crit_blocked = True
                    break
                blocked += 1

        # Prefer camera behind player (penalize positions in front)
        cam_len = math.sqrt(ox * ox + oz * oz)
        dir_penalty = (
            ((ox * look_x + oz * look_z) / cam_len + 1.0) * 50.0
            if cam_len > 0.01
            else 50.0
        )

        # Prefer lower angles, especially when moving
        elev_penalty = max(0.0, oy - 1.5) * (10.0 + 20.0 * speed_factor)

        score = blocked * 50.0 + dir_penalty + elev_penalty + pref * 0.01

        # Penalize blocked combat targets
        for j in range(others.shape[0]):
            if _ray_blocked(
                bitmask,
                cx,
                cy,
                cz,
                c + others[j, 0],
                c + others[j, 1],
                c + others[j, 2],
            ):
                score += 20.0

        if crit_blocked:
            if score + 500.0 < fallback[3]:
                fallback = (ox, oy, oz, score + 500.0)
        elif score < best[3]:
            best = (ox, oy, oz, score)

    if best[3] < 1e9:
        return (best[0], best[1], best[2])
    if fallback[3] < 1e9:
        return (fallback[0], fallback[1], fallback[2])
    return (4.0, 4.0, 0.0)


@numba.njit(cache=True, fastmath=True)
def _interp_spherical(
    cur_x: float,
    cur_y: float,
    cur_z: float,
    tgt_x: float,
    tgt_y: float,
    tgt_z: float,
    bitmask: NDArray[np.uint8],
    stuck: int,
    t: float,
) -> tuple[float, float, float, int]:
    """Interpolate camera along sphere surface to keep player in frame."""
    c = float((bitmask.shape[0] - 1) // 2)

    # Convert to spherical (radius, azimuth, elevation)
    cr = math.sqrt(cur_x * cur_x + cur_y * cur_y + cur_z * cur_z)
    tr = math.sqrt(tgt_x * tgt_x + tgt_y * tgt_y + tgt_z * tgt_z)
    if cr < 0.1:
        cr = 6.0
    if tr < 0.1:
        tr = 6.0

    caz, taz = math.atan2(cur_z, cur_x), math.atan2(tgt_z, tgt_x)
    cel = math.asin(max(-0.99, min(0.99, cur_y / cr)))
    tel = math.asin(max(-0.99, min(0.99, tgt_y / tr)))

    # Shortest azimuth path
    adiff = taz - caz
    if adiff > math.pi:
        adiff -= 2 * math.pi
    elif adiff < -math.pi:
        adiff += 2 * math.pi

    # Interpolate spherical coords
    naz = caz + adiff * t
    nel = cel + (tel - cel) * t
    nr = cr + (tr - cr) * t

    # Convert to cartesian
    ce, se, ca, sa = math.cos(nel), math.sin(nel), math.cos(naz), math.sin(naz)
    nx, ny, nz = nr * ce * ca, nr * se, nr * ce * sa

    if not _ray_blocked(bitmask, nx + c, ny + c, nz + c, c, c, c):
        return (nx, ny, nz, 0)

    # Try larger radii if blocked
    for bonus in (1.0, 2.0, 3.0, 4.0):
        r = nr + bonus
        ox, oy, oz = r * ce * ca, r * se, r * ce * sa
        if not _ray_blocked(bitmask, ox + c, oy + c, oz + c, c, c, c):
            return (ox, oy, oz, 0)

    # Force move if stuck
    if stuck >= 3:
        ft = min(t * 2.0, 0.3)
        naz2 = caz + adiff * ft
        nel2 = cel + (tel - cel) * ft
        nr2 = cr + (tr - cr) * ft
        ce2, se2, ca2, sa2 = (
            math.cos(nel2),
            math.sin(nel2),
            math.cos(naz2),
            math.sin(naz2),
        )
        return (nr2 * ce2 * ca2, nr2 * se2, nr2 * ce2 * sa2, 0)

    return (cur_x, cur_y, cur_z, stuck + 1)


class BroadcastPeerSpectatePluginState:
    flight_speed: int | float
    _send_abilities: Callable


class BroadcastPeerSpectatePlugin(BroadcastPeerPlugin):
    def _init_broadcast_peer_spectate(self):
        self.watching = False
        self._cam: Vec3d | None = None  # camera offset from player
        self._cam_stuck = 0
        self._rot: tuple[float, float] | None = None  # smoothed (yaw, pitch)
        self._last_pos: Vec3d | None = None

    @listen(0x0B)
    async def packet_entity_action(self, buff: Buffer):
        if buff.unpack(VarInt) != self.eid:
            return
        if buff.unpack(VarInt) == 0 and self.spec_eid is not None:
            self._reset_spec()

    async def _update_spec_task(self):
        while self.open:
            if self.spec_eid is None:
                await asyncio.sleep(0.05)
                continue

            pos = rot = None
            if self.spec_eid == self.proxy._transformer.player_eid:
                pos, rot = self.proxy.gamestate.position, self.proxy.gamestate.rotation
                self.client.send_packet(*self.proxy.gamestate._build_player_inventory())
                self.client.send_packet(
                    0x2F, Byte.pack(-1), Short.pack(-1), Slot.pack(SlotData())
                )
            elif entity := self.proxy.gamestate.get_entity(self.spec_eid):
                pos, rot = entity.position, entity.rotation
                eq = entity.equipment
                for slot, item in [
                    (36, eq.held),
                    (5, eq.helmet),
                    (6, eq.chestplate),
                    (7, eq.leggings),
                    (8, eq.boots),
                ]:
                    self._set_slot(slot, item)

            if pos and rot:
                self.client.send_packet(
                    0x08,
                    Double.pack(pos.x),
                    Double.pack(pos.y),
                    Double.pack(pos.z),
                    Float.pack(rot.yaw),
                    Float.pack(rot.pitch),
                    Byte.pack(0),
                )
            await asyncio.sleep(0.05)

    @subscribe("login_success")
    async def _broadcast_peer_base_event_login_success(self, _match, _data):
        self.create_task(self._update_spec_task())
        self.create_task(self._update_watch())
        self.create_task(self._check_position())

    def _get_camera(self) -> tuple[Vec3d, Rotation]:
        """Calculate camera position and rotation for watch mode."""
        pos = self.proxy.gamestate.position
        rot = self.proxy.gamestate.rotation
        bitmask = self.proxy.gamestate.get_block_bitmask(pos, radius=8)

        # Combat targets as offsets from player
        others = (
            np.array(
                [
                    (e.position.x - pos.x, e.position.y - pos.y, e.position.z - pos.z)
                    for e in self.proxy.ein_combat_with
                ],
                dtype=np.float64,
            )
            if self.proxy.ein_combat_with
            else np.empty((0, 3), dtype=np.float64)
        )

        # Player look direction and movement speed
        yaw_rad = -rot.yaw * math.pi / 180
        look_x, look_z = math.sin(yaw_rad), math.cos(yaw_rad)
        speed = (
            math.sqrt((pos.x - self._last_pos.x) ** 2 + (pos.z - self._last_pos.z) ** 2)
            if self._last_pos
            else 0.0
        )
        self._last_pos = pos

        # Find target camera offset and interpolate
        tgt = _find_camera_offset(
            bitmask, others, _CANDIDATES, _BODY_OFFSETS, look_x, look_z, speed
        )
        interp_t = 0.12 + min(speed / 0.28, 1.0) * 0.18

        if self._cam is None:
            self._cam = Vec3d(*tgt)
        else:
            *new, self._cam_stuck = _interp_spherical(
                self._cam.x,
                self._cam.y,
                self._cam.z,
                tgt[0],
                tgt[1],
                tgt[2],
                bitmask,
                self._cam_stuck,
                interp_t,
            )
            self._cam = Vec3d(*new)

        cam_pos = pos + self._cam
        focus = pos + Vec3d(0, 1.62, 0)

        # Look target: weighted blend of player, look-ahead, and combat targets
        pitch_rad = -rot.pitch * math.pi / 180
        cos_p = math.cos(pitch_rad)
        look_ahead = Vec3d(
            focus.x + look_x * cos_p * 5,
            focus.y + math.sin(pitch_rad) * 5,
            focus.z + look_z * cos_p * 5,
        )

        targets = [focus, look_ahead] + [e.position for e in self.proxy.ein_combat_with]
        weights = [2.0, 1.0] + [1.0] * len(self.proxy.ein_combat_with)
        tw = sum(weights)
        lx = sum(w * t.x for w, t in zip(weights, targets)) / tw
        ly = sum(w * t.y for w, t in zip(weights, targets)) / tw
        lz = sum(w * t.z for w, t in zip(weights, targets)) / tw

        # Compute rotation to look target
        dx, dy, dz = lx - cam_pos.x, ly - cam_pos.y, lz - cam_pos.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        tgt_yaw = (-math.atan2(dx, dz) * 180 / math.pi) % 360
        tgt_pitch = -math.asin(dy / dist) * 180 / math.pi

        # Smooth rotation (slower when looking steeply)
        if self._rot is None:
            self._rot = (tgt_yaw, tgt_pitch)
        else:
            yaw, pitch = self._rot
            yd = tgt_yaw - yaw
            if yd > 180:
                yd -= 360
            elif yd < -180:
                yd += 360
            smooth = 0.15 * (1.0 - max(0.0, (abs(pitch) - 30) / 60) * 0.6)
            self._rot = (
                (yaw + yd * smooth) % 360,
                pitch + (tgt_pitch - pitch) * smooth,
            )

        return cam_pos, Rotation(*self._rot)

    def _spawn_bat(self):
        self.bat_eid = random.getrandbits(31)
        self.watch_pos, self.watch_rot = self._get_camera()
        self.client.send_packet(
            0x0F,
            VarInt.pack(self.bat_eid)
            + UnsignedByte.pack(65)
            + Int.pack(int(self.watch_pos.x * 32))
            + Int.pack(int(self.watch_pos.y * 32))
            + Int.pack(int(self.watch_pos.z * 32))
            + Angle.pack(self.watch_rot.yaw)
            + Angle.pack(self.watch_rot.pitch)
            + Angle.pack(0.0)
            + Short.pack(0)
            + Short.pack(0)
            + Short.pack(0)
            + UnsignedByte.pack(0)
            + Byte.pack(0x20)
            + UnsignedByte.pack(16)
            + Byte.pack(0)
            + UnsignedByte.pack(0x7F),
        )

    async def _update_watch(self):
        self._spawn_bat()
        while self.open:
            old = self.watch_pos
            self.watch_pos, self.watch_rot = self._get_camera()
            dx, dy, dz = (
                self.watch_pos.x - old.x,
                self.watch_pos.y - old.y,
                self.watch_pos.z - old.z,
            )

            if max(abs(dx), abs(dy), abs(dz)) > 4:
                self.client.send_packet(
                    0x18,
                    VarInt.pack(self.bat_eid),
                    Int.pack(int(self.watch_pos.x * 32)),
                    Int.pack(int(self.watch_pos.y * 32)),
                    Int.pack(int(self.watch_pos.z * 32)),
                    Angle.pack(self.watch_rot.yaw),
                    Angle.pack(self.watch_rot.pitch),
                    Boolean.pack(False),
                )
            else:
                self.client.send_packet(
                    0x15,
                    VarInt.pack(self.bat_eid),
                    Byte.pack(int(dx * 32)),
                    Byte.pack(int(dy * 32)),
                    Byte.pack(int(dz * 32)),
                    Boolean.pack(False),
                )

            self.client.send_packet(
                0x16,
                VarInt.pack(self.bat_eid),
                Angle.pack(self.watch_rot.yaw),
                Angle.pack(self.watch_rot.pitch),
                Boolean.pack(False),
            )
            await asyncio.sleep(0.1)

    async def _check_position(self):
        while self.open:
            pos = self.gamestate.position
            if pos.y < -100:
                owner = self.proxy.username
                self.client.chat(
                    TextComponent("Click here to teleport back to")
                    .color("green")
                    .bold()
                    .appends(TextComponent(owner).color("aqua"))
                    .click_event(
                        "run_command",
                        f"/tp {owner}",
                    )
                    .hover_text(
                        TextComponent("Teleport to")
                        .color("yellow")
                        .appends(TextComponent(owner).color("aqua"))
                    )
                )
                await asyncio.sleep(10)
            else:
                await asyncio.sleep(1)

    def _set_gamemode(self, gm: int):
        self.client.send_packet(0x2B, UnsignedByte.pack(3), Float.pack(float(gm)))

    @subscribe("setting:broadcast:titles")
    async def _setting_broadcast_titles(self, _match, data: list[Literal["ON", "OFF"]]):
        _, new_state = data
        if new_state == "OFF":
            self.client.send_packet(0x45, VarInt.pack(4))  # reset
        else:
            for packet in self.gamestate._build_title():
                id, packet_data = packet
                self.client.send_packet(id, packet_data)

    @subscribe("setting:broadcast.fly_speed")
    async def _setting_broadcast_fly_speed(self, _match, _data):
        self._send_abilities()

    def _send_abilities(self):
        _fly_speed_mapping = {"0.5x": 0.025, "1x": 0.05, "2x": 0.1}
        self.flight_speed = _fly_speed_mapping[self.settings.fly_speed.get()]

        flags = PlayerAbilityFlags.INVULNERABLE | self.flying | self.flight
        self.client.send_packet(
            0x39,
            Byte.pack(int(flags))
            + Float.pack(self.flight_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

    def _set_slot(self, slot: int, item: SlotData):
        self.client.send_packet(0x2F, Byte.pack(0), Short.pack(slot), Slot.pack(item))

    def _reset_spec(self):
        self.watching, self._cam, self._cam_stuck, self._rot, self._last_pos = (
            False,
            None,
            0,
            None,
            None,
        )
        self.client.send_packet(0x43, VarInt.pack(self.eid))
        self.client.send_packet(
            0x30,
            UnsignedByte.pack(0),
            Short.pack(45),
            b"".join(Slot.pack(SlotData()) for _ in range(45)),
        )
        self.spec_eid = None
        self._set_gamemode(2)
        self._send_abilities()
        self._set_slot(36, SlotData())

    @listen(0x02)
    async def _packet_use_entity(self, buff: Buffer):
        target, action = buff.unpack(VarInt), buff.unpack(VarInt)
        entity = self.gamestate.get_entity(target)
        if action == 0:
            if isinstance(entity, Player):
                if uuid_version(entity.uuid) == 2:  # is npc
                    return self._spectate(target)
                spectate_player_menu = PlayerSpectateWindow(self, entity)
                spectate_player_menu.open()
            elif isinstance(entity, Entity):
                return self._spectate(target)  # TODO: what?
            else:
                return self._spectate(target)

    def _find_eid(self, target: ServerPlayer):
        if target.name.casefold() == self.proxy.username.casefold():
            return self.proxy._transformer.player_eid
        if target.uuid is None or not (
            player := self.proxy.gamestate.get_player_by_uuid(target.uuid)
        ):
            raise CommandException(f"Player '{target.name}' is not nearby!")
        return player.entity_id

    @command("spectate", "spec")
    async def _command_spectate(self, target: ServerPlayer):
        """Spectate a player."""
        if target.name.casefold() == self.username.casefold():
            if self.spec_eid is None:
                raise CommandException("You are not spectating anyone!")
            return self._reset_spec()
        self._spectate(self._find_eid(target))

    def _spectate(self, eid: int):
        self.spec_eid = eid
        self._set_gamemode(3)
        self.client.send_packet(0x43, VarInt.pack(eid))

    # WIP
    # @command("watch")
    # async def _command_watch(self):
    #     """Enter cinematic mode."""
    #     self.watching = True
    #     self._spectate(self.bat_eid)


class PlayerSpectateWindow(Window):
    proxy: BroadcastPeerSpectatePlugin
    entity: Player

    def __init__(self, proxy: BroadcastPeerSpectatePlugin, entity: Player):
        self.proxy = proxy
        self.entity = entity

        self.health: Optional[float] = None
        self.display_name: str = self.entity.name
        self.player: Optional[hypixel.Player] = None

        super().__init__(
            proxy=self.proxy,
            window_title=entity.name,
            window_type="minecraft:chest",
            num_slots=9,
        )

        asyncio.create_task(self._load_details())
        self.set_slot(
            1,
            SlotData(
                item=Item.from_name("minecraft:ender_eye"),
                nbt=nbt.dumps(
                    nbt.from_dict(
                        {
                            "display": {
                                "Name": f"§b§lSpectate {entity.name}",
                            },
                        }
                    )
                ),
            ),
            callback=self._ender_eye_callback,
        )
        # WIP
        # self.set_slot(
        #     2,
        #     SlotData(
        #         item=Item.from_name("minecraft:ender_pearl"),
        #         nbt=nbt.dumps(
        #             nbt.from_dict(
        #                 {
        #                     "display": {
        #                         "Name": f"§d§lWatch {entity.name}",
        #                     },
        #                     "ench": [],
        #                 }
        #             )
        #         ),
        #     ),
        # )
        asyncio.create_task(self._update_slots())

    class Details(TypedDict):
        Name: str
        Lore: list[str]

    def _update(self):
        self.health = self.proxy.proxy.get_health(self.entity.name)

        if self.player is not None:
            if self.proxy.proxy.game.gametype in SUPPORTED_MODES:
                self.fdict = format_player_dict(
                    self.player,
                    self.proxy.proxy.game.gametype,
                )
                self.display_name = self.proxy.proxy._build_player_display_name(
                    self.entity.name, self.fdict
                )
            else:
                self.display_name = get_rankname(self.player)

        details = self.Details(Name=f"{self.display_name}", Lore=[])
        if self.health is not None:
            details["Lore"].append(
                TextComponent("Health:")
                .color("yellow")
                .appends(TextComponent(str(int(self.health))).color("white"))
                .append(TextComponent("❤").color("red"))
                .to_legacy()
            )

        if self.player is not None:
            details["Lore"].append(
                TextComponent("Hypixel Level:")
                .color("yellow")
                .appends(TextComponent(str(self.player.level)).color("dark_aqua"))
                .to_legacy()
            )

        self.set_slot(
            0,
            SlotData(
                item=Item.from_name("minecraft:skull"),
                damage=3,
                nbt=nbt.dumps(
                    nbt.from_dict({"SkullOwner": self.entity.name, "display": details})
                ),
            ),
        )
        self.update()

    async def _load_details(self):
        self.display_name = f"Loading {self.entity.name}'s name..."
        try:
            self.player = await self.proxy.proxy.hypixel_client.player(self.entity.name)
        except hypixel.HypixelException:
            self.display_name = self.entity.name

    async def _update_slots(self):
        def _or_glass_pane(sd: SlotData, display_name: str) -> SlotData:
            nsd = SlotData(
                item=Item.from_name("minecraft:stained_glass_pane"),
                damage=Item.from_display_name(
                    "Red Stained Glass Pane"
                ).data,  # ts some bs why is it the damage field
                nbt=nbt.dumps(
                    nbt.from_dict(
                        {
                            "display": {
                                "Name": f"§r§c{display_name}",
                            }
                        }
                    )
                ),
            )
            return nsd if sd.item is None else sd

        while self._open and self.proxy.open:
            self.set_slots(
                {
                    8: _or_glass_pane(self.entity.equipment.boots, "Boots slot empty"),
                    7: _or_glass_pane(
                        self.entity.equipment.leggings, "Leggings slot empty"
                    ),
                    6: _or_glass_pane(
                        self.entity.equipment.chestplate, "Chestplate slot empty"
                    ),
                    5: _or_glass_pane(
                        self.entity.equipment.helmet, "Helmet slot empty"
                    ),
                    4: _or_glass_pane(self.entity.equipment.held, "Main hand empty"),
                }
            )
            self._update()
            await asyncio.sleep(0.5)

    async def _ender_eye_callback(
        self,
        window: Window,
        slot: int,
        button: int,
        action_num: int,
        mode: int,
        clicked_item: SlotData,
    ):
        self.close()
        self.proxy._spectate(self.entity.entity_id)
