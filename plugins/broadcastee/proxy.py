from plugins.chat import ChatPlugin
from plugins.commands import CommandsPlugin
from plugins.settings import SettingsPlugin
from plugins.window import WindowPlugin

from .plugins import BroadcasteeClosePlugin

broadcastee_plugin_list: tuple[type, ...] = (
    BroadcasteeClosePlugin,
    ChatPlugin,
    CommandsPlugin,
    SettingsPlugin,
    WindowPlugin,
)
