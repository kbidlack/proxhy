from dataclasses import dataclass, field
from typing import Any

from numba import float64, int64
from numba.experimental import jitclass

from protocol.datatypes import (
    SlotData,
)

_vec3d_spec = [
    ("x", float64),
    ("y", float64),
    ("z", float64),
]


@jitclass(_vec3d_spec)
class Vec3d:
    """3D position with double precision."""

    x: float
    y: float
    z: float

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x = x
        self.y = y
        self.z = z

    def __sub__(self, other: "Vec3d") -> "Vec3d":
        return Vec3d(self.x - other.x, self.y - other.y, self.z - other.z)

    def __add__(self, other: "Vec3d") -> "Vec3d":
        return Vec3d(self.x + other.x, self.y + other.y, self.z + other.z)

    def __mul__(self, scalar: float) -> "Vec3d":
        return Vec3d(self.x * scalar, self.y * scalar, self.z * scalar)

    def __truediv__(self, scalar: float) -> "Vec3d":
        return Vec3d(self.x / scalar, self.y / scalar, self.z / scalar)

    def __floordiv__(self, scalar: float) -> "Vec3d":
        return Vec3d(self.x // scalar, self.y // scalar, self.z // scalar)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Vec3d):
            return False
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __ne__(self, other: object) -> bool:
        if not isinstance(other, Vec3d):
            return True
        return self.x != other.x or self.y != other.y or self.z != other.z

    def copy(self) -> "Vec3d":
        return Vec3d(self.x, self.y, self.z)


_vec3i_spec = [
    ("x", int64),
    ("y", int64),
    ("z", int64),
]


@jitclass(_vec3i_spec)
class Vec3i:
    """3D position with integer precision."""

    x: int
    y: int
    z: int

    def __init__(self, x: int = 0, y: int = 0, z: int = 0):
        self.x = x
        self.y = y
        self.z = z

    def __sub__(self, other: "Vec3i") -> "Vec3i":
        return Vec3i(self.x - other.x, self.y - other.y, self.z - other.z)

    def __add__(self, other: "Vec3i") -> "Vec3i":
        return Vec3i(self.x + other.x, self.y + other.y, self.z + other.z)

    def __mul__(self, scalar: int) -> "Vec3i":
        return Vec3i(self.x * scalar, self.y * scalar, self.z * scalar)

    def __floordiv__(self, scalar: int) -> "Vec3i":
        return Vec3i(self.x // scalar, self.y // scalar, self.z // scalar)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Vec3i):
            return False
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __ne__(self, other: object) -> bool:
        if not isinstance(other, Vec3i):
            return True
        return self.x != other.x or self.y != other.y or self.z != other.z

    def copy(self) -> "Vec3i":
        return Vec3i(self.x, self.y, self.z)


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

    held: SlotData = field(default_factory=SlotData)
    boots: SlotData = field(default_factory=SlotData)
    leggings: SlotData = field(default_factory=SlotData)
    chestplate: SlotData = field(default_factory=SlotData)
    helmet: SlotData = field(default_factory=SlotData)


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
    properties: list[dict[str, Any]] = field(default_factory=list)


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
