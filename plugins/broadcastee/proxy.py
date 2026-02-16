from plugins.chat import ChatPlugin
from plugins.gamestate import GameStatePlugin
from plugins.settings import SettingsPlugin
from plugins.window import WindowPlugin

from .plugins import (
    BroadcasteeClosePlugin,
    BroadcasteeCommandsPlugin,
    BroadcasteeSettingsPlugin,
)

broadcastee_plugin_list: tuple[type, ...] = (
    BroadcasteeClosePlugin,
    BroadcasteeSettingsPlugin,
    BroadcasteeCommandsPlugin,
    ChatPlugin,
    SettingsPlugin,
    WindowPlugin,
    GameStatePlugin,
)

# constructed in broadcaster.py
