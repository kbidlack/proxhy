from typing import TYPE_CHECKING

from petty.endpoints import Proxy

from broadcasting.plugins.base import BroadcastPeerBasePlugin
from broadcasting.plugins.commands import BroadcastPeerCommandsPlugin
from broadcasting.plugins.login import BroadcastPeerLoginPlugin
from broadcasting.plugins.settings import BroadcastPeerSettingsPlugin
from broadcasting.plugins.spectate import BroadcastPeerSpectatePlugin
from plugins.chat import ChatPlugin
from plugins.gamestate import GameStatePlugin
from plugins.window import WindowPlugin

if TYPE_CHECKING:
    from proxhy.proxhy import Proxhy


class BroadcastPeerPlugin(
    BroadcastPeerBasePlugin,
    BroadcastPeerCommandsPlugin,
    BroadcastPeerLoginPlugin,
    BroadcastPeerSettingsPlugin,
    BroadcastPeerSpectatePlugin,
    ChatPlugin,
    WindowPlugin,
    GameStatePlugin,
    Proxy,
):
    proxy: Proxhy
    eid: int
