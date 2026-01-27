"""
Minecraft Protocol v47 (1.8.x) Game State Tracker

This module provides a comprehensive game state tracker that processes
clientbound packets and maintains the complete game state as seen by a client.
"""

# mostly written by AI, because I was NOT about
# to copy this all myself from the mc wiki

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Any, Callable, Literal, Optional

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
    Long,
    Pos,
    Position,
    Short,
    Slot,
    SlotData,
    String,
    UnsignedByte,
    UnsignedShort,
    VarInt,
)

# Type alias for packet: (packet_id, packet_data)
type Packet = tuple[int, bytes]

# =============================================================================
# Enums and Constants
# =============================================================================


class Dimension(IntEnum):
    NETHER = -1
    OVERWORLD = 0
    END = 1


class Gamemode(IntEnum):
    SURVIVAL = 0
    CREATIVE = 1
    ADVENTURE = 2
    SPECTATOR = 3


class Difficulty(IntEnum):
    PEACEFUL = 0
    EASY = 1
    NORMAL = 2
    HARD = 3


class Animation(IntEnum):
    SWING_ARM = 0
    TAKE_DAMAGE = 1
    LEAVE_BED = 2
    EAT_FOOD = 3
    CRITICAL_EFFECT = 4
    MAGIC_CRITICAL_EFFECT = 5


class EntityStatus(IntEnum):
    SPAWN_MINECART_TIMER_RESET = 1
    LIVING_ENTITY_HURT = 2
    LIVING_ENTITY_DEAD = 3
    IRON_GOLEM_ARMS = 4
    TAMING_HEARTS = 6
    TAMED_SMOKE = 7
    WOLF_SHAKE = 8
    EATING_ACCEPTED = 9
    SHEEP_EATING = 10
    TNT_IGNITE = 10
    IRON_GOLEM_ROSE = 11
    VILLAGER_HEARTS = 12
    VILLAGER_ANGRY = 13
    VILLAGER_HAPPY = 14
    WITCH_MAGIC = 15
    ZOMBIE_CONVERTING = 16
    FIREWORK_EXPLODING = 17
    ANIMAL_LOVE = 18
    SQUID_RESET = 19
    EXPLOSION_PARTICLE = 20
    GUARDIAN_SOUND = 21
    REDUCED_DEBUG_ENABLED = 22
    REDUCED_DEBUG_DISABLED = 23


class GameStateReason(IntEnum):
    INVALID_BED = 0
    END_RAINING = 1
    BEGIN_RAINING = 2
    CHANGE_GAMEMODE = 3
    ENTER_CREDITS = 4
    DEMO_MESSAGE = 5
    ARROW_HIT_PLAYER = 6
    FADE_VALUE = 7
    FADE_TIME = 8
    MOB_APPEARANCE = 10


class PlayerListAction(IntEnum):
    ADD_PLAYER = 0
    UPDATE_GAMEMODE = 1
    UPDATE_LATENCY = 2
    UPDATE_DISPLAY_NAME = 3
    REMOVE_PLAYER = 4


class ScoreboardAction(IntEnum):
    CREATE_UPDATE = 0
    REMOVE = 1


class TeamMode(IntEnum):
    CREATE = 0
    REMOVE = 1
    UPDATE_INFO = 2
    ADD_PLAYERS = 3
    REMOVE_PLAYERS = 4


class TitleAction(IntEnum):
    SET_TITLE = 0
    SET_SUBTITLE = 1
    SET_TIMES = 2
    HIDE = 3
    RESET = 4


class WorldBorderAction(IntEnum):
    SET_SIZE = 0
    LERP_SIZE = 1
    SET_CENTER = 2
    INITIALIZE = 3
    SET_WARNING_TIME = 4
    SET_WARNING_BLOCKS = 5


class CombatEventType(IntEnum):
    ENTER_COMBAT = 0
    END_COMBAT = 1
    ENTITY_DEAD = 2


class EquipmentSlot(IntEnum):
    HELD = 0
    BOOTS = 1
    LEGGINGS = 2
    CHESTPLATE = 3
    HELMET = 4


class PlayerAbilityFlags(IntFlag):
    INVULNERABLE = 0x01
    FLYING = 0x02
    ALLOW_FLYING = 0x04
    CREATIVE_MODE = 0x08


class EntityFlags(IntFlag):
    ON_FIRE = 0x01
    CROUCHED = 0x02
    SPRINTING = 0x08
    EATING_DRINKING_BLOCKING = 0x10
    INVISIBLE = 0x20


class PistonState(IntEnum):
    PUSHING = 0
    PULLING = 1


class PistonDirection(IntEnum):
    DOWN = 0
    UP = 1
    SOUTH = 2
    WEST = 3
    NORTH = 4
    EAST = 5


class NoteBlockInstrument(IntEnum):
    HARP = 0
    DOUBLE_BASS = 1
    SNARE_DRUM = 2
    CLICKS_STICKS = 3
    BASS_DRUM = 4


class MinecartType(IntEnum):
    EMPTY = 0
    CHEST = 1
    FURNACE = 2
    TNT = 3
    SPAWNER = 4
    HOPPER = 5
    COMMAND_BLOCK = 6


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Vec3d:
    """3D position with double precision."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class Vec3i:
    """3D position with integer precision."""

    x: int = 0
    y: int = 0
    z: int = 0


@dataclass
class Rotation:
    """Entity rotation."""

    yaw: float = 0.0
    pitch: float = 0.0


@dataclass
class MetadataValue:
    """Typed metadata value that preserves the wire type for re-serialization."""

    type_id: (
        int  # 0=Byte, 1=Short, 2=Int, 3=Float, 4=String, 5=Slot, 6=Vec3i, 7=Rotation
    )
    value: Any


@dataclass
class PlayerInfo:
    """Information about a player in the player list."""

    uuid: str = ""
    name: str = ""
    properties: list[dict[str, Any]] = field(default_factory=list)
    gamemode: int = 0
    ping: int = 0
    display_name: str | None = None


@dataclass
class EntityEquipment:
    """Equipment slots for an entity."""

    held: SlotData | None = None
    boots: SlotData | None = None
    leggings: SlotData | None = None
    chestplate: SlotData | None = None
    helmet: SlotData | None = None


@dataclass
class EntityEffect:
    """Active effect on an entity."""

    effect_id: int = 0
    amplifier: int = 0
    duration: int = 0
    hide_particles: bool = False


@dataclass
class AttributeModifier:
    """Modifier for an entity attribute."""

    uuid: str = ""
    amount: float = 0.0
    operation: int = 0


@dataclass
class EntityAttribute:
    """An attribute of an entity."""

    key: str = ""
    value: float = 0.0
    modifiers: list[AttributeModifier] = field(default_factory=list)


@dataclass
class Entity:
    """Base entity data."""

    entity_id: int = 0
    entity_type: int = 0
    uuid: str = ""
    position: Vec3d = field(default_factory=Vec3d)
    rotation: Rotation = field(default_factory=Rotation)
    head_yaw: float = 0.0
    velocity: Vec3d = field(default_factory=Vec3d)
    on_ground: bool = False
    metadata: dict[int, MetadataValue] = field(default_factory=dict)
    equipment: EntityEquipment = field(default_factory=EntityEquipment)
    effects: dict[int, EntityEffect] = field(default_factory=dict)
    attributes: dict[str, EntityAttribute] = field(default_factory=dict)
    passengers: list[int] = field(default_factory=list)
    vehicle_id: int | None = None
    object_data: int = 0


@dataclass
class Player(Entity):
    """Player entity with additional player-specific data."""

    name: str = ""
    current_item: int = 0


@dataclass
class ChunkSection:
    """A 16x16x16 section of a chunk."""

    blocks: bytearray = field(default_factory=lambda: bytearray(8192))
    block_light: bytearray = field(default_factory=lambda: bytearray(2048))
    sky_light: bytearray | None = None

    def get_block(self, x: int, y: int, z: int) -> int:
        """Get block state at relative position."""
        index = ((y * 16 + z) * 16 + x) * 2
        return self.blocks[index] | (self.blocks[index + 1] << 8)

    def set_block(self, x: int, y: int, z: int, block_state: int) -> None:
        """Set block state at relative position."""
        index = ((y * 16 + z) * 16 + x) * 2
        self.blocks[index] = block_state & 0xFF
        self.blocks[index + 1] = (block_state >> 8) & 0xFF


@dataclass
class Chunk:
    """A chunk column (16x256x16)."""

    x: int = 0
    z: int = 0
    sections: list[ChunkSection | None] = field(default_factory=lambda: [None] * 16)
    biomes: bytearray = field(default_factory=lambda: bytearray(256))
    has_sky_light: bool = True

    def get_block(self, x: int, y: int, z: int) -> int:
        """Get block state at position within chunk."""
        section_y = y // 16
        section = self.sections[section_y]
        if section is None:
            return 0
        return section.get_block(x, y % 16, z)

    def set_block(self, x: int, y: int, z: int, block_state: int) -> None:
        """Set block state at position within chunk."""
        section_y = y // 16
        section = self.sections[section_y]
        if section is None:
            section = ChunkSection()
            if self.has_sky_light:
                section.sky_light = bytearray(2048)
            self.sections[section_y] = section
        section.set_block(x, y % 16, z, block_state)


@dataclass
class Window:
    """An open inventory window."""

    window_id: int = 0
    window_type: str = ""
    title: str = ""
    slot_count: int = 0
    slots: dict[int, SlotData] = field(default_factory=dict)
    entity_id: int | None = None
    properties: dict[int, int] = field(default_factory=dict)


@dataclass
class ScoreboardObjective:
    """A scoreboard objective."""

    name: str = ""
    display_text: str = ""
    objective_type: str = "integer"


@dataclass
class Score:
    """A score entry."""

    score_name: str = ""
    objective_name: str = ""
    value: int = 0


@dataclass
class Team:
    """A scoreboard team."""

    name: str = ""
    display_name: str = ""
    prefix: str = ""
    suffix: str = ""
    friendly_fire: int = 0
    name_tag_visibility: str = "always"
    color: int = 0
    members: set[str] = field(default_factory=set)


@dataclass
class MapData:
    """Data for a map item."""

    map_id: int = 0
    scale: int = 0
    icons: list[dict[str, Any]] = field(default_factory=list)
    pixels: bytearray = field(default_factory=lambda: bytearray(128 * 128))

    def update_region(
        self, x: int, z: int, width: int, height: int, data: bytes
    ) -> None:
        """Update a rectangular region of the map."""
        idx = 0
        for row in range(height):
            for col in range(width):
                px = x + col
                pz = z + row
                if 0 <= px < 128 and 0 <= pz < 128:
                    self.pixels[pz * 128 + px] = data[idx]
                idx += 1


@dataclass
class BlockEntity:
    """A block entity (tile entity)."""

    position: Vec3i = field(default_factory=Vec3i)
    action: int = 0
    nbt_data: bytes = b""


@dataclass
class Explosion:
    """Data about an explosion."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    radius: float = 0.0
    affected_blocks: list[Vec3i] = field(default_factory=list)
    player_motion: Vec3d = field(default_factory=Vec3d)


@dataclass
class WorldBorder:
    """World border state."""

    center_x: float = 0.0
    center_z: float = 0.0
    old_radius: float = 60000000.0
    new_radius: float = 60000000.0
    speed: int = 0
    portal_boundary: int = 29999984
    warning_time: int = 15
    warning_blocks: int = 5


@dataclass
class TitleState:
    """Current title display state."""

    title: str = ""
    subtitle: str = ""
    fade_in: int = 10
    stay: int = 70
    fade_out: int = 20
    visible: bool = False


@dataclass
class BossBar:
    """Boss bar display state (not in 1.8, but preparing for future)."""

    uuid: str = ""
    title: str = ""
    health: float = 1.0
    color: int = 0
    division: int = 0
    flags: int = 0


@dataclass
class Statistics:
    """Player statistics."""

    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class ResourcePack:
    """Resource pack state."""

    url: str = ""
    hash: str = ""
    status: int = 0


@dataclass
class PluginChannel:
    """Plugin channel registration."""

    registered: set[str] = field(default_factory=set)


@dataclass
class Sign:
    """Sign text content."""

    position: Vec3i = field(default_factory=Vec3i)
    lines: list[str] = field(default_factory=lambda: ["", "", "", ""])


@dataclass
class VillagerTrade:
    """A villager trade offer."""

    input_item_1: SlotData | None = None
    output_item: SlotData | None = None
    has_second_item: bool = False
    input_item_2: SlotData | None = None
    trade_disabled: bool = False
    trade_uses: int = 0
    max_trade_uses: int = 0


# =============================================================================
# Game State Class
# =============================================================================


class GameState:
    """
    Complete game state tracker for Minecraft protocol v47 (1.8.x).

    Processes clientbound packets and maintains the complete game state
    as seen by a client.
    """

    def __init__(self) -> None:
        """Initialize a new game state."""
        # Player state
        self.player_entity_id: int = 0
        self.player_uuid: str = ""
        self.player_name: str = ""
        self.gamemode: Gamemode = Gamemode.SURVIVAL
        self.is_hardcore: bool = False
        self.dimension: Dimension = Dimension.OVERWORLD
        self.difficulty: Difficulty = Difficulty.NORMAL
        self.max_players: int = 20
        self.level_type: str = "default"
        self.reduced_debug_info: bool = False

        # Player position and look
        self.position: Vec3d = Vec3d()
        self.rotation: Rotation = Rotation()
        self.on_ground: bool = False

        # Player health and food
        self.health: float = 20.0
        self.food: int = 20
        self.food_saturation: float = 5.0

        # Experience
        self.experience_bar: float = 0.0
        self.experience_level: int = 0
        self.total_experience: int = 0

        # Player abilities
        self.abilities: PlayerAbilityFlags = PlayerAbilityFlags(0)
        self.flying_speed: float = 0.05
        self.field_of_view_modifier: float = 0.1

        # Held item
        self.held_item_slot: int = 0

        # Player entity flags (sneaking, sprinting, etc.) - tracked from serverbound packets
        self.player_flags: int = 0  # EntityFlags bitmask

        # Spawn position
        self.spawn_position: Vec3i = Vec3i()

        # World state
        self.world_age: int = 0
        self.time_of_day: int = 0
        self.is_raining: bool = False
        self.rain_strength: float = 0.0
        self.thunder_strength: float = 0.0

        # Entities
        self.entities: dict[int, Entity] = {}
        self.players: dict[str, Player] = {}
        self.player_list: dict[str, PlayerInfo] = {}

        # Chunks
        self.chunks: dict[tuple[int, int], Chunk] = {}

        # Windows/Inventories
        self.player_inventory: Window = Window(
            window_id=0,
            window_type="minecraft:player",
            title="Inventory",
            slot_count=45,
        )
        self.open_window: Window | None = None
        self.cursor_item: SlotData | None = None

        # Scoreboard
        self.objectives: dict[str, ScoreboardObjective] = {}
        self.scores: dict[str, dict[str, Score]] = {}
        self.display_slots: dict[int, str] = {}
        self.teams: dict[str, Team] = {}

        # Maps
        self.maps: dict[int, MapData] = {}

        # Block entities
        self.block_entities: dict[tuple[int, int, int], BlockEntity] = {}

        # Signs
        self.signs: dict[tuple[int, int, int], Sign] = {}

        # World border
        self.world_border: WorldBorder = WorldBorder()

        # Title
        self.title: TitleState = TitleState()

        # Tab list header/footer
        self.tab_header: str = ""
        self.tab_footer: str = ""

        # Statistics
        self.statistics: Statistics = Statistics()

        # Resource pack
        self.resource_pack: ResourcePack = ResourcePack()

        # Plugin channels
        self.plugin_channels: PluginChannel = PluginChannel()

        # Villager trades (current open trading window)
        self.villager_trades: list[VillagerTrade] = []

        # Compression threshold
        self.compression_threshold: int = -1

        # Block break animations
        self.block_break_animations: dict[int, tuple[Vec3i, int]] = {}

        # Camera entity (for spectating)
        self.camera_entity_id: int | None = None

        # Packet handlers
        self._handlers: dict[int, Callable[[Buffer], None]] = self._init_handlers()

    def _init_handlers(self) -> dict[int, Callable[[Buffer], None]]:
        """Initialize packet handlers."""
        return {
            0x00: self._handle_keep_alive,
            0x01: self._handle_join_game,
            0x02: self._handle_chat_message,
            0x03: self._handle_time_update,
            0x04: self._handle_entity_equipment,
            0x05: self._handle_spawn_position,
            0x06: self._handle_update_health,
            0x07: self._handle_respawn,
            0x08: self._handle_player_position_and_look,
            0x09: self._handle_held_item_change,
            0x0A: self._handle_use_bed,
            0x0B: self._handle_animation,
            0x0C: self._handle_spawn_player,
            0x0D: self._handle_collect_item,
            0x0E: self._handle_spawn_object,
            0x0F: self._handle_spawn_mob,
            0x10: self._handle_spawn_painting,
            0x11: self._handle_spawn_experience_orb,
            0x12: self._handle_entity_velocity,
            0x13: self._handle_destroy_entities,
            0x14: self._handle_entity,
            0x15: self._handle_entity_relative_move,
            0x16: self._handle_entity_look,
            0x17: self._handle_entity_look_and_relative_move,
            0x18: self._handle_entity_teleport,
            0x19: self._handle_entity_head_look,
            0x1A: self._handle_entity_status,
            0x1B: self._handle_attach_entity,
            0x1C: self._handle_entity_metadata,
            0x1D: self._handle_entity_effect,
            0x1E: self._handle_remove_entity_effect,
            0x1F: self._handle_set_experience,
            0x20: self._handle_entity_properties,
            0x21: self._handle_chunk_data,
            0x22: self._handle_multi_block_change,
            0x23: self._handle_block_change,
            0x24: self._handle_block_action,
            0x25: self._handle_block_break_animation,
            0x26: self._handle_map_chunk_bulk,
            0x27: self._handle_explosion,
            0x28: self._handle_effect,
            0x29: self._handle_sound_effect,
            0x2A: self._handle_particle,
            0x2B: self._handle_change_game_state,
            0x2C: self._handle_spawn_global_entity,
            0x2D: self._handle_open_window,
            0x2E: self._handle_close_window,
            0x2F: self._handle_set_slot,
            0x30: self._handle_window_items,
            0x31: self._handle_window_property,
            0x32: self._handle_confirm_transaction,
            0x33: self._handle_update_sign,
            0x34: self._handle_map,
            0x35: self._handle_update_block_entity,
            0x36: self._handle_open_sign_editor,
            0x37: self._handle_statistics,
            0x38: self._handle_player_list_item,
            0x39: self._handle_player_abilities,
            0x3A: self._handle_tab_complete,
            0x3B: self._handle_scoreboard_objective,
            0x3C: self._handle_update_score,
            0x3D: self._handle_display_scoreboard,
            0x3E: self._handle_teams,
            0x3F: self._handle_plugin_message,
            0x40: self._handle_disconnect,
            0x41: self._handle_server_difficulty,
            0x42: self._handle_combat_event,
            0x43: self._handle_camera,
            0x44: self._handle_world_border,
            0x45: self._handle_title,
            0x46: self._handle_set_compression,
            0x47: self._handle_player_list_header_and_footer,
            0x48: self._handle_resource_pack_send,
            0x49: self._handle_update_entity_nbt,
        }

    def update(self, packet_id: int, packet_data: bytes) -> None:
        """
        Update the game state based on a received packet.

        Args:
            packet_id: The packet ID (0x00 - 0x49 for Play state)
            packet_data: The raw packet data (excluding packet ID)
        """
        handler = self._handlers.get(packet_id)
        if handler is not None:
            buff = Buffer(packet_data)
            try:
                handler(buff)
            except Exception:
                pass

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _get_or_create_entity(self, entity_id: int) -> Entity:
        """Get an existing entity or create a new one."""
        if entity_id not in self.entities:
            self.entities[entity_id] = Entity(entity_id=entity_id)
        return self.entities[entity_id]

    def _fixed_point_to_float(self, value: int) -> float:
        """Convert fixed-point number (5 fraction bits) to float."""
        return value / 32.0

    def _fixed_point_byte_to_float(self, value: int) -> float:
        """Convert fixed-point byte (5 fraction bits) to float."""
        if value > 127:
            value -= 256
        return value / 32.0

    def _angle_to_degrees(self, angle: float) -> float:
        """Convert protocol angle (0-255) to degrees."""
        return angle

    def _parse_uuid(self, buff: Buffer) -> str:
        """Parse a UUID from buffer."""
        high = buff.unpack(Long)
        low = buff.unpack(Long)
        uuid_int = (high << 64) | (low & 0xFFFFFFFFFFFFFFFF)
        hex_str = format(uuid_int & ((1 << 128) - 1), "032x")
        return f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:]}"

    def _parse_metadata(self, buff: Buffer) -> dict[int, MetadataValue]:
        """Parse entity metadata from buffer, preserving type information."""
        metadata: dict[int, MetadataValue] = {}

        while True:
            item = buff.unpack(UnsignedByte)
            if item == 0x7F:
                break

            index = item & 0x1F
            type_id = item >> 5

            if type_id == 0:
                metadata[index] = MetadataValue(type_id, buff.unpack(Byte))
            elif type_id == 1:
                metadata[index] = MetadataValue(type_id, buff.unpack(Short))
            elif type_id == 2:
                metadata[index] = MetadataValue(type_id, buff.unpack(Int))
            elif type_id == 3:
                metadata[index] = MetadataValue(type_id, buff.unpack(Float))
            elif type_id == 4:
                metadata[index] = MetadataValue(type_id, buff.unpack(String))
            elif type_id == 5:
                metadata[index] = MetadataValue(type_id, buff.unpack(Slot))
            elif type_id == 6:
                x = buff.unpack(Int)
                y = buff.unpack(Int)
                z = buff.unpack(Int)
                metadata[index] = MetadataValue(type_id, Vec3i(x, y, z))
            elif type_id == 7:
                pitch = buff.unpack(Float)
                yaw = buff.unpack(Float)
                roll = buff.unpack(Float)
                metadata[index] = MetadataValue(type_id, (pitch, yaw, roll))

        return metadata

    def _parse_chunk_section(self, buff: Buffer, has_sky_light: bool) -> ChunkSection:
        """Parse a chunk section from buffer."""
        section = ChunkSection()
        section.blocks = bytearray(buff.read(8192))
        section.block_light = bytearray(buff.read(2048))
        if has_sky_light:
            section.sky_light = bytearray(buff.read(2048))
        return section

    # =========================================================================
    # Packet Handlers
    # =========================================================================

    def _handle_keep_alive(self, buff: Buffer) -> None:
        """Handle Keep Alive packet (0x00)."""
        _ = buff.unpack(VarInt)

    def _handle_join_game(self, buff: Buffer) -> None:
        """Handle Join Game packet (0x01)."""
        self.player_entity_id = buff.unpack(Int)
        gamemode_byte = buff.unpack(UnsignedByte)
        self.is_hardcore = bool(gamemode_byte & 0x08)
        self.gamemode = Gamemode(gamemode_byte & 0x07)
        self.dimension = Dimension(buff.unpack(Byte))
        self.difficulty = Difficulty(buff.unpack(UnsignedByte))
        self.max_players = buff.unpack(UnsignedByte)
        self.level_type = buff.unpack(String)
        self.reduced_debug_info = buff.unpack(Boolean)

        self.chunks.clear()
        self.entities.clear()
        self.players.clear()

    def _handle_chat_message(self, buff: Buffer) -> None:
        """Handle Chat Message packet (0x02)."""
        _ = buff.unpack(Chat)
        _ = buff.unpack(Byte)

    def _handle_time_update(self, buff: Buffer) -> None:
        """Handle Time Update packet (0x03)."""
        self.world_age = buff.unpack(Long)
        self.time_of_day = buff.unpack(Long)

    def _handle_entity_equipment(self, buff: Buffer) -> None:
        """Handle Entity Equipment packet (0x04)."""
        entity_id = buff.unpack(VarInt)
        slot = buff.unpack(Short)
        item = buff.unpack(Slot)

        entity = self._get_or_create_entity(entity_id)
        equipment = entity.equipment

        if slot == EquipmentSlot.HELD:
            equipment.held = item
        elif slot == EquipmentSlot.BOOTS:
            equipment.boots = item
        elif slot == EquipmentSlot.LEGGINGS:
            equipment.leggings = item
        elif slot == EquipmentSlot.CHESTPLATE:
            equipment.chestplate = item
        elif slot == EquipmentSlot.HELMET:
            equipment.helmet = item

    def _handle_spawn_position(self, buff: Buffer) -> None:
        """Handle Spawn Position packet (0x05)."""
        pos: Pos = buff.unpack(Position)
        self.spawn_position = Vec3i(pos.x, pos.y, pos.z)

    def _handle_update_health(self, buff: Buffer) -> None:
        """Handle Update Health packet (0x06)."""
        self.health = buff.unpack(Float)
        self.food = buff.unpack(VarInt)
        self.food_saturation = buff.unpack(Float)

    def _handle_respawn(self, buff: Buffer) -> None:
        """Handle Respawn packet (0x07)."""
        self.dimension = Dimension(buff.unpack(Int))
        self.difficulty = Difficulty(buff.unpack(UnsignedByte))
        gamemode_byte = buff.unpack(UnsignedByte)
        self.gamemode = Gamemode(gamemode_byte & 0x07)
        self.level_type = buff.unpack(String)

        self.chunks.clear()
        self.entities.clear()

    def _handle_player_position_and_look(self, buff: Buffer) -> None:
        """Handle Player Position And Look packet (0x08)."""
        x = buff.unpack(Double)
        y = buff.unpack(Double)
        z = buff.unpack(Double)
        yaw = buff.unpack(Float)
        pitch = buff.unpack(Float)
        flags = buff.unpack(Byte)

        if flags & 0x01:
            self.position.x += x
        else:
            self.position.x = x

        if flags & 0x02:
            self.position.y += y
        else:
            self.position.y = y

        if flags & 0x04:
            self.position.z += z
        else:
            self.position.z = z

        if flags & 0x08:
            self.rotation.yaw += yaw
        else:
            self.rotation.yaw = yaw

        if flags & 0x10:
            self.rotation.pitch += pitch
        else:
            self.rotation.pitch = pitch

    def _handle_held_item_change(self, buff: Buffer) -> None:
        """Handle Held Item Change packet (0x09)."""
        self.held_item_slot = buff.unpack(Byte)

    def _handle_use_bed(self, buff: Buffer) -> None:
        """Handle Use Bed packet (0x0A)."""
        entity_id = buff.unpack(VarInt)
        pos: Pos = buff.unpack(Position)
        entity = self._get_or_create_entity(entity_id)
        entity.position = Vec3d(float(pos.x), float(pos.y), float(pos.z))

    def _handle_animation(self, buff: Buffer) -> None:
        """Handle Animation packet (0x0B)."""
        _ = buff.unpack(VarInt)
        _ = buff.unpack(UnsignedByte)

    def _handle_spawn_player(self, buff: Buffer) -> None:
        """Handle Spawn Player packet (0x0C)."""
        entity_id = buff.unpack(VarInt)
        uuid = self._parse_uuid(buff)
        x = self._fixed_point_to_float(buff.unpack(Int))
        y = self._fixed_point_to_float(buff.unpack(Int))
        z = self._fixed_point_to_float(buff.unpack(Int))
        yaw = self._angle_to_degrees(buff.unpack(Angle))
        pitch = self._angle_to_degrees(buff.unpack(Angle))
        current_item = buff.unpack(Short)
        metadata = self._parse_metadata(buff)

        player = Player(
            entity_id=entity_id,
            uuid=uuid,
            position=Vec3d(x, y, z),
            rotation=Rotation(yaw, pitch),
            current_item=current_item,
            metadata=metadata,
        )

        if uuid in self.player_list:
            player.name = self.player_list[uuid].name

        self.entities[entity_id] = player
        self.players[uuid] = player

    def _handle_collect_item(self, buff: Buffer) -> None:
        """Handle Collect Item packet (0x0D)."""
        _ = buff.unpack(VarInt)
        _ = buff.unpack(VarInt)

    def _handle_spawn_object(self, buff: Buffer) -> None:
        """Handle Spawn Object packet (0x0E)."""
        entity_id = buff.unpack(VarInt)
        entity_type = buff.unpack(Byte)
        x = self._fixed_point_to_float(buff.unpack(Int))
        y = self._fixed_point_to_float(buff.unpack(Int))
        z = self._fixed_point_to_float(buff.unpack(Int))
        pitch = self._angle_to_degrees(buff.unpack(Angle))
        yaw = self._angle_to_degrees(buff.unpack(Angle))
        data = buff.unpack(Int)

        entity = Entity(
            entity_id=entity_id,
            entity_type=entity_type,
            position=Vec3d(x, y, z),
            rotation=Rotation(yaw, pitch),
            object_data=data,
        )

        if data != 0:
            vx = buff.unpack(Short) / 8000.0
            vy = buff.unpack(Short) / 8000.0
            vz = buff.unpack(Short) / 8000.0
            entity.velocity = Vec3d(vx, vy, vz)

        self.entities[entity_id] = entity

    def _handle_spawn_mob(self, buff: Buffer) -> None:
        """Handle Spawn Mob packet (0x0F)."""
        entity_id = buff.unpack(VarInt)
        entity_type = buff.unpack(UnsignedByte)
        x = self._fixed_point_to_float(buff.unpack(Int))
        y = self._fixed_point_to_float(buff.unpack(Int))
        z = self._fixed_point_to_float(buff.unpack(Int))
        yaw = self._angle_to_degrees(buff.unpack(Angle))
        pitch = self._angle_to_degrees(buff.unpack(Angle))
        head_pitch = self._angle_to_degrees(buff.unpack(Angle))
        vx = buff.unpack(Short) / 8000.0
        vy = buff.unpack(Short) / 8000.0
        vz = buff.unpack(Short) / 8000.0
        metadata = self._parse_metadata(buff)

        entity = Entity(
            entity_id=entity_id,
            entity_type=entity_type,
            position=Vec3d(x, y, z),
            rotation=Rotation(yaw, pitch),
            head_yaw=head_pitch,
            velocity=Vec3d(vx, vy, vz),
            metadata=metadata,
        )

        self.entities[entity_id] = entity

    def _handle_spawn_painting(self, buff: Buffer) -> None:
        """Handle Spawn Painting packet (0x10)."""
        entity_id = buff.unpack(VarInt)
        title = buff.unpack(String)
        pos: Pos = buff.unpack(Position)
        direction = buff.unpack(UnsignedByte)

        entity = Entity(
            entity_id=entity_id,
            position=Vec3d(float(pos.x), float(pos.y), float(pos.z)),
            object_data=direction,
        )
        entity.metadata[0] = MetadataValue(4, title)  # type 4 = String

        self.entities[entity_id] = entity

    def _handle_spawn_experience_orb(self, buff: Buffer) -> None:
        """Handle Spawn Experience Orb packet (0x11)."""
        entity_id = buff.unpack(VarInt)
        x = self._fixed_point_to_float(buff.unpack(Int))
        y = self._fixed_point_to_float(buff.unpack(Int))
        z = self._fixed_point_to_float(buff.unpack(Int))
        count = buff.unpack(Short)

        entity = Entity(
            entity_id=entity_id,
            position=Vec3d(x, y, z),
            object_data=count,
        )

        self.entities[entity_id] = entity

    def _handle_entity_velocity(self, buff: Buffer) -> None:
        """Handle Entity Velocity packet (0x12)."""
        entity_id = buff.unpack(VarInt)
        vx = buff.unpack(Short) / 8000.0
        vy = buff.unpack(Short) / 8000.0
        vz = buff.unpack(Short) / 8000.0

        entity = self._get_or_create_entity(entity_id)
        entity.velocity = Vec3d(vx, vy, vz)

    def _handle_destroy_entities(self, buff: Buffer) -> None:
        """Handle Destroy Entities packet (0x13)."""
        count = buff.unpack(VarInt)
        for _ in range(count):
            entity_id = buff.unpack(VarInt)
            if entity_id in self.entities:
                entity = self.entities[entity_id]
                if isinstance(entity, Player) and entity.uuid in self.players:
                    del self.players[entity.uuid]
                del self.entities[entity_id]

    def _handle_entity(self, buff: Buffer) -> None:
        """Handle Entity packet (0x14)."""
        entity_id = buff.unpack(VarInt)
        self._get_or_create_entity(entity_id)

    def _handle_entity_relative_move(self, buff: Buffer) -> None:
        """Handle Entity Relative Move packet (0x15)."""
        entity_id = buff.unpack(VarInt)
        dx = self._fixed_point_byte_to_float(buff.unpack(Byte))
        dy = self._fixed_point_byte_to_float(buff.unpack(Byte))
        dz = self._fixed_point_byte_to_float(buff.unpack(Byte))
        on_ground = buff.unpack(Boolean)

        entity = self._get_or_create_entity(entity_id)
        entity.position.x += dx
        entity.position.y += dy
        entity.position.z += dz
        entity.on_ground = on_ground

    def _handle_entity_look(self, buff: Buffer) -> None:
        """Handle Entity Look packet (0x16)."""
        entity_id = buff.unpack(VarInt)
        yaw = self._angle_to_degrees(buff.unpack(Angle))
        pitch = self._angle_to_degrees(buff.unpack(Angle))
        on_ground = buff.unpack(Boolean)

        entity = self._get_or_create_entity(entity_id)
        entity.rotation = Rotation(yaw, pitch)
        entity.on_ground = on_ground

    def _handle_entity_look_and_relative_move(self, buff: Buffer) -> None:
        """Handle Entity Look And Relative Move packet (0x17)."""
        entity_id = buff.unpack(VarInt)
        dx = self._fixed_point_byte_to_float(buff.unpack(Byte))
        dy = self._fixed_point_byte_to_float(buff.unpack(Byte))
        dz = self._fixed_point_byte_to_float(buff.unpack(Byte))
        yaw = self._angle_to_degrees(buff.unpack(Angle))
        pitch = self._angle_to_degrees(buff.unpack(Angle))
        on_ground = buff.unpack(Boolean)

        entity = self._get_or_create_entity(entity_id)
        entity.position.x += dx
        entity.position.y += dy
        entity.position.z += dz
        entity.rotation = Rotation(yaw, pitch)
        entity.on_ground = on_ground

    def _handle_entity_teleport(self, buff: Buffer) -> None:
        """Handle Entity Teleport packet (0x18)."""
        entity_id = buff.unpack(VarInt)
        x = self._fixed_point_to_float(buff.unpack(Int))
        y = self._fixed_point_to_float(buff.unpack(Int))
        z = self._fixed_point_to_float(buff.unpack(Int))
        yaw = self._angle_to_degrees(buff.unpack(Angle))
        pitch = self._angle_to_degrees(buff.unpack(Angle))
        on_ground = buff.unpack(Boolean)

        entity = self._get_or_create_entity(entity_id)
        entity.position = Vec3d(x, y, z)
        entity.rotation = Rotation(yaw, pitch)
        entity.on_ground = on_ground

    def _handle_entity_head_look(self, buff: Buffer) -> None:
        """Handle Entity Head Look packet (0x19)."""
        entity_id = buff.unpack(VarInt)
        head_yaw = self._angle_to_degrees(buff.unpack(Angle))

        entity = self._get_or_create_entity(entity_id)
        entity.head_yaw = head_yaw

    def _handle_entity_status(self, buff: Buffer) -> None:
        """Handle Entity Status packet (0x1A)."""
        entity_id = buff.unpack(Int)
        status = buff.unpack(Byte)

        if status == EntityStatus.REDUCED_DEBUG_ENABLED:
            self.reduced_debug_info = True
        elif status == EntityStatus.REDUCED_DEBUG_DISABLED:
            self.reduced_debug_info = False

        self._get_or_create_entity(entity_id)

    def _handle_attach_entity(self, buff: Buffer) -> None:
        """Handle Attach Entity packet (0x1B)."""
        entity_id = buff.unpack(Int)
        vehicle_id = buff.unpack(Int)
        _ = buff.unpack(Boolean)

        entity = self._get_or_create_entity(entity_id)
        if vehicle_id == -1:
            entity.vehicle_id = None
        else:
            entity.vehicle_id = vehicle_id
            vehicle = self._get_or_create_entity(vehicle_id)
            if entity_id not in vehicle.passengers:
                vehicle.passengers.append(entity_id)

    def _handle_entity_metadata(self, buff: Buffer) -> None:
        """Handle Entity Metadata packet (0x1C)."""
        entity_id = buff.unpack(VarInt)
        metadata = self._parse_metadata(buff)

        entity = self._get_or_create_entity(entity_id)
        entity.metadata.update(metadata)

    def _handle_entity_effect(self, buff: Buffer) -> None:
        """Handle Entity Effect packet (0x1D)."""
        entity_id = buff.unpack(VarInt)
        effect_id = buff.unpack(Byte)
        amplifier = buff.unpack(Byte)
        duration = buff.unpack(VarInt)
        hide_particles = buff.unpack(Boolean)

        entity = self._get_or_create_entity(entity_id)
        entity.effects[effect_id] = EntityEffect(
            effect_id=effect_id,
            amplifier=amplifier,
            duration=duration,
            hide_particles=hide_particles,
        )

    def _handle_remove_entity_effect(self, buff: Buffer) -> None:
        """Handle Remove Entity Effect packet (0x1E)."""
        entity_id = buff.unpack(VarInt)
        effect_id = buff.unpack(Byte)

        entity = self._get_or_create_entity(entity_id)
        if effect_id in entity.effects:
            del entity.effects[effect_id]

    def _handle_set_experience(self, buff: Buffer) -> None:
        """Handle Set Experience packet (0x1F)."""
        self.experience_bar = buff.unpack(Float)
        self.experience_level = buff.unpack(VarInt)
        self.total_experience = buff.unpack(VarInt)

    def _handle_entity_properties(self, buff: Buffer) -> None:
        """Handle Entity Properties packet (0x20)."""
        entity_id = buff.unpack(VarInt)
        num_properties = buff.unpack(Int)

        entity = self._get_or_create_entity(entity_id)

        for _ in range(num_properties):
            key = buff.unpack(String)
            value = buff.unpack(Double)
            num_modifiers = buff.unpack(VarInt)

            modifiers = []
            for _ in range(num_modifiers):
                uuid = self._parse_uuid(buff)
                amount = buff.unpack(Double)
                operation = buff.unpack(Byte)
                modifiers.append(
                    AttributeModifier(
                        uuid=uuid,
                        amount=amount,
                        operation=operation,
                    )
                )

            entity.attributes[key] = EntityAttribute(
                key=key,
                value=value,
                modifiers=modifiers,
            )

    def _handle_chunk_data(self, buff: Buffer) -> None:
        """Handle Chunk Data packet (0x21)."""
        chunk_x = buff.unpack(Int)
        chunk_z = buff.unpack(Int)
        ground_up_continuous = buff.unpack(Boolean)
        primary_bitmask = buff.unpack(UnsignedShort)
        size = buff.unpack(VarInt)
        data = buff.read(size)

        if ground_up_continuous and primary_bitmask == 0:
            if (chunk_x, chunk_z) in self.chunks:
                del self.chunks[(chunk_x, chunk_z)]
            return

        has_sky_light = self.dimension == Dimension.OVERWORLD
        chunk = Chunk(x=chunk_x, z=chunk_z, has_sky_light=has_sky_light)

        data_buff = Buffer(data)
        for section_y in range(16):
            if primary_bitmask & (1 << section_y):
                section = self._parse_chunk_section(data_buff, has_sky_light)
                chunk.sections[section_y] = section

        if ground_up_continuous:
            chunk.biomes = bytearray(data_buff.read(256))

        self.chunks[(chunk_x, chunk_z)] = chunk

    def _handle_multi_block_change(self, buff: Buffer) -> None:
        """Handle Multi Block Change packet (0x22)."""
        chunk_x = buff.unpack(Int)
        chunk_z = buff.unpack(Int)
        record_count = buff.unpack(VarInt)

        chunk = self.chunks.get((chunk_x, chunk_z))
        if chunk is None:
            chunk = Chunk(x=chunk_x, z=chunk_z)
            self.chunks[(chunk_x, chunk_z)] = chunk

        for _ in range(record_count):
            horizontal_pos = buff.unpack(UnsignedByte)
            y = buff.unpack(UnsignedByte)
            block_id = buff.unpack(VarInt)

            x = (horizontal_pos >> 4) & 0x0F
            z = horizontal_pos & 0x0F

            chunk.set_block(x, y, z, block_id)

    def _handle_block_change(self, buff: Buffer) -> None:
        """Handle Block Change packet (0x23)."""
        pos: Pos = buff.unpack(Position)
        block_id = buff.unpack(VarInt)

        chunk_x = pos.x >> 4
        chunk_z = pos.z >> 4
        chunk = self.chunks.get((chunk_x, chunk_z))
        if chunk is None:
            chunk = Chunk(x=chunk_x, z=chunk_z)
            self.chunks[(chunk_x, chunk_z)] = chunk

        chunk.set_block(pos.x & 0x0F, pos.y, pos.z & 0x0F, block_id)

    def _handle_block_action(self, buff: Buffer) -> None:
        """Handle Block Action packet (0x24)."""
        _ = buff.unpack(Position)
        _ = buff.unpack(UnsignedByte)
        _ = buff.unpack(UnsignedByte)
        _ = buff.unpack(VarInt)

    def _handle_block_break_animation(self, buff: Buffer) -> None:
        """Handle Block Break Animation packet (0x25)."""
        entity_id = buff.unpack(VarInt)
        pos: Pos = buff.unpack(Position)
        destroy_stage = buff.unpack(Byte)

        if 0 <= destroy_stage <= 9:
            self.block_break_animations[entity_id] = (
                Vec3i(pos.x, pos.y, pos.z),
                destroy_stage,
            )
        elif entity_id in self.block_break_animations:
            del self.block_break_animations[entity_id]

    def _handle_map_chunk_bulk(self, buff: Buffer) -> None:
        """Handle Map Chunk Bulk packet (0x26)."""
        sky_light_sent = buff.unpack(Boolean)
        chunk_count = buff.unpack(VarInt)

        chunk_metas = []
        for _ in range(chunk_count):
            chunk_x = buff.unpack(Int)
            chunk_z = buff.unpack(Int)
            primary_bitmask = buff.unpack(UnsignedShort)
            chunk_metas.append((chunk_x, chunk_z, primary_bitmask))

        for chunk_x, chunk_z, primary_bitmask in chunk_metas:
            chunk = Chunk(x=chunk_x, z=chunk_z, has_sky_light=sky_light_sent)

            for section_y in range(16):
                if primary_bitmask & (1 << section_y):
                    section = self._parse_chunk_section(buff, sky_light_sent)
                    chunk.sections[section_y] = section

            chunk.biomes = bytearray(buff.read(256))
            self.chunks[(chunk_x, chunk_z)] = chunk

    def _handle_explosion(self, buff: Buffer) -> None:
        """Handle Explosion packet (0x27)."""
        x = buff.unpack(Float)
        y = buff.unpack(Float)
        z = buff.unpack(Float)
        _ = buff.unpack(Float)
        record_count = buff.unpack(Int)

        affected = []
        for _ in range(record_count):
            bx = buff.unpack(Byte)
            by = buff.unpack(Byte)
            bz = buff.unpack(Byte)
            affected.append(Vec3i(int(x) + bx, int(y) + by, int(z) + bz))

        pmx = buff.unpack(Float)
        pmy = buff.unpack(Float)
        pmz = buff.unpack(Float)

        for block in affected:
            chunk_x = block.x >> 4
            chunk_z = block.z >> 4
            chunk = self.chunks.get((chunk_x, chunk_z))
            if chunk and 0 <= block.y < 256:
                chunk.set_block(block.x & 0x0F, block.y, block.z & 0x0F, 0)

        self.position.x += pmx
        self.position.y += pmy
        self.position.z += pmz

    def _handle_effect(self, buff: Buffer) -> None:
        """Handle Effect packet (0x28)."""
        _ = buff.unpack(Int)
        _ = buff.unpack(Position)
        _ = buff.unpack(Int)
        _ = buff.unpack(Boolean)

    def _handle_sound_effect(self, buff: Buffer) -> None:
        """Handle Sound Effect packet (0x29)."""
        _ = buff.unpack(String)
        _ = buff.unpack(Int)
        _ = buff.unpack(Int)
        _ = buff.unpack(Int)
        _ = buff.unpack(Float)
        _ = buff.unpack(UnsignedByte)

    def _handle_particle(self, buff: Buffer) -> None:
        """Handle Particle packet (0x2A)."""
        particle_id = buff.unpack(Int)
        _ = buff.unpack(Boolean)
        _ = buff.unpack(Float)
        _ = buff.unpack(Float)
        _ = buff.unpack(Float)
        _ = buff.unpack(Float)
        _ = buff.unpack(Float)
        _ = buff.unpack(Float)
        _ = buff.unpack(Float)
        _ = buff.unpack(Int)

        if particle_id == 36:
            _ = buff.unpack(VarInt)
            _ = buff.unpack(VarInt)
        elif particle_id in (37, 38):
            _ = buff.unpack(VarInt)

    def _handle_change_game_state(self, buff: Buffer) -> None:
        """Handle Change Game State packet (0x2B)."""
        reason = buff.unpack(UnsignedByte)
        value = buff.unpack(Float)

        if reason == GameStateReason.END_RAINING:
            self.is_raining = False
        elif reason == GameStateReason.BEGIN_RAINING:
            self.is_raining = True
        elif reason == GameStateReason.CHANGE_GAMEMODE:
            self.gamemode = Gamemode(int(value))
        elif reason == GameStateReason.FADE_VALUE:
            self.rain_strength = value
        elif reason == GameStateReason.FADE_TIME:
            self.thunder_strength = value

    def _handle_spawn_global_entity(self, buff: Buffer) -> None:
        """Handle Spawn Global Entity packet (0x2C)."""
        entity_id = buff.unpack(VarInt)
        entity_type = buff.unpack(Byte)
        x = self._fixed_point_to_float(buff.unpack(Int))
        y = self._fixed_point_to_float(buff.unpack(Int))
        z = self._fixed_point_to_float(buff.unpack(Int))

        entity = Entity(
            entity_id=entity_id,
            entity_type=entity_type,
            position=Vec3d(x, y, z),
        )

        self.entities[entity_id] = entity

    def _handle_open_window(self, buff: Buffer) -> None:
        """Handle Open Window packet (0x2D)."""
        window_id = buff.unpack(UnsignedByte)
        window_type = buff.unpack(String)
        title = buff.unpack(Chat)
        slot_count = buff.unpack(UnsignedByte)

        entity_id = None
        if window_type == "EntityHorse":
            entity_id = buff.unpack(Int)

        self.open_window = Window(
            window_id=window_id,
            window_type=window_type,
            title=str(title) if title else "",
            slot_count=slot_count,
            entity_id=entity_id,
        )

    def _handle_close_window(self, buff: Buffer) -> None:
        """Handle Close Window packet (0x2E)."""
        window_id = buff.unpack(UnsignedByte)
        if self.open_window and self.open_window.window_id == window_id:
            self.open_window = None

    def _handle_set_slot(self, buff: Buffer) -> None:
        """Handle Set Slot packet (0x2F)."""
        window_id = buff.unpack(Byte)
        slot = buff.unpack(Short)
        slot_data = buff.unpack(Slot)

        if window_id == -1 and slot == -1:
            self.cursor_item = slot_data
        elif window_id == 0:
            self.player_inventory.slots[slot] = slot_data
        elif self.open_window and self.open_window.window_id == window_id:
            self.open_window.slots[slot] = slot_data

    def _handle_window_items(self, buff: Buffer) -> None:
        """Handle Window Items packet (0x30)."""
        window_id = buff.unpack(UnsignedByte)
        count = buff.unpack(Short)

        slots = {}
        for i in range(count):
            slots[i] = buff.unpack(Slot)

        if window_id == 0:
            self.player_inventory.slots = slots
        elif self.open_window and self.open_window.window_id == window_id:
            self.open_window.slots = slots

    def _handle_window_property(self, buff: Buffer) -> None:
        """Handle Window Property packet (0x31)."""
        window_id = buff.unpack(UnsignedByte)
        prop = buff.unpack(Short)
        value = buff.unpack(Short)

        if self.open_window and self.open_window.window_id == window_id:
            self.open_window.properties[prop] = value

    def _handle_confirm_transaction(self, buff: Buffer) -> None:
        """Handle Confirm Transaction packet (0x32)."""
        _ = buff.unpack(Byte)
        _ = buff.unpack(Short)
        _ = buff.unpack(Boolean)

    def _handle_update_sign(self, buff: Buffer) -> None:
        """Handle Update Sign packet (0x33)."""
        pos: Pos = buff.unpack(Position)
        line1 = buff.unpack(Chat)
        line2 = buff.unpack(Chat)
        line3 = buff.unpack(Chat)
        line4 = buff.unpack(Chat)

        self.signs[(pos.x, pos.y, pos.z)] = Sign(
            position=Vec3i(pos.x, pos.y, pos.z),
            lines=[
                str(line1) if line1 else "",
                str(line2) if line2 else "",
                str(line3) if line3 else "",
                str(line4) if line4 else "",
            ],
        )

    def _handle_map(self, buff: Buffer) -> None:
        """Handle Map packet (0x34)."""
        map_id = buff.unpack(VarInt)
        scale = buff.unpack(Byte)
        icon_count = buff.unpack(VarInt)

        icons = []
        for _ in range(icon_count):
            dir_type = buff.unpack(Byte)
            x = buff.unpack(Byte)
            z = buff.unpack(Byte)
            icons.append(
                {
                    "direction": (dir_type >> 4) & 0x0F,
                    "type": dir_type & 0x0F,
                    "x": x,
                    "z": z,
                }
            )

        columns = buff.unpack(Byte)

        if map_id not in self.maps:
            self.maps[map_id] = MapData(map_id=map_id)

        map_data = self.maps[map_id]
        map_data.scale = scale
        map_data.icons = icons

        if columns > 0:
            rows = buff.unpack(Byte)
            x = buff.unpack(Byte)
            z = buff.unpack(Byte)
            length = buff.unpack(VarInt)
            data = buff.read(length)
            map_data.update_region(x, z, columns, rows, data)

    def _handle_update_block_entity(self, buff: Buffer) -> None:
        """Handle Update Block Entity packet (0x35)."""
        pos: Pos = buff.unpack(Position)
        action = buff.unpack(UnsignedByte)
        nbt_data = buff.read()

        self.block_entities[(pos.x, pos.y, pos.z)] = BlockEntity(
            position=Vec3i(pos.x, pos.y, pos.z),
            action=action,
            nbt_data=nbt_data,
        )

    def _handle_open_sign_editor(self, buff: Buffer) -> None:
        """Handle Open Sign Editor packet (0x36)."""
        _ = buff.unpack(Position)

    def _handle_statistics(self, buff: Buffer) -> None:
        """Handle Statistics packet (0x37)."""
        count = buff.unpack(VarInt)
        for _ in range(count):
            name = buff.unpack(String)
            value = buff.unpack(VarInt)
            self.statistics.stats[name] = value

    def _handle_player_list_item(self, buff: Buffer) -> None:
        """Handle Player List Item packet (0x38)."""
        action = buff.unpack(VarInt)
        num_players = buff.unpack(VarInt)

        for _ in range(num_players):
            uuid = self._parse_uuid(buff)

            if action == PlayerListAction.ADD_PLAYER:
                name = buff.unpack(String)
                num_properties = buff.unpack(VarInt)
                properties = []
                for _ in range(num_properties):
                    prop_name = buff.unpack(String)
                    prop_value = buff.unpack(String)
                    is_signed = buff.unpack(Boolean)
                    signature = buff.unpack(String) if is_signed else None
                    properties.append(
                        {
                            "name": prop_name,
                            "value": prop_value,
                            "signature": signature,
                        }
                    )
                gamemode = buff.unpack(VarInt)
                ping = buff.unpack(VarInt)
                has_display_name = buff.unpack(Boolean)
                display_name = buff.unpack(Chat) if has_display_name else None

                self.player_list[uuid] = PlayerInfo(
                    uuid=uuid,
                    name=name,
                    properties=properties,
                    gamemode=gamemode,
                    ping=ping,
                    display_name=str(display_name) if display_name else None,
                )

            elif action == PlayerListAction.UPDATE_GAMEMODE:
                gamemode = buff.unpack(VarInt)
                if uuid in self.player_list:
                    self.player_list[uuid].gamemode = gamemode

            elif action == PlayerListAction.UPDATE_LATENCY:
                ping = buff.unpack(VarInt)
                if uuid in self.player_list:
                    self.player_list[uuid].ping = ping

            elif action == PlayerListAction.UPDATE_DISPLAY_NAME:
                has_display_name = buff.unpack(Boolean)
                display_name = buff.unpack(Chat) if has_display_name else None
                if uuid in self.player_list:
                    self.player_list[uuid].display_name = (
                        str(display_name) if display_name else None
                    )

            elif action == PlayerListAction.REMOVE_PLAYER:
                if uuid in self.player_list:
                    del self.player_list[uuid]

    def _handle_player_abilities(self, buff: Buffer) -> None:
        """Handle Player Abilities packet (0x39)."""
        flags = buff.unpack(Byte)
        self.flying_speed = buff.unpack(Float)
        self.field_of_view_modifier = buff.unpack(Float)

        self.abilities = PlayerAbilityFlags(flags)

    def _handle_tab_complete(self, buff: Buffer) -> None:
        """Handle Tab-Complete packet (0x3A)."""
        count = buff.unpack(VarInt)
        for _ in range(count):
            _ = buff.unpack(String)

    def _handle_scoreboard_objective(self, buff: Buffer) -> None:
        """Handle Scoreboard Objective packet (0x3B)."""
        objective_name = buff.unpack(String)
        mode = buff.unpack(Byte)

        if mode == 1:
            if objective_name in self.objectives:
                del self.objectives[objective_name]
            if objective_name in self.scores:
                del self.scores[objective_name]
        else:
            display_text = buff.unpack(String)
            objective_type = buff.unpack(String)

            self.objectives[objective_name] = ScoreboardObjective(
                name=objective_name,
                display_text=display_text,
                objective_type=objective_type,
            )

    def _handle_update_score(self, buff: Buffer) -> None:
        """Handle Update Score packet (0x3C)."""
        score_name = buff.unpack(String)
        action = buff.unpack(Byte)
        objective_name = buff.unpack(String)

        if action == 1:
            if objective_name in self.scores:
                if score_name in self.scores[objective_name]:
                    del self.scores[objective_name][score_name]
        else:
            value = buff.unpack(VarInt)
            if objective_name not in self.scores:
                self.scores[objective_name] = {}
            self.scores[objective_name][score_name] = Score(
                score_name=score_name,
                objective_name=objective_name,
                value=value,
            )

    def _handle_display_scoreboard(self, buff: Buffer) -> None:
        """Handle Display Scoreboard packet (0x3D)."""
        position = buff.unpack(Byte)
        score_name = buff.unpack(String)
        self.display_slots[position] = score_name

    def _handle_teams(self, buff: Buffer) -> None:
        """Handle Teams packet (0x3E)."""
        team_name = buff.unpack(String)
        mode = buff.unpack(Byte)

        if mode == TeamMode.CREATE:
            display_name = buff.unpack(String)
            prefix = buff.unpack(String)
            suffix = buff.unpack(String)
            friendly_fire = buff.unpack(Byte)
            name_tag_visibility = buff.unpack(String)
            color = buff.unpack(Byte)
            player_count = buff.unpack(VarInt)
            members = set()
            for _ in range(player_count):
                members.add(buff.unpack(String))

            self.teams[team_name] = Team(
                name=team_name,
                display_name=display_name,
                prefix=prefix,
                suffix=suffix,
                friendly_fire=friendly_fire,
                name_tag_visibility=name_tag_visibility,
                color=color,
                members=members,
            )

        elif mode == TeamMode.REMOVE:
            if team_name in self.teams:
                del self.teams[team_name]

        elif mode == TeamMode.UPDATE_INFO:
            display_name = buff.unpack(String)
            prefix = buff.unpack(String)
            suffix = buff.unpack(String)
            friendly_fire = buff.unpack(Byte)
            name_tag_visibility = buff.unpack(String)
            color = buff.unpack(Byte)

            if team_name in self.teams:
                team = self.teams[team_name]
                team.display_name = display_name
                team.prefix = prefix
                team.suffix = suffix
                team.friendly_fire = friendly_fire
                team.name_tag_visibility = name_tag_visibility
                team.color = color

        elif mode == TeamMode.ADD_PLAYERS:
            player_count = buff.unpack(VarInt)
            if team_name in self.teams:
                for _ in range(player_count):
                    self.teams[team_name].members.add(buff.unpack(String))
            else:
                for _ in range(player_count):
                    _ = buff.unpack(String)

        elif mode == TeamMode.REMOVE_PLAYERS:
            player_count = buff.unpack(VarInt)
            if team_name in self.teams:
                for _ in range(player_count):
                    player = buff.unpack(String)
                    self.teams[team_name].members.discard(player)
            else:
                for _ in range(player_count):
                    _ = buff.unpack(String)

    def _handle_plugin_message(self, buff: Buffer) -> None:
        """Handle Plugin Message packet (0x3F)."""
        channel = buff.unpack(String)
        data = buff.read()

        if channel == "REGISTER":
            channels = data.decode("utf-8").split("\x00")
            for ch in channels:
                if ch:
                    self.plugin_channels.registered.add(ch)
        elif channel == "UNREGISTER":
            channels = data.decode("utf-8").split("\x00")
            for ch in channels:
                self.plugin_channels.registered.discard(ch)
        elif channel == "MC|TrList":
            self._parse_villager_trades(Buffer(data))

    def _parse_villager_trades(self, buff: Buffer) -> None:
        """Parse villager trade list from MC|TrList plugin message."""
        _ = buff.unpack(Int)
        size = buff.unpack(Byte)

        self.villager_trades = []
        for _ in range(size):
            input_item_1 = buff.unpack(Slot)
            output_item = buff.unpack(Slot)
            has_second_item = buff.unpack(Boolean)
            input_item_2 = buff.unpack(Slot) if has_second_item else None
            trade_disabled = buff.unpack(Boolean)
            trade_uses = buff.unpack(Int)
            max_trade_uses = buff.unpack(Int)

            self.villager_trades.append(
                VillagerTrade(
                    input_item_1=input_item_1,
                    output_item=output_item,
                    has_second_item=has_second_item,
                    input_item_2=input_item_2,
                    trade_disabled=trade_disabled,
                    trade_uses=trade_uses,
                    max_trade_uses=max_trade_uses,
                )
            )

    def _handle_disconnect(self, buff: Buffer) -> None:
        """Handle Disconnect packet (0x40)."""
        _ = buff.unpack(Chat)

    def _handle_server_difficulty(self, buff: Buffer) -> None:
        """Handle Server Difficulty packet (0x41)."""
        self.difficulty = Difficulty(buff.unpack(UnsignedByte))

    def _handle_combat_event(self, buff: Buffer) -> None:
        """Handle Combat Event packet (0x42)."""
        event = buff.unpack(VarInt)

        if event == CombatEventType.END_COMBAT:
            _ = buff.unpack(VarInt)
            _ = buff.unpack(Int)
        elif event == CombatEventType.ENTITY_DEAD:
            _ = buff.unpack(VarInt)
            _ = buff.unpack(Int)
            _ = buff.unpack(String)

    def _handle_camera(self, buff: Buffer) -> None:
        """Handle Camera packet (0x43)."""
        self.camera_entity_id = buff.unpack(VarInt)

    def _handle_world_border(self, buff: Buffer) -> None:
        """Handle World Border packet (0x44)."""
        action = buff.unpack(VarInt)

        if action == WorldBorderAction.SET_SIZE:
            self.world_border.new_radius = buff.unpack(Double)
            self.world_border.old_radius = self.world_border.new_radius

        elif action == WorldBorderAction.LERP_SIZE:
            self.world_border.old_radius = buff.unpack(Double)
            self.world_border.new_radius = buff.unpack(Double)
            self.world_border.speed = buff.unpack(VarInt)

        elif action == WorldBorderAction.SET_CENTER:
            self.world_border.center_x = buff.unpack(Double)
            self.world_border.center_z = buff.unpack(Double)

        elif action == WorldBorderAction.INITIALIZE:
            self.world_border.center_x = buff.unpack(Double)
            self.world_border.center_z = buff.unpack(Double)
            self.world_border.old_radius = buff.unpack(Double)
            self.world_border.new_radius = buff.unpack(Double)
            self.world_border.speed = buff.unpack(VarInt)
            self.world_border.portal_boundary = buff.unpack(VarInt)
            self.world_border.warning_time = buff.unpack(VarInt)
            self.world_border.warning_blocks = buff.unpack(VarInt)

        elif action == WorldBorderAction.SET_WARNING_TIME:
            self.world_border.warning_time = buff.unpack(VarInt)

        elif action == WorldBorderAction.SET_WARNING_BLOCKS:
            self.world_border.warning_blocks = buff.unpack(VarInt)

    def _handle_title(self, buff: Buffer) -> None:
        """Handle Title packet (0x45)."""
        action = buff.unpack(VarInt)

        if action == TitleAction.SET_TITLE:
            title_text = buff.unpack(Chat)
            self.title.title = str(title_text) if title_text else ""
            self.title.visible = True

        elif action == TitleAction.SET_SUBTITLE:
            subtitle_text = buff.unpack(Chat)
            self.title.subtitle = str(subtitle_text) if subtitle_text else ""

        elif action == TitleAction.SET_TIMES:
            self.title.fade_in = buff.unpack(Int)
            self.title.stay = buff.unpack(Int)
            self.title.fade_out = buff.unpack(Int)

        elif action == TitleAction.HIDE:
            self.title.visible = False

        elif action == TitleAction.RESET:
            self.title = TitleState()

    def _handle_set_compression(self, buff: Buffer) -> None:
        """Handle Set Compression packet (0x46)."""
        self.compression_threshold = buff.unpack(VarInt)

    def _handle_player_list_header_and_footer(self, buff: Buffer) -> None:
        """Handle Player List Header And Footer packet (0x47)."""
        # Store raw JSON to preserve formatting/colors
        self.tab_header = buff.unpack(String)
        self.tab_footer = buff.unpack(String)

    def _handle_resource_pack_send(self, buff: Buffer) -> None:
        """Handle Resource Pack Send packet (0x48)."""
        self.resource_pack.url = buff.unpack(String)
        self.resource_pack.hash = buff.unpack(String)

    def _handle_update_entity_nbt(self, buff: Buffer) -> None:
        """Handle Update Entity NBT packet (0x49)."""
        entity_id = buff.unpack(VarInt)
        nbt_data = buff.read()

        entity = self._get_or_create_entity(entity_id)
        # Store raw NBT data at special index -1 (not sent via metadata protocol)
        entity.metadata[-1] = MetadataValue(-1, nbt_data)

    # =========================================================================
    # Serverbound Packet Handlers (player -> server)
    # =========================================================================

    def update_serverbound(self, packet_id: int, packet_data: bytes) -> None:
        """
        Update the game state based on a serverbound packet.

        This handles packets sent by the player to the server, which are needed
        to track the player's own state (position, rotation, actions) that isn't
        sent back via clientbound packets.

        Args:
            packet_id: The serverbound packet ID
            packet_data: The raw packet data (excluding packet ID)
        """
        buff = Buffer(packet_data)

        if packet_id == 0x03:  # Player (on ground only)
            self.on_ground = buff.unpack(Boolean)

        elif packet_id == 0x04:  # Player Position
            self.position.x = buff.unpack(Double)
            self.position.y = buff.unpack(Double)
            self.position.z = buff.unpack(Double)
            self.on_ground = buff.unpack(Boolean)

        elif packet_id == 0x05:  # Player Look
            self.rotation.yaw = buff.unpack(Float)
            self.rotation.pitch = buff.unpack(Float)
            self.on_ground = buff.unpack(Boolean)

        elif packet_id == 0x06:  # Player Position And Look
            self.position.x = buff.unpack(Double)
            self.position.y = buff.unpack(Double)
            self.position.z = buff.unpack(Double)
            self.rotation.yaw = buff.unpack(Float)
            self.rotation.pitch = buff.unpack(Float)
            self.on_ground = buff.unpack(Boolean)

        elif packet_id == 0x09:  # Held Item Change (serverbound)
            self.held_item_slot = buff.unpack(Short)

        elif packet_id == 0x0B:  # Entity Action
            _ = buff.unpack(VarInt)  # entity id (always player's own)
            action_id = buff.unpack(VarInt)
            # action_param = buff.unpack(VarInt)  # jump boost for horse, unused here

            if action_id == 0:  # Start sneaking
                self.player_flags |= EntityFlags.CROUCHED
            elif action_id == 1:  # Stop sneaking
                self.player_flags &= ~EntityFlags.CROUCHED
            elif action_id == 3:  # Start sprinting
                self.player_flags |= EntityFlags.SPRINTING
            elif action_id == 4:  # Stop sprinting
                self.player_flags &= ~EntityFlags.SPRINTING

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_block(self, x: int, y: int, z: int) -> int:
        """
        Get the block state at world coordinates.

        Args:
            x: World X coordinate
            y: World Y coordinate (0-255)
            z: World Z coordinate

        Returns:
            Block state ID (block_id << 4 | metadata) or 0 if chunk not loaded
        """
        chunk_x = x >> 4
        chunk_z = z >> 4
        chunk = self.chunks.get((chunk_x, chunk_z))
        if chunk is None:
            return 0
        return chunk.get_block(x & 0x0F, y, z & 0x0F)

    def get_entity(self, entity_id: int) -> Entity | None:
        """Get an entity by its ID."""
        return self.entities.get(entity_id)

    def get_player_by_uuid(self, uuid: str) -> Player | None:
        """Get a player entity by UUID."""
        return self.players.get(uuid)

    def get_player_by_name(self, name: str) -> Player | None:
        """Get a player entity by name."""
        for player in self.players.values():
            if player.name == name:
                return player
        return None

    def get_slot(self, window_id: int, slot: int) -> SlotData | None:
        """
        Get a slot from a window.

        Args:
            window_id: Window ID (0 for player inventory)
            slot: Slot index

        Returns:
            SlotData or None if not found
        """
        if window_id == 0:
            return self.player_inventory.slots.get(slot)
        elif self.open_window and self.open_window.window_id == window_id:
            return self.open_window.slots.get(slot)
        return None

    def get_hotbar_slot(self, slot: int) -> SlotData | None:
        """Get item in hotbar slot (0-8)."""
        return self.player_inventory.slots.get(36 + slot)

    def get_held_item(self) -> SlotData | None:
        """Get the currently held item."""
        return self.get_hotbar_slot(self.held_item_slot)

    def get_armor(self) -> list[SlotData | None]:
        """Get armor slots [helmet, chestplate, leggings, boots]."""
        return [
            self.player_inventory.slots.get(5),
            self.player_inventory.slots.get(6),
            self.player_inventory.slots.get(7),
            self.player_inventory.slots.get(8),
        ]

    def get_objective_score(self, objective: str, name: str) -> int | None:
        """Get a score for a name in an objective."""
        if objective in self.scores and name in self.scores[objective]:
            return self.scores[objective][name].value
        return None

    def get_team_for_player(self, player_name: str) -> Team | None:
        """Get the team a player belongs to."""
        for team in self.teams.values():
            if player_name in team.members:
                return team
        return None

    def is_chunk_loaded(self, chunk_x: int, chunk_z: int) -> bool:
        """Check if a chunk is loaded."""
        return (chunk_x, chunk_z) in self.chunks

    def get_nearby_entities(
        self, x: float, y: float, z: float, radius: float
    ) -> list[Entity]:
        """Get entities within a radius of a position."""
        result = []
        radius_sq = radius * radius
        for entity in self.entities.values():
            dx = entity.position.x - x
            dy = entity.position.y - y
            dz = entity.position.z - z
            if dx * dx + dy * dy + dz * dz <= radius_sq:
                result.append(entity)
        return result

    def get_biome(self, x: int, z: int) -> int:
        """Get the biome ID at world coordinates."""
        chunk_x = x >> 4
        chunk_z = z >> 4
        chunk = self.chunks.get((chunk_x, chunk_z))
        if chunk is None:
            return 0
        local_x = x & 0x0F
        local_z = z & 0x0F
        return chunk.biomes[local_z * 16 + local_x]

    def reset(self) -> None:
        """Reset the game state to initial values."""
        self.__init__()

    # =========================================================================
    # Packet Building Methods
    # =========================================================================

    def _build_join_game(
        self, eid: Optional[int] = None, gamemode: Optional[Literal[1, 2, 3, 4]] = None
    ) -> Packet:
        """Build Join Game packet (0x01)."""
        game_mode = gamemode or self.gamemode.value
        if self.is_hardcore:
            game_mode |= 0x08

        data = (
            Int.pack(eid or self.player_entity_id)
            + UnsignedByte.pack(game_mode)
            + Byte.pack(self.dimension.value)
            + UnsignedByte.pack(self.difficulty.value)
            + UnsignedByte.pack(self.max_players)
            + String.pack(self.level_type)
            + Boolean.pack(self.reduced_debug_info)
        )
        return (0x01, data)

    def _build_server_difficulty(self) -> Packet:
        """Build Server Difficulty packet (0x41)."""
        return (0x41, UnsignedByte.pack(self.difficulty.value))

    def _build_player_abilities(self) -> Packet:
        """Build Player Abilities packet (0x39)."""
        data = (
            Byte.pack(int(self.abilities))
            + Float.pack(self.flying_speed)
            + Float.pack(self.field_of_view_modifier)
        )
        return (0x39, data)

    def _build_held_item_change(self) -> Packet:
        """Build Held Item Change packet (0x09)."""
        return (0x09, Byte.pack(self.held_item_slot))

    def _build_spawn_position(self) -> Packet:
        """Build Spawn Position packet (0x05)."""
        pos = (self.spawn_position.x, self.spawn_position.y, self.spawn_position.z)
        return (0x05, Position.pack(pos))

    def _build_player_position_and_look(self) -> Packet:
        """Build Player Position And Look packet (0x08)."""
        data = (
            Double.pack(self.position.x)
            + Double.pack(self.position.y)
            + Double.pack(self.position.z)
            + Float.pack(self.rotation.yaw)
            + Float.pack(self.rotation.pitch)
            + Byte.pack(0)  # Flags: all absolute
        )
        return (0x08, data)

    def _build_update_health(self) -> Packet:
        """Build Update Health packet (0x06)."""
        data = (
            Float.pack(self.health)
            + VarInt.pack(self.food)
            + Float.pack(self.food_saturation)
        )
        return (0x06, data)

    def _build_set_experience(self) -> Packet:
        """Build Set Experience packet (0x1F)."""
        data = (
            Float.pack(self.experience_bar)
            + VarInt.pack(self.experience_level)
            + VarInt.pack(self.total_experience)
        )
        return (0x1F, data)

    def _build_time_update(self) -> Packet:
        """Build Time Update packet (0x03)."""
        data = Long.pack(self.world_age) + Long.pack(self.time_of_day)
        return (0x03, data)

    def _build_world_border(self) -> Packet:
        """Build World Border packet (0x44) with Initialize action."""
        data = (
            VarInt.pack(WorldBorderAction.INITIALIZE)
            + Double.pack(self.world_border.center_x)
            + Double.pack(self.world_border.center_z)
            + Double.pack(self.world_border.old_radius)
            + Double.pack(self.world_border.new_radius)
            + VarInt.pack(self.world_border.speed)
            + VarInt.pack(self.world_border.portal_boundary)
            + VarInt.pack(self.world_border.warning_time)
            + VarInt.pack(self.world_border.warning_blocks)
        )
        return (0x44, data)

    def _build_player_list_items(self) -> list[Packet]:
        """Build Player List Item packets (0x38) for all players."""
        if not self.player_list:
            return []

        packets: list[Packet] = []

        # Build one packet with all player additions
        data = VarInt.pack(PlayerListAction.ADD_PLAYER)
        data += VarInt.pack(len(self.player_list))

        for uuid, info in self.player_list.items():
            # data += UUID.pack(uuid_mod.UUID(uuid))
            data += self._pack_uuid(uuid)
            data += String.pack(info.name)
            data += VarInt.pack(len(info.properties))
            for prop in info.properties:
                data += String.pack(prop.get("name", ""))
                data += String.pack(prop.get("value", ""))
                has_sig = prop.get("signature") is not None
                data += Boolean.pack(has_sig)
                if has_sig:
                    data += String.pack(prop["signature"])
            data += VarInt.pack(info.gamemode)
            data += VarInt.pack(info.ping)
            has_display = info.display_name is not None
            data += Boolean.pack(has_display)
            if has_display and info.display_name is not None:
                data += Chat.pack(info.display_name)

        packets.append((0x38, data))
        return packets

    def _build_player_list_header_footer(self) -> Packet:
        """Build Player List Header And Footer packet (0x47)."""
        # tab_header/tab_footer are raw JSON strings
        data = String.pack(self.tab_header) + String.pack(self.tab_footer)
        return (0x47, data)

    def _build_scoreboard_objectives(self) -> list[Packet]:
        """Build Scoreboard Objective packets (0x3B)."""
        packets: list[Packet] = []
        for obj in self.objectives.values():
            data = (
                String.pack(obj.name)
                + Byte.pack(0)  # Mode: Create
                + String.pack(obj.display_text)
                + String.pack(obj.objective_type)
            )
            packets.append((0x3B, data))
        return packets

    def _build_scoreboard_scores(self) -> list[Packet]:
        """Build Update Score packets (0x3C)."""
        packets: list[Packet] = []
        for objective_name, scores in self.scores.items():
            for score_name, score in scores.items():
                data = (
                    String.pack(score_name)
                    + Byte.pack(0)  # Action: Create/Update
                    + String.pack(objective_name)
                    + VarInt.pack(score.value)
                )
                packets.append((0x3C, data))
        return packets

    def _build_display_scoreboards(self) -> list[Packet]:
        """Build Display Scoreboard packets (0x3D)."""
        packets: list[Packet] = []
        for position, score_name in self.display_slots.items():
            data = Byte.pack(position) + String.pack(score_name)
            packets.append((0x3D, data))
        return packets

    def _build_teams(self) -> list[Packet]:
        """Build Teams packets (0x3E)."""
        packets: list[Packet] = []
        for team in self.teams.values():
            # Create team with all info and members
            data = (
                String.pack(team.name)
                + Byte.pack(TeamMode.CREATE)
                + String.pack(team.display_name)
                + String.pack(team.prefix)
                + String.pack(team.suffix)
                + Byte.pack(team.friendly_fire)
                + String.pack(team.name_tag_visibility)
                + Byte.pack(team.color)
                + VarInt.pack(len(team.members))
            )
            for member in team.members:
                data += String.pack(member)
            packets.append((0x3E, data))
        return packets

    def _build_chunk_data(self) -> list[Packet]:
        """Build Chunk Data packets (0x21) for all loaded chunks."""
        packets: list[Packet] = []

        for (chunk_x, chunk_z), chunk in self.chunks.items():
            # Calculate primary bitmask
            primary_bitmask = 0
            for i, section in enumerate(chunk.sections):
                if section is not None:
                    primary_bitmask |= 1 << i

            if primary_bitmask == 0:
                continue  # Skip empty chunks

            # Build chunk data
            chunk_data = b""
            for section in chunk.sections:
                if section is not None:
                    chunk_data += bytes(section.blocks)
                    chunk_data += bytes(section.block_light)
                    if section.sky_light is not None:
                        chunk_data += bytes(section.sky_light)

            # Add biome data
            chunk_data += bytes(chunk.biomes)

            data = (
                Int.pack(chunk_x)
                + Int.pack(chunk_z)
                + Boolean.pack(True)  # Ground-up continuous
                + UnsignedShort.pack(primary_bitmask)
                + VarInt.pack(len(chunk_data))
                + chunk_data
            )
            packets.append((0x21, data))

        return packets

    def _build_block_entities(self) -> list[Packet]:
        """Build Update Block Entity packets (0x35)."""
        packets: list[Packet] = []
        for (x, y, z), block_entity in self.block_entities.items():
            data = (
                Position.pack((x, y, z))
                + UnsignedByte.pack(block_entity.action)
                + block_entity.nbt_data
            )
            packets.append((0x35, data))
        return packets

    def _build_signs(self) -> list[Packet]:
        """Build Update Sign packets (0x33)."""
        packets: list[Packet] = []
        for (x, y, z), sign in self.signs.items():
            data = (
                Position.pack((x, y, z))
                + Chat.pack(sign.lines[0])
                + Chat.pack(sign.lines[1])
                + Chat.pack(sign.lines[2])
                + Chat.pack(sign.lines[3])
            )
            packets.append((0x33, data))
        return packets

    def _build_entity_spawns(self) -> list[Packet]:
        """Build spawn packets for all entities."""
        packets: list[Packet] = []

        for entity in self.entities.values():
            if entity.entity_id == self.player_entity_id:
                continue  # Skip self

            if isinstance(entity, Player):
                packets.append(self._build_spawn_player(entity))
            elif entity.entity_type >= 50 and entity.entity_type < 120:
                # Mob types (50-119)
                packets.append(self._build_spawn_mob(entity))
            else:
                # Objects - skip item entities (type 2) without valid item metadata
                if entity.entity_type == 2:
                    # Item entities need metadata at index 10 with a valid item
                    item_meta = entity.metadata.get(10)
                    if item_meta is None:
                        continue  # Skip - no item metadata
                    if isinstance(item_meta, MetadataValue):
                        if not isinstance(item_meta.value, SlotData):
                            continue  # Skip - invalid metadata type
                        if item_meta.value.item is None:
                            continue  # Skip - empty slot
                    elif isinstance(item_meta, SlotData):
                        if item_meta.item is None:
                            continue  # Skip - empty slot
                    else:
                        continue  # Skip - unknown metadata format
                packets.append(self._build_spawn_object(entity))

        return packets

    def _build_spawn_player(self, player: Player) -> Packet:
        """Build Spawn Player packet (0x0C)."""
        data = (
            VarInt.pack(player.entity_id)
            + self._pack_uuid(player.uuid)
            + Int.pack(int(player.position.x * 32))
            + Int.pack(int(player.position.y * 32))
            + Int.pack(int(player.position.z * 32))
            + Angle.pack(player.rotation.yaw)
            + Angle.pack(player.rotation.pitch)
            + Short.pack(player.current_item)
            + self._pack_metadata(player.metadata)
        )
        return (0x0C, data)

    def _build_spawn_mob(self, entity: Entity) -> Packet:
        """Build Spawn Mob packet (0x0F)."""
        data = (
            VarInt.pack(entity.entity_id)
            + UnsignedByte.pack(entity.entity_type)
            + Int.pack(int(entity.position.x * 32))
            + Int.pack(int(entity.position.y * 32))
            + Int.pack(int(entity.position.z * 32))
            + Angle.pack(entity.rotation.yaw)
            + Angle.pack(entity.rotation.pitch)
            + Angle.pack(entity.head_yaw)
            + Short.pack(int(entity.velocity.x * 8000))
            + Short.pack(int(entity.velocity.y * 8000))
            + Short.pack(int(entity.velocity.z * 8000))
            + self._pack_metadata(entity.metadata)
        )
        return (0x0F, data)

    def _build_spawn_object(self, entity: Entity) -> Packet:
        """Build Spawn Object packet (0x0E)."""
        data = (
            VarInt.pack(entity.entity_id)
            + Byte.pack(entity.entity_type)
            + Int.pack(int(entity.position.x * 32))
            + Int.pack(int(entity.position.y * 32))
            + Int.pack(int(entity.position.z * 32))
            + Angle.pack(entity.rotation.pitch)
            + Angle.pack(entity.rotation.yaw)
            + Int.pack(entity.object_data)
        )
        if entity.object_data != 0:
            data += (
                Short.pack(int(entity.velocity.x * 8000))
                + Short.pack(int(entity.velocity.y * 8000))
                + Short.pack(int(entity.velocity.z * 8000))
            )
        return (0x0E, data)

    def _build_entity_metadata(self) -> list[Packet]:
        """Build Entity Metadata packets (0x1C) for all entities."""
        packets: list[Packet] = []
        for entity in self.entities.values():
            if entity.entity_id == self.player_entity_id:
                continue
            if entity.metadata:
                data = VarInt.pack(entity.entity_id) + self._pack_metadata(
                    entity.metadata
                )
                packets.append((0x1C, data))
        return packets

    def _build_entity_equipment(self) -> list[Packet]:
        """Build Entity Equipment packets (0x04) for all entities."""
        packets: list[Packet] = []
        for entity in self.entities.values():
            if entity.entity_id == self.player_entity_id:
                continue
            equip = entity.equipment
            slots = [
                (EquipmentSlot.HELD, equip.held),
                (EquipmentSlot.BOOTS, equip.boots),
                (EquipmentSlot.LEGGINGS, equip.leggings),
                (EquipmentSlot.CHESTPLATE, equip.chestplate),
                (EquipmentSlot.HELMET, equip.helmet),
            ]
            for slot_id, item in slots:
                if item and item.item:
                    data = (
                        VarInt.pack(entity.entity_id)
                        + Short.pack(slot_id)
                        + Slot.pack(item)
                    )
                    packets.append((0x04, data))
        return packets

    def _build_entity_effects(self) -> list[Packet]:
        """Build Entity Effect packets (0x1D) for all entities."""
        packets: list[Packet] = []
        for entity in self.entities.values():
            if entity.entity_id == self.player_entity_id:
                continue
            for effect in entity.effects.values():
                data = (
                    VarInt.pack(entity.entity_id)
                    + Byte.pack(effect.effect_id)
                    + Byte.pack(effect.amplifier)
                    + VarInt.pack(effect.duration)
                    + Boolean.pack(effect.hide_particles)
                )
                packets.append((0x1D, data))
        return packets

    def _build_entity_properties(self) -> list[Packet]:
        """Build Entity Properties packets (0x20) for all entities."""
        packets: list[Packet] = []
        for entity in self.entities.values():
            if entity.entity_id == self.player_entity_id:
                continue
            if not entity.attributes:
                continue

            data = VarInt.pack(entity.entity_id)
            data += Int.pack(len(entity.attributes))

            for attr in entity.attributes.values():
                data += String.pack(attr.key)
                data += Double.pack(attr.value)
                data += VarInt.pack(len(attr.modifiers))
                for mod in attr.modifiers:
                    data += self._pack_uuid(mod.uuid)
                    data += Double.pack(mod.amount)
                    data += Byte.pack(mod.operation)

            packets.append((0x20, data))
        return packets

    def _build_player_inventory(self) -> Packet:
        """Build Window Items packet (0x30) for player inventory."""
        slots = self.player_inventory.slots
        max_slot = max(slots.keys()) if slots else 44

        data = UnsignedByte.pack(0)  # Window ID 0 = player inventory
        data += Short.pack(max_slot + 1)

        for i in range(max_slot + 1):
            slot_data = slots.get(i, SlotData())
            data += Slot.pack(slot_data)

        return (0x30, data)

    def _build_open_window(self) -> list[Packet]:
        """Build Open Window (0x2D) and Window Items (0x30) packets."""
        packets: list[Packet] = []

        if not self.open_window:
            return packets

        win = self.open_window

        # Open Window packet
        data = (
            UnsignedByte.pack(win.window_id)
            + String.pack(win.window_type)
            + Chat.pack(win.title)
            + UnsignedByte.pack(win.slot_count)
        )
        if win.window_type == "EntityHorse" and win.entity_id is not None:
            data += Int.pack(win.entity_id)
        packets.append((0x2D, data))

        # Window Items packet
        slots = win.slots
        max_slot = max(slots.keys()) if slots else win.slot_count - 1

        items_data = UnsignedByte.pack(win.window_id)
        items_data += Short.pack(max_slot + 1)

        for i in range(max_slot + 1):
            slot_data = slots.get(i, SlotData())
            items_data += Slot.pack(slot_data)

        packets.append((0x30, items_data))

        # Window Properties
        for prop, value in win.properties.items():
            prop_data = (
                UnsignedByte.pack(win.window_id) + Short.pack(prop) + Short.pack(value)
            )
            packets.append((0x31, prop_data))

        return packets

    def _build_statistics(self) -> Packet:
        """Build Statistics packet (0x37)."""
        data = VarInt.pack(len(self.statistics.stats))
        for name, value in self.statistics.stats.items():
            data += String.pack(name) + VarInt.pack(value)
        return (0x37, data)

    def _build_title(self) -> list[Packet]:
        """Build Title packets (0x45)."""
        packets: list[Packet] = []

        # Set times
        times_data = (
            VarInt.pack(TitleAction.SET_TIMES)
            + Int.pack(self.title.fade_in)
            + Int.pack(self.title.stay)
            + Int.pack(self.title.fade_out)
        )
        packets.append((0x45, times_data))

        # Set subtitle (if any)
        if self.title.subtitle:
            subtitle_data = VarInt.pack(TitleAction.SET_SUBTITLE) + Chat.pack(
                self.title.subtitle
            )
            packets.append((0x45, subtitle_data))

        # Set title (triggers display)
        title_data = VarInt.pack(TitleAction.SET_TITLE) + Chat.pack(self.title.title)
        packets.append((0x45, title_data))

        return packets

    def _build_game_state_changes(self) -> list[Packet]:
        """Build Change Game State packets (0x2B) for weather."""
        packets: list[Packet] = []

        if self.is_raining:
            # Begin raining
            data = UnsignedByte.pack(GameStateReason.BEGIN_RAINING) + Float.pack(0.0)
            packets.append((0x2B, data))

            # Rain strength
            if self.rain_strength > 0:
                data = UnsignedByte.pack(GameStateReason.FADE_VALUE) + Float.pack(
                    self.rain_strength
                )
                packets.append((0x2B, data))

        return packets

    def _build_maps(self) -> list[Packet]:
        """Build Map packets (0x34) for all maps."""
        packets: list[Packet] = []

        for map_data in self.maps.values():
            # Build map packet with full data
            data = VarInt.pack(map_data.map_id)
            data += Byte.pack(map_data.scale)
            data += VarInt.pack(len(map_data.icons))

            for icon in map_data.icons:
                dir_type = ((icon.get("direction", 0) & 0x0F) << 4) | (
                    icon.get("type", 0) & 0x0F
                )
                data += Byte.pack(dir_type)
                data += Byte.pack(icon.get("x", 0))
                data += Byte.pack(icon.get("z", 0))

            # Send full map data (128x128)
            data += UnsignedByte.pack(128)  # Columns
            data += UnsignedByte.pack(128)  # Rows
            data += Byte.pack(0)  # X offset
            data += Byte.pack(0)  # Z offset
            data += VarInt.pack(128 * 128)
            data += bytes(map_data.pixels)

            packets.append((0x34, data))

        return packets

    def _build_resource_pack(self) -> Packet:
        """Build Resource Pack Send packet (0x48)."""
        data = String.pack(self.resource_pack.url) + String.pack(
            self.resource_pack.hash
        )
        return (0x48, data)

    def _build_camera(self) -> Packet:
        """Build Camera packet (0x43)."""
        return (0x43, VarInt.pack(self.camera_entity_id or self.player_entity_id))

    def _build_block_break_animations(self) -> list[Packet]:
        """Build Block Break Animation packets (0x25)."""
        packets: list[Packet] = []
        for entity_id, (pos, stage) in self.block_break_animations.items():
            data = (
                VarInt.pack(entity_id)
                + Position.pack((pos.x, pos.y, pos.z))
                + Byte.pack(stage)
            )
            packets.append((0x25, data))
        return packets

    # =========================================================================
    # Packet Building Utilities
    # =========================================================================

    def _pack_uuid(self, uuid_str: str) -> bytes:
        """Pack a UUID string into bytes."""
        return UUID.pack(uuid_mod.UUID(uuid_str))

    def _pack_metadata(self, metadata: dict[int, MetadataValue | Any]) -> bytes:
        """Pack entity metadata into bytes, preserving original types."""
        data = b""

        for index, entry in metadata.items():
            if index < 0:
                continue  # Skip special entries like NBT stored at -1

            # Handle MetadataValue (preferred - preserves type)
            if isinstance(entry, MetadataValue):
                type_id = entry.type_id
                value = entry.value

                if type_id < 0:
                    continue  # Skip special non-protocol entries

                data += UnsignedByte.pack((type_id << 5) | (index & 0x1F))

                if type_id == 0:
                    data += Byte.pack(value)
                elif type_id == 1:
                    data += Short.pack(value)
                elif type_id == 2:
                    data += Int.pack(value)
                elif type_id == 3:
                    data += Float.pack(value)
                elif type_id == 4:
                    data += String.pack(value)
                elif type_id == 5:
                    data += Slot.pack(value)
                elif type_id == 6:
                    data += Int.pack(value.x) + Int.pack(value.y) + Int.pack(value.z)
                elif type_id == 7:
                    data += (
                        Float.pack(value[0])
                        + Float.pack(value[1])
                        + Float.pack(value[2])
                    )
            else:
                # Fallback for raw values (legacy compatibility)
                # This path should be avoided as it guesses types
                value = entry
                if isinstance(value, int):
                    if -128 <= value <= 127:
                        data += UnsignedByte.pack((0 << 5) | (index & 0x1F))
                        data += Byte.pack(value)
                    elif -32768 <= value <= 32767:
                        data += UnsignedByte.pack((1 << 5) | (index & 0x1F))
                        data += Short.pack(value)
                    else:
                        data += UnsignedByte.pack((2 << 5) | (index & 0x1F))
                        data += Int.pack(value)
                elif isinstance(value, float):
                    data += UnsignedByte.pack((3 << 5) | (index & 0x1F))
                    data += Float.pack(value)
                elif isinstance(value, str):
                    data += UnsignedByte.pack((4 << 5) | (index & 0x1F))
                    data += String.pack(value)
                elif isinstance(value, SlotData):
                    data += UnsignedByte.pack((5 << 5) | (index & 0x1F))
                    data += Slot.pack(value)
                elif isinstance(value, Vec3i):
                    data += UnsignedByte.pack((6 << 5) | (index & 0x1F))
                    data += Int.pack(value.x) + Int.pack(value.y) + Int.pack(value.z)
                elif isinstance(value, tuple) and len(value) == 3:
                    data += UnsignedByte.pack((7 << 5) | (index & 0x1F))
                    data += (
                        Float.pack(value[0])
                        + Float.pack(value[1])
                        + Float.pack(value[2])
                    )

        # End of metadata
        data += UnsignedByte.pack(0x7F)
        return data

    def send_update(self) -> list[Packet]:
        """
        Generate a list of packets that would update a client's game state
        to exactly match the current stored state.

        Returns:
            A list of tuples (packet_id, packet_data) that can be sent to a client.
            These should be sent in order to properly synchronize the game state.

        Usage:
            packets = game_state.send_update()
            for packet_id, packet_data in packets:
                client.send_packet(packet_id, packet_data)
        """
        packets: list[Packet] = []

        # 1. Join Game (0x01) - Essential first packet
        packets.append(self._build_join_game())

        # 2. Server Difficulty (0x41)
        packets.append(self._build_server_difficulty())

        # 3. Player Abilities (0x39)
        packets.append(self._build_player_abilities())

        # 4. Held Item Change (0x09)
        packets.append(self._build_held_item_change())

        # 5. Spawn Position (0x05)
        packets.append(self._build_spawn_position())

        # 6. Player Position And Look (0x08)
        packets.append(self._build_player_position_and_look())

        # 7. Update Health (0x06)
        packets.append(self._build_update_health())

        # 8. Set Experience (0x1F)
        packets.append(self._build_set_experience())

        # 9. Time Update (0x03)
        packets.append(self._build_time_update())

        # 10. World Border (0x44) - Initialize
        packets.append(self._build_world_border())

        # 11. Player List Items (0x38) - Add all players
        packets.extend(self._build_player_list_items())

        # 12. Tab Header/Footer (0x47)
        if self.tab_header or self.tab_footer:
            packets.append(self._build_player_list_header_footer())

        # 13. Scoreboard Objectives (0x3B)
        packets.extend(self._build_scoreboard_objectives())

        # 14. Scoreboard Scores (0x3C)
        packets.extend(self._build_scoreboard_scores())

        # 15. Display Scoreboard (0x3D)
        packets.extend(self._build_display_scoreboards())

        # 16. Teams (0x3E)
        packets.extend(self._build_teams())

        # 17. Chunk Data (0x21) - All loaded chunks
        packets.extend(self._build_chunk_data())

        # 18. Block Entities (0x35)
        packets.extend(self._build_block_entities())

        # 19. Signs (0x33)
        packets.extend(self._build_signs())

        # 20. Entities - Spawn all entities
        packets.extend(self._build_entity_spawns())

        # 21. Entity Metadata (0x1C) - For all entities
        packets.extend(self._build_entity_metadata())

        # 22. Entity Equipment (0x04) - For all entities
        packets.extend(self._build_entity_equipment())

        # 23. Entity Effects (0x1D) - For all entities
        packets.extend(self._build_entity_effects())

        # 24. Entity Properties (0x20) - For all entities
        packets.extend(self._build_entity_properties())

        # 25. Window Items (0x30) - Player inventory
        packets.append(self._build_player_inventory())

        # 26. Open Window (0x2D) + Window Items if window is open
        if self.open_window:
            packets.extend(self._build_open_window())

        # 27. Statistics (0x37)
        if self.statistics.stats:
            packets.append(self._build_statistics())

        # 28. Title (0x45) - If visible
        if self.title.visible:
            packets.extend(self._build_title())

        # 29. Game State Changes (0x2B) - Weather
        packets.extend(self._build_game_state_changes())

        # 30. Maps (0x34)
        packets.extend(self._build_maps())

        # 31. Resource Pack (0x48)
        if self.resource_pack.url:
            packets.append(self._build_resource_pack())

        # 32. Camera (0x43) - If spectating another entity
        if self.camera_entity_id and self.camera_entity_id != self.player_entity_id:
            packets.append(self._build_camera())

        # 33. Block Break Animations (0x25)
        packets.extend(self._build_block_break_animations())

        return packets

    def sync_spectator(self, eid: Optional[int] = None) -> list[Packet]:
        """
        To use for broadcasting; generate a list of packets that would update a
        player's view to be a spectator of this game state.

        Some packets are commented out because I copy pasted this from send_update()

        Returns:
            A list of tuples (packet_id, packet_data) that can be sent to a client.
            These should be sent in order to properly synchronize the game state.

        Usage:
            packets = game_state.send_update()
            for packet_id, packet_data in packets:
                client.send_packet(packet_id, packet_data)
        """
        packets: list[Packet] = []

        # 1. Join Game (0x01) - Essential first packet
        packets.append(self._build_join_game(eid, 3))  # spectator

        # 2. Server Difficulty (0x41)
        packets.append(self._build_server_difficulty())

        # 3. Player Abilities (0x39)
        # packets.append(self._build_player_abilities())

        # 4. Held Item Change (0x09)
        # packets.append(self._build_held_item_change())

        # 5. Spawn Position (0x05)
        # packets.append(self._build_spawn_position())

        # 6. Player Position And Look (0x08)
        packets.append(self._build_player_position_and_look())

        # 7. Update Health (0x06)
        # packets.append(self._build_update_health())

        # 8. Set Experience (0x1F)
        # packets.append(self._build_set_experience())

        # 9. Time Update (0x03)
        packets.append(self._build_time_update())

        # 10. World Border (0x44) - Initialize
        packets.append(self._build_world_border())

        # 11. Player List Items (0x38) - Add all players
        packets.extend(self._build_player_list_items())

        # 12. Tab Header/Footer (0x47)
        if self.tab_header or self.tab_footer:
            packets.append(self._build_player_list_header_footer())

        # 13. Scoreboard Objectives (0x3B)
        packets.extend(self._build_scoreboard_objectives())

        # 14. Scoreboard Scores (0x3C)
        packets.extend(self._build_scoreboard_scores())

        # 15. Display Scoreboard (0x3D)
        packets.extend(self._build_display_scoreboards())

        # 16. Teams (0x3E)
        packets.extend(self._build_teams())

        # 17. Chunk Data (0x21) - All loaded chunks
        packets.extend(self._build_chunk_data())

        # 18. Block Entities (0x35)
        packets.extend(self._build_block_entities())

        # 19. Signs (0x33)
        packets.extend(self._build_signs())

        # 20. Entities - Spawn all entities
        packets.extend(self._build_entity_spawns())

        # 21. Entity Metadata (0x1C) - For all entities
        packets.extend(self._build_entity_metadata())

        # 22. Entity Equipment (0x04) - For all entities
        packets.extend(self._build_entity_equipment())

        # 23. Entity Effects (0x1D) - For all entities
        packets.extend(self._build_entity_effects())

        # 24. Entity Properties (0x20) - For all entities
        packets.extend(self._build_entity_properties())

        # 25. Window Items (0x30) - Player inventory
        # packets.append(self._build_player_inventory())

        # 26. Open Window (0x2D) + Window Items if window is open
        # if self.open_window:
        #     packets.extend(self._build_open_window())

        # 27. Statistics (0x37)
        # if self.statistics.stats:
        #     packets.append(self._build_statistics())

        # 28. Title (0x45) - If visible
        if self.title.visible:
            packets.extend(self._build_title())

        # 29. Game State Changes (0x2B) - Weather
        packets.extend(self._build_game_state_changes())

        # 30. Maps (0x34)
        packets.extend(self._build_maps())

        # 31. Resource Pack (0x48)
        if self.resource_pack.url:
            packets.append(self._build_resource_pack())

        # 32. Camera (0x43) - If spectating another entity
        # if self.camera_entity_id and self.camera_entity_id != self.player_entity_id:
        #     packets.append(self._build_camera())

        # 33. Block Break Animations (0x25)
        packets.extend(self._build_block_break_animations())

        return packets

    def sync_broadcast_spectator(self, eid: int) -> list[Packet]:
        """Build packets to sync a broadcast spectator client.

        Broadcast spectators should be presented to the client as being in
        ADVENTURE mode (so they cannot break blocks) but still be allowed to
        fly using vanilla behaviour (double-tap space to start/stop flying).
        This function builds a similar set of packets to `sync_spectator` but:

        - sets gamemode to ADVENTURE (2)
        - includes a Player Abilities packet (0x39) with INVULNERABLE and
          ALLOW_FLYING set, CREATIVE_MODE unset, and FLYING unset so the client
          uses the normal double-tap to start flying behaviour.
        """
        packets: list[Packet] = []

        # 1. Join Game (0x01) - Present as Adventure to prevent block breaking
        packets.append(self._build_join_game(eid, 2))  # adventure

        # 2. Server Difficulty (0x41)
        packets.append(self._build_server_difficulty())

        # 3. Player Abilities (0x39) - INVULNERABLE + ALLOW_FLYING, FLYING unset
        abilities = PlayerAbilityFlags.INVULNERABLE | PlayerAbilityFlags.ALLOW_FLYING
        packets.append(
            (
                0x39,
                Byte.pack(int(abilities))
                + Float.pack(self.flying_speed)
                + Float.pack(self.field_of_view_modifier),
            )
        )

        # 4. Held Item Change (0x09)
        # packets.append(self._build_held_item_change())

        # 5. Spawn Position (0x05)
        # packets.append(self._build_spawn_position())

        # 6. Player Position And Look (0x08)
        packets.append(self._build_player_position_and_look())

        # 7. Update Health (0x06)
        # packets.append(self._build_update_health())

        # 8. Set Experience (0x1F)
        # packets.append(self._build_set_experience())

        # 9. Time Update (0x03)
        packets.append(self._build_time_update())

        # 10. World Border (0x44) - Initialize
        packets.append(self._build_world_border())

        # 11. Player List Items (0x38) - Add all players
        packets.extend(self._build_player_list_items())

        # 12. Tab Header/Footer (0x47)
        if self.tab_header or self.tab_footer:
            packets.append(self._build_player_list_header_footer())

        # 13. Scoreboard Objectives (0x3B)
        packets.extend(self._build_scoreboard_objectives())

        # 14. Scoreboard Scores (0x3C)
        packets.extend(self._build_scoreboard_scores())

        # 15. Display Scoreboard (0x3D)
        packets.extend(self._build_display_scoreboards())

        # 16. Teams (0x3E)
        packets.extend(self._build_teams())

        # 17. Chunk Data (0x21) - All loaded chunks
        packets.extend(self._build_chunk_data())

        # 18. Block Entities (0x35)
        packets.extend(self._build_block_entities())

        # 19. Signs (0x33)
        packets.extend(self._build_signs())

        # 20. Entities - Spawn all entities
        packets.extend(self._build_entity_spawns())

        # 21. Entity Metadata (0x1C) - For all entities
        packets.extend(self._build_entity_metadata())

        # 22. Entity Equipment (0x04) - For all entities
        packets.extend(self._build_entity_equipment())

        # 23. Entity Effects (0x1D) - For all entities
        packets.extend(self._build_entity_effects())

        # 24. Entity Properties (0x20) - For all entities
        packets.extend(self._build_entity_properties())

        # 25. Window Items (0x30) - Player inventory
        # packets.append(self._build_player_inventory())

        # 26. Open Window (0x2D) + Window Items if window is open
        # if self.open_window:
        #     packets.extend(self._build_open_window())

        # 27. Statistics (0x37)
        # if self.statistics.stats:
        #     packets.append(self._build_statistics())

        # 28. Title (0x45) - If visible
        if self.title.visible:
            packets.extend(self._build_title())

        # 29. Game State Changes (0x2B) - Weather
        packets.extend(self._build_game_state_changes())

        # 30. Maps (0x34)
        packets.extend(self._build_maps())

        # 31. Resource Pack (0x48)
        if self.resource_pack.url:
            packets.append(self._build_resource_pack())

        # 32. Camera (0x43) - If spectating another entity
        # if self.camera_entity_id and self.camera_entity_id != self.player_entity_id:
        #     packets.append(self._build_camera())

        # 33. Block Break Animations (0x25)
        packets.extend(self._build_block_break_animations())

        return packets
