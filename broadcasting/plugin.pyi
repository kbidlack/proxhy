from core.plugin import Plugin
from plugins.chat import ChatPluginState
from plugins.gamestate import GameStatePluginState
from plugins.window import WindowPluginState
from proxhy.proxhy import Proxhy

class BroadcastPeerPlugin(
    ChatPluginState, GameStatePluginState, WindowPluginState, Plugin
):
    proxy: Proxhy
    eid: int
