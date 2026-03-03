from core.net import StreamReader, StreamWriter
from core.proxy import Proxy
from plugins.autoboop import AutoboopPlugin
from plugins.broadcaster import BroadcastPlugin
from plugins.chat import ChatPlugin
from plugins.commands import CommandsPlugin
from plugins.debug import DebugPlugin
from plugins.gamestate import GameStatePlugin
from plugins.hypixelstate import HypixelStatePlugin
from plugins.login import LoginPlugin
from plugins.misc import MiscPlugin
from plugins.settings import SettingsPlugin
from plugins.sound import SoundPlugin
from plugins.spatial import SpatialPlugin
from plugins.statcheck import StatCheckPlugin
from plugins.statcheck.command import StatcheckCommandPlugin
from plugins.window import WindowPlugin
from proxhy.plugin import ProxhyPlugin


class _Proxhy(ProxhyPlugin):
    def __init__(
        # proxy params
        self,
        reader: StreamReader,
        writer: StreamWriter,
        connect_host: tuple[str, int] = (
            "mc.hypixel.net",
            25565,
        ),
        autostart: bool = True,
        # custom proxhy params
        fake_connect_host: tuple[str, int] = (
            "mc.hypixel.net",
            25565,
        ),
        dev_mode: bool = False,
    ):
        super().__init__(reader, writer, connect_host, autostart)
        self.FAKE_CONNECT_HOST = fake_connect_host
        self.dev_mode = dev_mode


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    Proxhy = _Proxhy
else:
    Proxhy = _Proxhy
