# "proxy" for any connected broadcast clients
# we are just reusing proxy code and then omitting the server
# to be able to take advantage of all the prebuilt plugins
# and packet handling stuff from proxy, just for a client connection

from core.proxy import Proxy
from plugins.chat import ChatPlugin
from plugins.gamestate import GameStatePlugin
from plugins.window import WindowPlugin

from .plugins import (
    BroadcastPeerBasePlugin,
    BroadcastPeerCommandsPlugin,
    BroadcastPeerLoginPlugin,
)

broadcast_peer_plugins: tuple[type, ...] = (
    ChatPlugin,
    WindowPlugin,
    GameStatePlugin,
    BroadcastPeerLoginPlugin,
    BroadcastPeerBasePlugin,
    BroadcastPeerCommandsPlugin,
)

BroadcastPeerProxy = type("BroadcastPeerProxy", (*broadcast_peer_plugins, Proxy), {})
