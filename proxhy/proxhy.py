from core.proxy import Proxy
from plugins.broadcast import BroadcastPlugin
from plugins.chat import ChatPlugin
from plugins.commands import CommandsPlugin
from plugins.debug import DebugPlugin
from plugins.gamestate import GameStatePlugin
from plugins.hypixelstate import HypixelStatePlugin
from plugins.login import LoginPlugin
from plugins.misc import MiscPlugin
from plugins.settings import SettingsPlugin
from plugins.spatial import SpatialPlugin
from plugins.statcheck import StatCheckPlugin
from plugins.window import WindowPlugin

plugins: tuple[type, ...] = (
    CommandsPlugin,  # Must be first - other plugins depend on command_registry
    BroadcastPlugin,
    ChatPlugin,
    DebugPlugin,
    HypixelStatePlugin,
    LoginPlugin,
    StatCheckPlugin,
    WindowPlugin,
    SettingsPlugin,
    SpatialPlugin,
    MiscPlugin,
    GameStatePlugin,
)


Proxhy = type("Proxhy", (*plugins, Proxy), {})
