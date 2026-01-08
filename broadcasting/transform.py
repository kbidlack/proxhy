"""
Packet transformation for broadcasting player actions to spectators.

This module handles converting player packets (serverbound) into entity packets
(clientbound) so spectators can see the player's movements, actions, and state.
"""

# as with gamestate, mostly written by AI
# because there is a lot of busywork here

import uuid as uuid_mod
from typing import Callable, Optional

from protocol.datatypes import (
    UUID,
    Angle,
    Boolean,
    Buffer,
    Byte,
    Chat,
    Double,
    Float,
    Int,
    Short,
    Slot,
    SlotData,
    String,
    UnsignedByte,
    VarInt,
)
from proxhy.gamestate import GameState, Rotation, Vec3d

from . import packets

# Equipment slot 0 = held item (main hand)
EQUIPMENT_SLOT_HELD = 0


class PlayerTransformer:
    """
    Transforms player packets into entity packets for spectator clients.

    This class tracks the player's state (position, rotation, equipment, etc.)
    and converts serverbound player packets into clientbound entity packets
    that can be sent to spectator clients.
    """

    def __init__(
        self,
        gamestate: GameState,
        announce_func: Callable[[int, bytes], None],
        announce_player_func: Callable[[int, bytes], None],
    ):
        """
        Initialize the transformer.

        Args:
            gamestate: The GameState instance for accessing game data
            announce_func: Function to send a packet to all spectators
            announce_player_func: Function to send a packet about the player entity
                                  to spectators who have the player spawned
        """
        self.gamestate = gamestate
        self._announce = announce_func
        self._announce_player = announce_player_func

        # Player entity state
        self._player_eid: int = 0
        self._player_uuid: str = ""
        self._player_spawned_for: set[int] = set()

        # Player state tracking
        self._player_position: Vec3d = Vec3d()
        self._player_rotation: Rotation = Rotation()
        self._player_on_ground: bool = False
        self._player_metadata_flags: int = 0
        self._player_held_slot: int = 0
        self._player_equipment: dict[int, SlotData] = {}

    def reset(self):
        """Reset spawn tracking (e.g., on dimension change)."""
        self._player_spawned_for.clear()

    def init_from_gamestate(self, player_uuid: str):
        """Initialize player state from the current gamestate."""
        self._player_uuid = player_uuid
        self._player_eid = self.gamestate.player_entity_id
        self._player_position = Vec3d(
            self.gamestate.position.x,
            self.gamestate.position.y,
            self.gamestate.position.z,
        )
        self._player_rotation = Rotation(
            self.gamestate.rotation.yaw,
            self.gamestate.rotation.pitch,
        )

    @property
    def player_eid(self) -> int:
        return self._player_eid

    @property
    def player_uuid(self) -> str:
        return self._player_uuid

    @property
    def player_position(self) -> Vec3d:
        return self._player_position

    @property
    def player_rotation(self) -> Rotation:
        return self._player_rotation

    @property
    def player_equipment(self) -> dict[int, SlotData]:
        return self._player_equipment

    @property
    def player_metadata_flags(self) -> int:
        return self._player_metadata_flags

    @property
    def player_spawned_for(self) -> set[int]:
        return self._player_spawned_for

    def mark_spawned(self, client_eid: int):
        """Mark that the player has been spawned for a client."""
        self._player_spawned_for.add(client_eid)

    # =========================================================================
    # Serverbound packet handling (player -> server)
    # =========================================================================

    def handle_serverbound_packet(self, packet_id: int, data: bytes):
        """
        Handle a serverbound packet and generate spectator updates.

        Args:
            packet_id: The packet ID
            data: The packet data
        """
        buff = Buffer(data)

        if packet_id == 0x03:  # Player (on ground only)
            on_ground = buff.unpack(Boolean)
            self._player_on_ground = on_ground
            self._announce_player(0x14, VarInt.pack(self._player_eid))

        elif packet_id == 0x04:  # Player Position
            x = buff.unpack(Double)
            y = buff.unpack(Double)
            z = buff.unpack(Double)
            on_ground = buff.unpack(Boolean)
            self._update_player_position(x, y, z, None, None, on_ground)

        elif packet_id == 0x05:  # Player Look
            yaw = buff.unpack(Float)
            pitch = buff.unpack(Float)
            on_ground = buff.unpack(Boolean)
            self._update_player_look(yaw, pitch, on_ground)

        elif packet_id == 0x06:  # Player Position And Look
            x = buff.unpack(Double)
            y = buff.unpack(Double)
            z = buff.unpack(Double)
            yaw = buff.unpack(Float)
            pitch = buff.unpack(Float)
            on_ground = buff.unpack(Boolean)
            self._update_player_position(x, y, z, yaw, pitch, on_ground)

        elif packet_id == 0x07:  # Player Digging
            pass  # Server will send block break animation

        elif packet_id == 0x09:  # Held Item Change (serverbound)
            slot = buff.unpack(Short)
            self._player_held_slot = slot
            # Send equipment update to spectators with the item in the new slot
            held_item = self.gamestate.get_hotbar_slot(slot)
            if held_item is None:
                held_item = SlotData()  # Empty slot
            self._player_equipment[EQUIPMENT_SLOT_HELD] = held_item
            self._announce_player(
                0x04,  # Entity Equipment
                VarInt.pack(self._player_eid)
                + Short.pack(EQUIPMENT_SLOT_HELD)
                + Slot.pack(held_item),
            )

        elif packet_id == 0x0A:  # Animation (arm swing)
            self._announce_player(
                0x0B,
                VarInt.pack(self._player_eid) + UnsignedByte.pack(0),
            )

        elif packet_id == 0x0B:  # Entity Action (sneak/sprint/etc)
            _ = buff.unpack(VarInt)  # entity id
            action_id = buff.unpack(VarInt)
            _ = buff.unpack(VarInt)  # action parameter
            self._handle_entity_action(action_id)

    def _update_player_position(
        self,
        x: float,
        y: float,
        z: float,
        yaw: Optional[float],
        pitch: Optional[float],
        on_ground: bool,
    ):
        """Update player position and send entity movement to spectators."""
        old_pos = self._player_position
        new_pos = Vec3d(x, y, z)

        dx = (x - old_pos.x) * 32
        dy = (y - old_pos.y) * 32
        dz = (z - old_pos.z) * 32

        use_relative = (
            abs(dx) < 128
            and abs(dy) < 128
            and abs(dz) < 128
            and self._player_spawned_for
        )

        self._player_position = new_pos
        self._player_on_ground = on_ground

        if yaw is not None and pitch is not None:
            self._player_rotation = Rotation(yaw, pitch)

        if use_relative:
            if yaw is not None and pitch is not None:
                # Entity Look And Relative Move (0x17)
                self._announce_player(
                    0x17,
                    VarInt.pack(self._player_eid)
                    + Byte.pack(int(dx))
                    + Byte.pack(int(dy))
                    + Byte.pack(int(dz))
                    + Angle.pack(yaw)
                    + Angle.pack(pitch)
                    + Boolean.pack(on_ground),
                )
                self._announce_player(
                    0x19,
                    VarInt.pack(self._player_eid) + Angle.pack(yaw),
                )
            else:
                # Entity Relative Move (0x15)
                self._announce_player(
                    0x15,
                    VarInt.pack(self._player_eid)
                    + Byte.pack(int(dx))
                    + Byte.pack(int(dy))
                    + Byte.pack(int(dz))
                    + Boolean.pack(on_ground),
                )
        else:
            # Entity Teleport (0x18)
            self._announce_player(
                0x18,
                VarInt.pack(self._player_eid)
                + Int.pack(int(x * 32))
                + Int.pack(int(y * 32))
                + Int.pack(int(z * 32))
                + Angle.pack(self._player_rotation.yaw)
                + Angle.pack(self._player_rotation.pitch)
                + Boolean.pack(on_ground),
            )
            if yaw is not None:
                self._announce_player(
                    0x19,
                    VarInt.pack(self._player_eid) + Angle.pack(yaw),
                )

    def _update_player_look(self, yaw: float, pitch: float, on_ground: bool):
        """Update player rotation and send entity look to spectators."""
        self._player_rotation = Rotation(yaw, pitch)
        self._player_on_ground = on_ground

        # Entity Look (0x16)
        self._announce_player(
            0x16,
            VarInt.pack(self._player_eid)
            + Angle.pack(yaw)
            + Angle.pack(pitch)
            + Boolean.pack(on_ground),
        )
        # Entity Head Look (0x19)
        self._announce_player(
            0x19,
            VarInt.pack(self._player_eid) + Angle.pack(yaw),
        )

    def _handle_entity_action(self, action_id: int):
        """Handle entity action and update metadata flags."""
        if action_id == 0:  # Start sneaking
            self._player_metadata_flags |= 0x02
        elif action_id == 1:  # Stop sneaking
            self._player_metadata_flags &= ~0x02
        elif action_id == 3:  # Start sprinting
            self._player_metadata_flags |= 0x08
        elif action_id == 4:  # Stop sprinting
            self._player_metadata_flags &= ~0x08
        else:
            return

        metadata = pack_single_metadata(0, 0, self._player_metadata_flags)
        self._announce_player(
            0x1C,
            VarInt.pack(self._player_eid) + metadata,
        )

    # =========================================================================
    # Clientbound packet forwarding (server -> client)
    # =========================================================================

    def forward_clientbound_packet(
        self,
        packet_id: int,
        data: tuple[bytes, ...],
        spawn_callback: Callable[[], None],
    ):
        """
        Forward/transform a clientbound packet for spectators.

        Args:
            packet_id: The packet ID
            data: The packet data parts
            spawn_callback: Callback to spawn player for clients after position update
        """
        buff = Buffer(b"".join(data))

        if packet_id == 0x01:  # Join Game
            eid = buff.unpack(Int)
            self._player_eid = eid
            self._player_spawned_for.clear()
            # Don't forward - clients get their own Join Game

        elif packet_id == 0x07:  # Respawn
            dimension = buff.unpack(Int)
            difficulty = buff.unpack(UnsignedByte)
            _ = buff.unpack(UnsignedByte)  # gamemode
            level_type = buff.unpack(String)

            self._player_spawned_for.clear()

            self._announce(
                packet_id,
                Int.pack(dimension)
                + UnsignedByte.pack(difficulty)
                + UnsignedByte.pack(3)  # spectator
                + String.pack(level_type),
            )

        elif packet_id == 0x08:  # Player Position And Look (server -> client)
            x = buff.unpack(Double)
            y = buff.unpack(Double)
            z = buff.unpack(Double)
            yaw = buff.unpack(Float)
            pitch = buff.unpack(Float)
            flags = buff.unpack(Byte)

            if flags & 0x01:
                x += self._player_position.x
            if flags & 0x02:
                y += self._player_position.y
            if flags & 0x04:
                z += self._player_position.z
            if flags & 0x08:
                yaw += self._player_rotation.yaw
            if flags & 0x10:
                pitch += self._player_rotation.pitch

            self._player_position = Vec3d(x, y, z)
            self._player_rotation = Rotation(yaw, pitch)

            self._announce(packet_id, b"".join(data))
            spawn_callback()

            self._announce_player(
                0x18,
                VarInt.pack(self._player_eid)
                + Int.pack(int(x * 32))
                + Int.pack(int(y * 32))
                + Int.pack(int(z * 32))
                + Angle.pack(yaw)
                + Angle.pack(pitch)
                + Boolean.pack(self._player_on_ground),
            )

        elif packet_id == 0x04:  # Entity Equipment
            entity_id = buff.unpack(VarInt)
            slot = buff.unpack(Short)
            item = buff.unpack(Slot)

            if (
                entity_id == self._player_eid
                or entity_id == self.gamestate.player_entity_id
            ):
                self._player_equipment[slot] = item
                self._announce(
                    packet_id,
                    VarInt.pack(self._player_eid) + Short.pack(slot) + Slot.pack(item),
                )
            elif packet_id in packets.BC_SPEC_ALLOW:
                self._announce(packet_id, b"".join(data))

        elif packet_id == 0x0B:  # Animation (server -> client)
            entity_id = buff.unpack(VarInt)
            animation = buff.unpack(UnsignedByte)

            if entity_id == self.gamestate.player_entity_id:
                self._announce_player(
                    packet_id,
                    VarInt.pack(self._player_eid) + UnsignedByte.pack(animation),
                )
            elif packet_id in packets.BC_SPEC_ALLOW:
                self._announce(packet_id, b"".join(data))

        elif packet_id == 0x1C:  # Entity Metadata
            entity_id = buff.unpack(VarInt)

            if entity_id == self.gamestate.player_entity_id:
                rest = buff.read()
                self._announce_player(
                    packet_id,
                    VarInt.pack(self._player_eid) + rest,
                )
            elif packet_id in packets.BC_SPEC_ALLOW:
                self._announce(packet_id, b"".join(data))

        elif packet_id == 0x12:  # Entity Velocity
            entity_id = buff.unpack(VarInt)

            if entity_id == self.gamestate.player_entity_id:
                rest = buff.read()
                self._announce_player(
                    packet_id,
                    VarInt.pack(self._player_eid) + rest,
                )
            elif packet_id in packets.BC_SPEC_ALLOW:
                self._announce(packet_id, b"".join(data))

        elif packet_id == 0x1B:  # Attach Entity
            entity_id = buff.unpack(Int)
            vehicle_id = buff.unpack(Int)
            leash = buff.unpack(Boolean)

            if entity_id == self.gamestate.player_entity_id:
                self._announce(
                    packet_id,
                    Int.pack(self._player_eid)
                    + Int.pack(vehicle_id)
                    + Boolean.pack(leash),
                )
            elif packet_id in packets.BC_SPEC_ALLOW:
                self._announce(packet_id, b"".join(data))

        elif packet_id == 0x1D:  # Entity Effect
            entity_id = buff.unpack(VarInt)

            if entity_id == self.gamestate.player_entity_id:
                rest = buff.read()
                self._announce_player(
                    packet_id,
                    VarInt.pack(self._player_eid) + rest,
                )
            elif packet_id in packets.BC_SPEC_ALLOW:
                self._announce(packet_id, b"".join(data))

        elif packet_id == 0x1E:  # Remove Entity Effect
            entity_id = buff.unpack(VarInt)

            if entity_id == self.gamestate.player_entity_id:
                rest = buff.read()
                self._announce_player(
                    packet_id,
                    VarInt.pack(self._player_eid) + rest,
                )
            elif packet_id in packets.BC_SPEC_ALLOW:
                self._announce(packet_id, b"".join(data))

        elif packet_id == 0x2F:  # Set Slot
            window_id = buff.unpack(Byte)
            slot = buff.unpack(Short)
            slot_data = buff.unpack(Slot)

            # Check if this affects the currently held item
            # Window 0 is player inventory, slots 36-44 are hotbar (36 + held_slot)
            if window_id == 0:
                hotbar_slot = slot - 36
                if 0 <= hotbar_slot <= 8 and hotbar_slot == self._player_held_slot:
                    # The currently held slot was updated, send equipment update
                    self._player_equipment[EQUIPMENT_SLOT_HELD] = slot_data
                    self._announce_player(
                        0x04,  # Entity Equipment
                        VarInt.pack(self._player_eid)
                        + Short.pack(EQUIPMENT_SLOT_HELD)
                        + Slot.pack(slot_data),
                    )
            # Don't forward Set Slot to spectators (they don't have inventory)

        elif packet_id == 0x38:  # Player List Item
            self._announce(packet_id, b"".join(data))

        elif packet_id == 0x13:  # Destroy Entities
            count = buff.unpack(VarInt)
            entity_ids = [buff.unpack(VarInt) for _ in range(count)]

            filtered = [
                eid for eid in entity_ids if eid != self.gamestate.player_entity_id
            ]

            if filtered:
                new_data = VarInt.pack(len(filtered))
                for eid in filtered:
                    new_data += VarInt.pack(eid)
                self._announce(packet_id, new_data)

        elif packet_id not in packets.BC_SPEC_ALLOW:
            pass  # Not in allow list

        else:
            self._announce(packet_id, b"".join(data))


# =============================================================================
# Utility functions
# =============================================================================


def pack_single_metadata(index: int, type_id: int, value: int) -> bytes:
    """Pack a single metadata entry."""
    data = UnsignedByte.pack((type_id << 5) | (index & 0x1F))
    if type_id == 0:  # Byte
        data += Byte.pack(value)
    elif type_id == 1:  # Short
        data += Short.pack(value)
    elif type_id == 2:  # Int
        data += Int.pack(value)
    data += UnsignedByte.pack(0x7F)  # End of metadata
    return data


def pack_uuid(uuid_str: str) -> bytes:
    """Pack a UUID string to bytes."""
    return UUID.pack(uuid_mod.UUID(uuid_str))


def build_spawn_player_packet(
    player_eid: int,
    player_uuid: str,
    position: Vec3d,
    rotation: Rotation,
    metadata_flags: int,
) -> bytes:
    """Build a Spawn Player (0x0C) packet."""
    metadata = pack_single_metadata(0, 0, metadata_flags)

    return (
        VarInt.pack(player_eid)
        + pack_uuid(player_uuid)
        + Int.pack(int(position.x * 32))
        + Int.pack(int(position.y * 32))
        + Int.pack(int(position.z * 32))
        + Angle.pack(rotation.yaw)
        + Angle.pack(rotation.pitch)
        + Short.pack(0)  # Current item
        + metadata
    )


def build_player_list_add_packet(
    player_uuid: str,
    player_name: str,
    properties: list[dict] | None = None,
    gamemode: int = 0,
    ping: int = 0,
    display_name: str | None = None,
) -> bytes:
    """Build a Player List Item (0x38) packet with action ADD_PLAYER."""
    data = VarInt.pack(0)  # Action: ADD_PLAYER
    data += VarInt.pack(1)  # Number of players
    data += pack_uuid(player_uuid)
    data += String.pack(player_name)

    if properties:
        data += VarInt.pack(len(properties))
        for prop in properties:
            data += String.pack(prop.get("name", ""))
            data += String.pack(prop.get("value", ""))
            has_sig = prop.get("signature") is not None
            data += Boolean.pack(has_sig)
            if has_sig:
                data += String.pack(prop["signature"])
    else:
        data += VarInt.pack(0)

    data += VarInt.pack(gamemode)
    data += VarInt.pack(ping)

    if display_name:
        data += Boolean.pack(True)
        data += Chat.pack(display_name)
    else:
        data += Boolean.pack(False)

    return data
