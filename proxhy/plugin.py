import logging

from petty.endpoints import Proxy
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
from plugins.slashproxhy import SlashProxhy
from plugins.sound import SoundPlugin
from plugins.spatial import SpatialPlugin
from plugins.statcheck import StatCheckPlugin
from plugins.statcheck.command import StatcheckCommandPlugin
from plugins.window import WindowPlugin


class ProxhyPlugin(  # type: ignore
    AutoboopPlugin,
    BroadcastPlugin,
    ChatPlugin,
    CommandsPlugin,
    DebugPlugin,
    GameStatePlugin,
    HypixelStatePlugin,
    LoginPlugin,
    MiscPlugin,
    SettingsPlugin,
    SlashProxhy,
    SoundPlugin,
    SpatialPlugin,
    StatCheckPlugin,
    StatcheckCommandPlugin,
    WindowPlugin,
    Proxy,
):
    FAKE_CONNECT_HOST: tuple[str, int]
    dev_mode: bool
    logger: logging.LoggerAdapter
