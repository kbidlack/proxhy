import asyncio
import math
import random

from broadcasting.plugin import BroadcastPeerPlugin
from core.events import listen_client as listen
from core.events import subscribe
from protocol.datatypes import (
    Angle,
    Boolean,
    Buffer,
    Byte,
    Double,
    Float,
    Int,
    Short,
    Slot,
    SlotData,
    UnsignedByte,
    VarInt,
)
from proxhy.argtypes import ServerPlayer
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.gamestate import PlayerAbilityFlags, Rotation, Vec3d


class BroadcastPeerSpectatePlugin(BroadcastPeerPlugin):
    def _init_broadcast_peer_spectate(self):
        self.watching = False

    @listen(0x0B)
    async def packet_entity_action(self, buff: Buffer):
        if eid := buff.unpack(VarInt) != self.eid:
            print(
                f"0x0B: Sent EID and self EID mismatch? {eid} / {self.eid}"
            )  # TODO: log this
            return

        action_id = buff.unpack(VarInt)
        if action_id == 0 and self.spec_eid is not None:
            self._reset_spec()

    async def _update_spec_task(self):
        while self.open:
            if self.spec_eid is not None:
                if self.spec_eid == self.proxy._transformer.player_eid:
                    pos = self.proxy.gamestate.position
                    rot = self.proxy.gamestate.rotation
                    self.client.send_packet(
                        *self.proxy.gamestate._build_player_inventory()
                    )
                    self.client.send_packet(
                        0x2F, Byte.pack(-1), Short.pack(-1), Slot.pack(SlotData())
                    )
                else:
                    entity = self.proxy.gamestate.get_entity(self.spec_eid)
                    if entity:
                        pos = entity.position
                        rot = entity.rotation
                        equip = entity.equipment
                        self._set_slot(36, equip.held)  # hotbar slot 0
                        self._set_slot(5, equip.helmet)
                        self._set_slot(6, equip.chestplate)
                        self._set_slot(7, equip.leggings)
                        self._set_slot(8, equip.boots)
                    else:
                        rot = None
                        pos = None

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
            await asyncio.sleep(1 / 20)  # every tick, ideally

    @subscribe("login_success")
    async def _broadcast_peer_base_event_login_success(self, _):
        self.spectate_teleport_task = asyncio.create_task(self._update_spec_task())
        self.update_watch_task = asyncio.create_task(self._update_watch())

    def _get_watch_position_rotation(self) -> tuple[Vec3d, Rotation]:
        # TODO: calculate real watch position
        relative_position = Vec3d(2, 2, 2)
        position = self.proxy.gamestate.position + relative_position

        in_combat_with_plus_self = [
            *(e.position for e in self.proxy.ein_combat_with),
            self.proxy.gamestate.position,
        ]

        avg_position = sum(
            in_combat_with_plus_self,
            start=Vec3d(0, 0, 0),
        ) / len(in_combat_with_plus_self)

        rotation = self.compute_look(position, avg_position)
        return position, rotation

    def _spawn_bat(self) -> None:
        # TODO: check for eid clashes on the server
        self.bat_eid = random.getrandbits(31)
        self.watch_position, self.watch_rotation = self._get_watch_position_rotation()
        self.client.send_packet(
            0x0F,
            VarInt.pack(self.bat_eid)
            + UnsignedByte.pack(65)
            + Int.pack(int(self.watch_position.x * 32))
            + Int.pack(int(self.watch_position.y * 32))
            + Int.pack(int(self.watch_position.z * 32))
            + Angle.pack(self.watch_rotation.yaw)
            + Angle.pack(self.watch_rotation.pitch)
            + Angle.pack(0.0)
            + Short.pack(0)
            + Short.pack(0)
            + Short.pack(0)
            + UnsignedByte.pack(0)  # metadata index 0 (entity flags), type 0 (byte)
            + Byte.pack(0x20)  # 0x20; invisible
            + UnsignedByte.pack(
                16
            )  # metadata index 16 (bat: is hanging), type 0 (byte)
            + Byte.pack(0)  # not hanging
            + UnsignedByte.pack(0x7F),  # end of metadata
        )

    async def _update_watch(self):
        self._spawn_bat()

        while self.open:
            old_position = self.watch_position
            self.watch_position, self.watch_rotation = (
                self._get_watch_position_rotation()
            )
            dx = self.watch_position.x - old_position.x
            dy = self.watch_position.y - old_position.y
            dz = self.watch_position.z - old_position.z
            if any((abs(dx) > 4, abs(dy) > 4, abs(dz) > 4)):
                self.client.send_packet(
                    0x18,
                    VarInt.pack(self.bat_eid),
                    Int.pack(int(self.watch_position.x * 32)),  # fixed-point position
                    Int.pack(int(self.watch_position.y * 32)),
                    Int.pack(int(self.watch_position.z * 32)),
                    Angle.pack(self.watch_rotation.yaw),
                    Angle.pack(self.watch_rotation.pitch),
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
                Angle.pack(self.watch_rotation.yaw),
                Angle.pack(self.watch_rotation.pitch),
                Boolean.pack(False),
            )
            await asyncio.sleep(1 / 10)

    def compute_look(self, camera_pos: Vec3d, object_pos: Vec3d) -> Rotation:
        dx = object_pos.x - camera_pos.x
        dy = object_pos.y - camera_pos.y
        dz = object_pos.z - camera_pos.z

        r = math.sqrt(dx * dx + dy * dy + dz * dz)

        # yaw: xz-plane, starts at (0, +Z), ccw, degrees
        yaw = -math.atan2(dx, dz) * 180 / math.pi

        if yaw < 0:  # normalize
            yaw += 360

        pitch = -math.asin(dy / r) * 180 / math.pi

        return Rotation(yaw, pitch)

    def _set_gamemode(self, gamemode: int) -> None:
        self.client.send_packet(0x2B, UnsignedByte.pack(3), Float.pack(float(gamemode)))

    def _send_abilities(self) -> None:
        abilities_flags = int(
            PlayerAbilityFlags.INVULNERABLE
            | (PlayerAbilityFlags.FLYING if not self.proxy.gamestate.on_ground else 0)
            | self.flight
        )
        self.client.send_packet(
            0x39,
            Byte.pack(abilities_flags)
            + Float.pack(self.proxy.gamestate.flying_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

    def _set_slot(self, slot: int, item: SlotData | None) -> None:
        self.client.send_packet(
            0x2F,
            Byte.pack(0),  # window ID 0 = player inventory
            Short.pack(slot),
            Slot.pack(item if item else SlotData()),
        )

    def _reset_spec(self):
        self.watching = False
        self.client.send_packet(0x43, VarInt.pack(self.eid))
        self.client.send_packet(
            0x30,
            UnsignedByte.pack(0),  # window ID
            Short.pack(45),  # slot count
            b"".join(Slot.pack(SlotData()) for _ in range(45)),
        )
        self.spec_eid = None
        self._set_gamemode(2)
        self._send_abilities()
        self._set_slot(36, None)

    @listen(0x02)
    async def _packet_use_entity(self, buff: Buffer):
        target = buff.unpack(VarInt)
        type_ = buff.unpack(VarInt)
        if type_ == 0:
            self._spectate(target)

    def _find_eid(self, target: ServerPlayer):
        # check if it's the broadcasting player (compare by username since UUIDs
        # may differ between auth and server in offline/local mode)
        if target.name.casefold() == self.proxy.username.casefold():
            # use transformer's player_eid, not gamestate's - the transformer
            # spawns the owner with a different entity ID for spectators
            eid = self.proxy._transformer.player_eid
        else:
            # another player -- check that they're spawned nearby
            if target.uuid is None:
                raise CommandException(f"Player '{target.name}' is not nearby!")
            player = self.proxy.gamestate.get_player_by_uuid(target.uuid)
            if not player:
                raise CommandException(f"Player '{target.name}' is not nearby!")
            eid = player.entity_id

        return eid

    @command("spectate", "spec")
    async def _command_spectate(self, target: ServerPlayer) -> None:
        # check if it's the spectator themselves (reset spectate mode)
        if target.name.casefold() == self.username.casefold():
            if self.spec_eid is None:
                raise CommandException("You are not spectating anyone!")
            return self._reset_spec()

        eid = self._find_eid(target)
        self._spectate(eid)

    def _spectate(self, eid: int):
        self.spec_eid = eid
        self._set_gamemode(3)  # spectator mode
        self.client.send_packet(0x43, VarInt.pack(eid))

    @command("watch")
    async def _command_watch(self):
        self.watching = True
        self._spectate(self.bat_eid)
