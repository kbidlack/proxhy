from __future__ import annotations

from core.proxy import Proxy
from plugins.chat import ChatPlugin
from plugins.commands import CommandsPlugin
from plugins.debug import DebugPlugin
from plugins.hypixelstate import HypixelStatePlugin
from plugins.login import LoginPlugin
from plugins.settings import SettingsPlugin
from plugins.statcheck import StatCheckPlugin
from plugins.window import WindowPlugin
from plugins.spatial import SpatialPlugin

plugins: tuple[type, ...] = (
    ChatPlugin,
    CommandsPlugin,
    DebugPlugin,
    HypixelStatePlugin,
    LoginPlugin,
    StatCheckPlugin,
    WindowPlugin,
    SettingsPlugin,
    SpatialPlugin,
)

Proxhy = type("Proxhy", (*plugins, Proxy), {})
