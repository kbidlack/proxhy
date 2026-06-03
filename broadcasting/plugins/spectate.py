import asyncio
import random
from typing import TYPE_CHECKING, Literal, Optional, TypedDict

import hypixel
import numpy as np

from gamestate.state import Entity, Player, PlayerAbilityFlags, Rotation, Vec3d
from petty import nbt
from petty.events import listen_client as listen
from petty.events import subscribe
from petty.protocol.datatypes import (
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
from plugins.commands import CommandException, command
from plugins.window import Window
from proxhy.argtypes import ServerPlayer
from proxhy.utils import uuid_version
from proxhypixel.formatting import get_rankname

if TYPE_CHECKING:
    from broadcasting.plugin import BroadcastPeerPlugin


def compute_look(camera_pos: Vec3d, object_pos: Vec3d):
    delta = np.array(
        [
            object_pos.x - camera_pos.x,
            object_pos.y - camera_pos.y,
            object_pos.z - camera_pos.z,
        ],
        dtype=np.float64,
    )

    dx, dy, dz = delta

    r = np.linalg.norm(delta)

    # yaw: xz-plane, starts at (0, +Z), ccw, degrees
    yaw = -np.degrees(np.arctan2(dx, dz))
    yaw = yaw % 360  # normalize to [0, 360)

    pitch = -np.degrees(np.arcsin(dy / r))

    return Rotation(yaw, pitch)


class BroadcastPeerSpectatePlugin:
    def _init_broadcast_peer_spectate(self: BroadcastPeerPlugin):
        self.watching = False
        self._cam: Vec3d | None = None  # camera offset from player
        self._cam_stuck = 0
        self._rot: tuple[float, float] | None = None  # smoothed (yaw, pitch)
        self._last_pos: Vec3d | None = None

    @listen(0x0B)
    async def packet_entity_action(self: BroadcastPeerPlugin, buff: Buffer):
        if buff.unpack(VarInt) != self.eid:
            return
        if buff.unpack(VarInt) == 0 and self.spec_eid is not None:
            self._reset_spec()

    @subscribe("login_success")
    async def _broadcast_peer_base_event_login_success(
        self: BroadcastPeerPlugin, _match, _data
    ):
        self.create_task(self._update_spec_task())
        self.create_task(self._update_watch())
        self.create_task(self._check_position())

    async def _update_watch(self: BroadcastPeerPlugin):
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
                self.downstream.send_packet(
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
                self.downstream.send_packet(
                    0x15,
                    VarInt.pack(self.bat_eid),
                    Byte.pack(int(dx * 32)),
                    Byte.pack(int(dy * 32)),
                    Byte.pack(int(dz * 32)),
                    Boolean.pack(False),
                )

            self.downstream.send_packet(
                0x16,
                VarInt.pack(self.bat_eid),
                Angle.pack(self.watch_rot.yaw),
                Angle.pack(self.watch_rot.pitch),
                Boolean.pack(False),
            )
            await asyncio.sleep(0.1)

    def _get_camera(self: BroadcastPeerPlugin) -> tuple[Vec3d, Rotation]:
        relative_position = Vec3d(2, 2, 2)
        position = self.proxy.gamestate.position + relative_position

        rotation = compute_look(position, self.proxy.gamestate.position)
        return position, rotation

    async def _update_spec_task(self: BroadcastPeerPlugin):
        while self.open:
            if self.spec_eid is None:
                await asyncio.sleep(0.05)
                continue

            pos = rot = None
            if self.spec_eid == self.proxy._transformer.player_eid:
                pos, rot = self.proxy.gamestate.position, self.proxy.gamestate.rotation
                self.downstream.send_packet(
                    *self.proxy.gamestate._build_player_inventory()
                )
                self.downstream.send_packet(
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
                self.downstream.send_packet(
                    0x08,
                    Double.pack(pos.x),
                    Double.pack(pos.y),
                    Double.pack(pos.z),
                    Float.pack(rot.yaw),
                    Float.pack(rot.pitch),
                    Byte.pack(0),
                )
            await asyncio.sleep(0.05)

    def _spawn_bat(self: BroadcastPeerPlugin):
        self.bat_eid = random.getrandbits(31)
        self.watch_pos, self.watch_rot = self._get_camera()
        self.downstream.send_packet(
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

    async def _check_position(self: BroadcastPeerPlugin):
        while self.open:
            pos = self.gamestate.position
            if pos.y < -100:
                owner = self.proxy.username
                self.downstream.chat(
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

    def _set_gamemode(self: BroadcastPeerPlugin, gm: int):
        self.downstream.send_packet(0x2B, UnsignedByte.pack(3), Float.pack(float(gm)))

    @subscribe("setting:broadcast.titles")
    async def _setting_broadcast_titles(
        self: BroadcastPeerPlugin, _match, data: list[Literal["ON", "OFF"]]
    ):
        _, new_state = data
        if new_state == "OFF":
            self.downstream.send_packet(0x45, VarInt.pack(4))  # reset
        else:
            for packet in self.gamestate._build_title():
                id, packet_data = packet
                self.downstream.send_packet(id, packet_data)

    @subscribe("setting:broadcast.fly_speed")
    async def _setting_broadcast_fly_speed(self: BroadcastPeerPlugin, _match, _data):
        self._send_abilities()

    def _send_abilities(self: BroadcastPeerPlugin):
        _fly_speed_mapping = {"0.5x": 0.025, "1x": 0.05, "2x": 0.1}
        self.flight_speed = _fly_speed_mapping[self.settings.fly_speed.get()]

        flags = PlayerAbilityFlags.INVULNERABLE | self.flying | self.flight
        self.downstream.send_packet(
            0x39,
            Byte.pack(int(flags))
            + Float.pack(self.flight_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

    def _set_slot(self: BroadcastPeerPlugin, slot: int, item: SlotData):
        self.downstream.send_packet(
            0x2F, Byte.pack(0), Short.pack(slot), Slot.pack(item)
        )

    def _reset_spec(self: BroadcastPeerPlugin):
        self.watching, self._cam, self._cam_stuck, self._rot, self._last_pos = (
            False,
            None,
            0,
            None,
            None,
        )
        self.downstream.send_packet(0x43, VarInt.pack(self.eid))
        self.downstream.send_packet(
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
    async def _packet_use_entity(self: BroadcastPeerPlugin, buff: Buffer):
        target, action = buff.unpack(VarInt), buff.unpack(VarInt)
        entity = self.gamestate.get_entity(target)

        if entity is None:
            self.downstream.chat(
                TextComponent(
                    f"That entity does not exist! (how did you do that?!) [{target=}, {action=}]"
                ).color("red")
            )

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

    def _find_eid(self: BroadcastPeerPlugin, target: ServerPlayer):
        if target.name.casefold() == self.proxy.username.casefold():
            return self.proxy._transformer.player_eid
        if target.uuid is None or not (
            player := self.proxy.gamestate.get_player_by_uuid(target.uuid)
        ):
            raise CommandException(f"Player '{target.name}' is not nearby!")
        return player.entity_id

    @command("spectate", "spec")
    async def _command_spectate(self: BroadcastPeerPlugin, target: ServerPlayer):
        """Spectate a player."""
        if target.name.casefold() == self.username.casefold():
            if self.spec_eid is None:
                raise CommandException("You are not spectating anyone!")
            return self._reset_spec()
        self._spectate(self._find_eid(target))

    def _spectate(self: BroadcastPeerPlugin, eid: int):
        self.spec_eid = eid
        self._set_gamemode(3)
        self.downstream.send_packet(0x43, VarInt.pack(eid))

    @command("watch")
    async def _command_watch(self: BroadcastPeerPlugin):
        """Enter cinematic mode."""
        self.watching = True
        self._spectate(self.bat_eid)


class PlayerSpectateWindow(Window):
    proxy: BroadcastPeerPlugin  # type: ignore
    entity: Player

    def __init__(self, proxy: BroadcastPeerPlugin, entity: Player):
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

        self.proxy.create_task(self._load_details())
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
        self.set_slot(
            2,
            SlotData(
                item=Item.from_name("minecraft:ender_pearl"),
                nbt=nbt.dumps(
                    nbt.from_dict(
                        {
                            "display": {
                                "Name": f"§d§lWatch {entity.name}",
                            },
                            "ench": [],
                        }
                    )
                ),
            ),
        )
        self.proxy.create_task(self._update_slots())

    class Details(TypedDict):
        Name: str
        Lore: list[str]

    def _update(self):
        self.health = self.proxy.proxy.get_health(self.entity.name)

        if self.player is not None:
            if gplayer := self.proxy.proxy.players_with_stats.get(self.entity.name):
                self.display_name = self.proxy.proxy._build_player_display_name(gplayer)
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
