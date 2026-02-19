from enum import IntEnum, IntFlag


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
