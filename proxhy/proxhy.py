from __future__ import annotations

from core.proxy import Proxy
from plugins.chat import ChatPlugin
from plugins.commands import CommandsPlugin
from plugins.debug import DebugPlugin
from plugins.gamestate import GameStatePlugin
from plugins.login import LoginPlugin
from plugins.statcheck import StatCheckPlugin
from plugins.window import WindowPlugin

plugins: tuple[type, ...] = (
    ChatPlugin,
    CommandsPlugin,
    DebugPlugin,
    GameStatePlugin,
    LoginPlugin,
    StatCheckPlugin,
    WindowPlugin,
)

Proxhy = type("Proxhy", (*plugins, Proxy), {})
