from core.plugin import Plugin
from plugins.autoboop import AutoboopPluginState
from plugins.broadcast import BroadcastPluginState
from plugins.chat import ChatPluginState
from plugins.commands import CommandsPluginState
from plugins.debug import DebugPluginState
from plugins.gamestate import GameStatePluginState
from plugins.hypixelstate import HypixelStatePluginState
from plugins.login import LoginPluginState
from plugins.misc import MiscPluginState
from plugins.settings import SettingsPluginState
from plugins.spatial import SpatialPluginState
from plugins.statcheck import StatCheckPluginState
from plugins.window import WindowPluginState

class ProxhyPlugin(
    AutoboopPluginState,
    BroadcastPluginState,
    ChatPluginState,
    CommandsPluginState,
    DebugPluginState,
    GameStatePluginState,
    HypixelStatePluginState,
    LoginPluginState,
    MiscPluginState,
    SettingsPluginState,
    SpatialPluginState,
    StatCheckPluginState,
    WindowPluginState,
    Plugin,
):
    FAKE_CONNECT_HOST: tuple[str, int]

    dev_mode: bool
