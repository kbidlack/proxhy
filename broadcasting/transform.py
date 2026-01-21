"""
Packet transformation for broadcasting player actions to spectators.

This module handles converting player packets (serverbound) into entity packets
(clientbound) so spectators can see the player's movements, actions, and state.
"""

# as with gamestate, mostly written by AI
# because there is a lot of busywork here

import uuid as uuid_mod
from typing import Callable

from protocol.datatypes import (
    UUID,
    Angle,
    Boolean,
    Buffer,
    Byte,
    Chat,
    Float,
    Int,
    Short,
    Slot,
    SlotData,
    String,
    UnsignedByte,
    VarInt,
)
from proxhy.gamestate import GameState, PlayerAbilityFlags, Rotation, Vec3d

from . import packets

# Equipment slot 0 = held item (main hand)
EQUIPMENT_SLOT_HELD = 0


class PlayerTransformer:
    """
    Transforms player packets into entity packets for spectator clients.

    This class handles forwarding and transforming packets for broadcasting.
    Player state (position, rotation, flags, etc.) is tracked by GameState.
    This class only handles:
    - Converting serverbound packets into entity packets for spectators
    - Forwarding/transforming clientbound packets for spectators
    - Tracking which spectators have the player entity spawned
    - Tracking player equipment for spectators
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

        # Player entity state (for spectators - uses different EID than server)
        self._player_eid: int = 0
        self._player_uuid: str = ""
        self._player_spawned_for: set[int] = set()

        # Equipment tracked separately for spectator updates
        self._player_equipment: dict[int, SlotData] = {}

        # Track previous position/rotation for delta calculations
        self._last_position: Vec3d = Vec3d()
        self._last_rotation: Rotation = Rotation()

    def reset(self):
        """Reset spawn tracking (e.g., on dimension change)."""
        self._player_spawned_for.clear()

    def init_from_gamestate(self, player_uuid: str):
        """Initialize player state from the current gamestate."""
        self._player_uuid = player_uuid
        self._player_eid = self.gamestate.player_entity_id
        # Sync last position/rotation for delta calculations
        self._last_position = Vec3d(
            self.gamestate.position.x,
            self.gamestate.position.y,
            self.gamestate.position.z,
        )
        self._last_rotation = Rotation(
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
    def player_equipment(self) -> dict[int, SlotData]:
        return self._player_equipment

    @property
    def player_metadata_flags(self) -> int:
        """Get player metadata flags from gamestate."""
        return self.gamestate.player_flags

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

        GameState has already been updated with the new state before this is called.
        This method generates the appropriate entity packets for spectators.

        Args:
            packet_id: The packet ID
            data: The packet data
        """
        if packet_id == 0x03:  # Player (on ground only)
            self._announce_player(0x14, VarInt.pack(self._player_eid))

        elif packet_id == 0x04:  # Player Position
            self._broadcast_position_update(has_look=False)

        elif packet_id == 0x05:  # Player Look
            self._broadcast_look_update()

        elif packet_id == 0x06:  # Player Position And Look
            self._broadcast_position_update(has_look=True)

        elif packet_id == 0x07:  # Player Digging
            pass  # Server will send block break animation

        elif packet_id == 0x09:  # Held Item Change (serverbound)
            # Send equipment update to spectators with the item in the new slot
            held_item = self.gamestate.get_held_item()
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
            # Gamestate already updated the flags, just broadcast the metadata
            self._broadcast_entity_action()

    def _broadcast_position_update(self, has_look: bool):
        """Broadcast player position (and optionally look) update to spectators."""
        gs = self.gamestate
        new_pos = gs.position
        new_rot = gs.rotation

        dx = (new_pos.x - self._last_position.x) * 32
        dy = (new_pos.y - self._last_position.y) * 32
        dz = (new_pos.z - self._last_position.z) * 32

        use_relative = (
            abs(dx) < 128
            and abs(dy) < 128
            and abs(dz) < 128
            and self._player_spawned_for
        )

        if use_relative:
            if has_look:
                # Entity Look And Relative Move (0x17)
                self._announce_player(
                    0x17,
                    VarInt.pack(self._player_eid)
                    + Byte.pack(int(dx))
                    + Byte.pack(int(dy))
                    + Byte.pack(int(dz))
                    + Angle.pack(new_rot.yaw)
                    + Angle.pack(new_rot.pitch)
                    + Boolean.pack(gs.on_ground),
                )
                self._announce_player(
                    0x19,
                    VarInt.pack(self._player_eid) + Angle.pack(new_rot.yaw),
                )
            else:
                # Entity Relative Move (0x15)
                self._announce_player(
                    0x15,
                    VarInt.pack(self._player_eid)
                    + Byte.pack(int(dx))
                    + Byte.pack(int(dy))
                    + Byte.pack(int(dz))
                    + Boolean.pack(gs.on_ground),
                )
        else:
            # Entity Teleport (0x18)
            self._announce_player(
                0x18,
                VarInt.pack(self._player_eid)
                + Int.pack(int(new_pos.x * 32))
                + Int.pack(int(new_pos.y * 32))
                + Int.pack(int(new_pos.z * 32))
                + Angle.pack(new_rot.yaw)
                + Angle.pack(new_rot.pitch)
                + Boolean.pack(gs.on_ground),
            )
            if has_look:
                self._announce_player(
                    0x19,
                    VarInt.pack(self._player_eid) + Angle.pack(new_rot.yaw),
                )

        # Update last known position for next delta calculation
        self._last_position = Vec3d(new_pos.x, new_pos.y, new_pos.z)
        if has_look:
            self._last_rotation = Rotation(new_rot.yaw, new_rot.pitch)

    def _broadcast_look_update(self):
        """Broadcast player look update to spectators."""
        gs = self.gamestate
        yaw = gs.rotation.yaw
        pitch = gs.rotation.pitch

        # Entity Look (0x16)
        self._announce_player(
            0x16,
            VarInt.pack(self._player_eid)
            + Angle.pack(yaw)
            + Angle.pack(pitch)
            + Boolean.pack(gs.on_ground),
        )
        # Entity Head Look (0x19)
        self._announce_player(
            0x19,
            VarInt.pack(self._player_eid) + Angle.pack(yaw),
        )

        self._last_rotation = Rotation(yaw, pitch)

    def _broadcast_entity_action(self):
        """Broadcast entity metadata update for sneak/sprint state."""
        metadata = pack_single_metadata(0, 0, self.gamestate.player_flags)
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

            # Send respawn with adventure mode (2) instead of spectator (3)
            # to keep broadcast peers in adventure mode across dimension changes
            self._announce(
                packet_id,
                Int.pack(dimension)
                + UnsignedByte.pack(difficulty)
                + UnsignedByte.pack(2)  # adventure
                + String.pack(level_type),
            )

            # Resend player abilities after respawn to restore flying capability
            # Respawn clears client abilities, so we need to re-grant them
            abilities_flags = int(
                PlayerAbilityFlags.INVULNERABLE | PlayerAbilityFlags.ALLOW_FLYING
            )
            self._announce(
                0x39,  # Player Abilities
                Byte.pack(abilities_flags)
                + Float.pack(self.gamestate.flying_speed)
                + Float.pack(self.gamestate.field_of_view_modifier),
            )

        elif packet_id == 0x08:  # Player Position And Look (server -> client)
            # Gamestate has already processed this packet and updated position/rotation
            # We just need to sync our last position tracking and broadcast
            gs = self.gamestate
            self._last_position = Vec3d(gs.position.x, gs.position.y, gs.position.z)
            self._last_rotation = Rotation(gs.rotation.yaw, gs.rotation.pitch)

            # self._announce(packet_id, b"".join(data))
            if self.player_eid not in self.player_spawned_for:
                spawn_callback()

            self._announce_player(
                0x18,
                VarInt.pack(self._player_eid)
                + Int.pack(int(gs.position.x * 32))
                + Int.pack(int(gs.position.y * 32))
                + Int.pack(int(gs.position.z * 32))
                + Angle.pack(gs.rotation.yaw)
                + Angle.pack(gs.rotation.pitch)
                + Boolean.pack(gs.on_ground),
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
                if (
                    0 <= hotbar_slot <= 8
                    and hotbar_slot == self.gamestate.held_item_slot
                ):
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
