from core.proxy import Proxy
from plugins.autoboop import AutoboopPlugin
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
    AutoboopPlugin,
    BroadcastPlugin,
    ChatPlugin,
    CommandsPlugin,
    DebugPlugin,
    GameStatePlugin,
    HypixelStatePlugin,
    LoginPlugin,
    MiscPlugin,
    SettingsPlugin,
    SpatialPlugin,
    StatCheckPlugin,
    WindowPlugin,
)


Proxhy = type("Proxhy", (*plugins, Proxy), {})
