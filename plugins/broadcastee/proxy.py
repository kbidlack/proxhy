from plugins.chat import ChatPlugin

from .plugins import BroadcasteeClosePlugin

broadcastee_plugin_list: tuple[type, ...] = (
    BroadcasteeClosePlugin,
    ChatPlugin,
)
