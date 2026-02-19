# "proxy" for any connected broadcast clients
# we are just reusing proxy code and then omitting the server
# to be able to take advantage of all the prebuilt plugins
# and packet handling stuff from proxy, just for a client connection


from core.proxy import Proxy
from plugins.chat import ChatPlugin
from plugins.gamestate import GameStatePlugin
from plugins.window import WindowPlugin

from .plugins.base import BroadcastPeerBasePlugin
from .plugins.commands import BroadcastPeerCommandsPlugin
from .plugins.login import BroadcastPeerLoginPlugin
from .plugins.settings import BroadcastPeerSettingsPlugin
from .plugins.spectate import BroadcastPeerSpectatePlugin


class BroadcastPeerProxy(
    ChatPlugin,
    WindowPlugin,
    GameStatePlugin,
    BroadcastPeerLoginPlugin,
    BroadcastPeerBasePlugin,
    BroadcastPeerCommandsPlugin,
    BroadcastPeerSettingsPlugin,
    BroadcastPeerSpectatePlugin,
    Proxy,
): ...
