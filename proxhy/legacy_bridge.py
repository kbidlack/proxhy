"""Backward compatibility bridge for existing Proxhy code."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Callable, TYPE_CHECKING

from .core import ProxhyFramework, PluginBase, State
from .core.proxy import Buffer
from .core.datatypes import VarInt, String, UnsignedShort

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter

# Global state to maintain backward compatibility
_current_instance: ProxhyFramework | None = None
_legacy_methods: List[Callable] = []


class ProxyBackwardCompatibilityBridge:
    """Bridge class that provides the old Proxhy interface while using the new framework."""
    
    def __init__(self, framework: ProxhyFramework):
        self.framework = framework
        self._proxy = framework.proxy
        
        # Expose proxy attributes for backward compatibility
        self.client = self._proxy.client
        self.server = getattr(self._proxy, 'server', None)
        self.state = self._proxy.state
        self.open = self._proxy.open
        self.CONNECT_HOST = self._proxy.CONNECT_HOST
        self.username = self._proxy.username
        self.access_token = self._proxy.access_token
        self.uuid = self._proxy.uuid
        
        # Legacy state attributes
        self.entity_id = None
        self.players = set()
        self.players_with_stats = set()
        self.teams = []
        self.game = {}
        self.received_locraw = asyncio.Event()
        self.received_player_stats = set()
        self._cached_players = {}
        self.client_type = "unknown"
        self.game_error = None
        self.hypixel_client = None
        self.nick_team_colors = {}
    
    async def close(self):
        """Close the proxy connection."""
        await self.framework.stop()
    
    # Method to help with legacy method injection
    def add_legacy_method(self, method: Callable):
        """Add a legacy method to this instance."""
        method_name = method.__name__
        setattr(self, method_name, method.__get__(self, self.__class__))


class Proxhy(ProxyBackwardCompatibilityBridge):
    """Backward compatible Proxhy class that uses the new framework."""
    
    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        connect_host: tuple[str, int, str, int] = ("mc.hypixel.net", 25565, "mc.hypixel.net", 25565),
    ):
        # Create framework instance
        from .core import ProxhyFrameworkFactory, plugin_registry
        
        factory = ProxhyFrameworkFactory(plugin_registry)
        framework = factory.create_instance(reader, writer, connect_host)
        
        super().__init__(framework)
        
        # Set global instance for legacy code
        global _current_instance
        _current_instance = framework
        
        # Apply legacy methods that were registered
        for method in _legacy_methods:
            self.add_legacy_method(method)
        
        # Start the framework
        asyncio.create_task(framework.start())


# Legacy decorators for backward compatibility
def on_chat(validator: Callable[[str], bool], source: str, blocking: bool = False):
    """Legacy on_chat decorator - converts to event system."""
    def wrapper(func):
        # Register with event system when instance is available
        def register_chat_listener():
            if _current_instance:
                event_name = f"chat.{source}.message"
                
                async def event_handler(message: str, buff: Buffer):
                    if validator(message):
                        if blocking:
                            await func(_current_instance, message, buff)
                        else:
                            asyncio.create_task(func(_current_instance, message, buff))
                
                _current_instance.events.on(event_name, event_handler)
        
        # Store for later registration
        func._chat_listener_info = (validator, source, blocking, register_chat_listener)
        register_chat_listener()
        return func
    
    return wrapper


# Legacy method system
def method(func):
    """Legacy @method decorator - stores methods for later injection."""
    _legacy_methods.append(func)
    return func


# Backward compatible listener decorators
def listen_client(packet_id: int, state: State = State.PLAY, blocking=False, override=False):
    """Legacy listen_client decorator."""
    def wrapper(func):
        if _current_instance:
            _current_instance.proxy.listeners.register_client_listener(
                packet_id, state, func, blocking, override
            )
        return func
    return wrapper


def listen_server(packet_id: int, state: State = State.PLAY, blocking=False, override=False):
    """Legacy listen_server decorator."""
    def wrapper(func):
        if _current_instance:
            _current_instance.proxy.listeners.register_server_listener(
                packet_id, state, func, blocking, override
            )
        return func
    return wrapper


# Legacy State class (re-export)
from .core.proxy import State

# Legacy imports for backward compatibility
from .utils.datatypes import *
from .utils.mcmodels import *
from .utils.formatting import *
from .utils.errors import *
from .utils.command import *