import asyncio

from broadcasting.plugin import BroadcastPeerPlugin
from core.events import listen_client as listen
from core.events import subscribe
from protocol.datatypes import (
    Buffer,
    Byte,
    Double,
    Float,
    Short,
    Slot,
    SlotData,
    UnsignedByte,
    VarInt,
)
from proxhy.argtypes import ServerPlayer
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.gamestate import PlayerAbilityFlags


class BroadcastPeerSpectatePlugin(BroadcastPeerPlugin):
    @listen(0x0B)
    async def packet_entity_action(self, buff: Buffer):
        if eid := buff.unpack(VarInt) != self.eid:
            print(
                f"0x0B: Sent EID and self EID mismatch? {eid} / {self.eid}"
            )  # TODO: log this
            return

        action_id = buff.unpack(VarInt)
        if action_id == 0 and self.spec_eid is not None:
            await self._command_spectate(None)

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

    @command("spectate", "spec")
    async def _command_spectate(self, target: ServerPlayer | None = None) -> None:
        if target is None:
            if self.spec_eid is not None:
                return self._reset_spec()
            else:
                raise CommandException("Please provide a target player!")

        # check if it's the spectator themselves (reset spectate mode)
        if target.name.casefold() == self.username.casefold():
            if self.spec_eid is None:
                raise CommandException("You are not spectating anyone!")
            return self._reset_spec()

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

        self._spectate(eid)

    def _spectate(self, eid: int):
        self.spec_eid = eid
        self._set_gamemode(3)  # spectator mode
        self.client.send_packet(0x43, VarInt.pack(eid))
