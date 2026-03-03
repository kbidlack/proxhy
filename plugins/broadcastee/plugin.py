from core.plugin import Plugin
from plugins.broadcastee.plugins import (
    BroadcasteeClosePlugin,
    BroadcasteeCommandsPlugin,
    BroadcasteeSettingsPlugin,
)
from plugins.chat import ChatPlugin
from plugins.gamestate import GameStatePlugin
from plugins.settings import SettingsPlugin
from plugins.window import WindowPlugin


class BroadcasteePlugin(
    BroadcasteeClosePlugin,
    BroadcasteeCommandsPlugin,
    BroadcasteeSettingsPlugin,
    ChatPlugin,
    GameStatePlugin,
    SettingsPlugin,
    WindowPlugin,
    Plugin,
):
    pass
