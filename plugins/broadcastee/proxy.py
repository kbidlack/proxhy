from plugins.chat import ChatPlugin
from plugins.commands import CommandsPlugin
from plugins.gamestate import GameStatePlugin
from plugins.settings import SettingsPlugin
from plugins.window import WindowPlugin

from .plugins import BroadcasteeClosePlugin, BroadcasteeSettingsPlugin

broadcastee_plugin_list: tuple[type, ...] = (
    BroadcasteeClosePlugin,
    BroadcasteeSettingsPlugin,
    ChatPlugin,
    CommandsPlugin,
    SettingsPlugin,
    WindowPlugin,
    GameStatePlugin,
)

# constructed in broadcaster.py
