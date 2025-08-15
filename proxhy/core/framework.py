"""Core framework for Proxhy - supports multiple instances."""
from __future__ import annotations

import asyncio
from typing import Dict, List, Any, Tuple
from asyncio import StreamReader, StreamWriter

from .events import EventEmitter
from .plugin_system import PluginRegistry, PluginBase
from .proxy import Proxy, State


class ProxhyFramework:
    """Framework class that can be instantiated multiple times."""
    
    def __init__(
        self, 
        reader: StreamReader,
        writer: StreamWriter,
        connect_host: Tuple[str, int, str, int] = ("mc.hypixel.net", 25565, "mc.hypixel.net", 25565),
        plugin_registry: PluginRegistry | None = None
    ):
        # Core proxy functionality
        self.proxy = Proxy(reader, writer, connect_host)
        
        # Instance-specific event system
        self.events = EventEmitter()
        
        # Plugin management
        self.plugin_registry = plugin_registry or PluginRegistry()
        self.plugins: Dict[str, PluginBase] = {}
        
        # Instance-specific state
        self.state: Dict[str, Any] = {}
        self._running = False
    
    async def start(self) -> None:
        """Start the framework instance."""
        if self._running:
            return
        
        self._running = True
        
        # Enable all plugins
        for plugin in self.plugins.values():
            await plugin.enable()
        
        # Emit start event
        await self.events.emit('framework.start', self)
    
    async def stop(self) -> None:
        """Stop the framework instance."""
        if not self._running:
            return
        
        self._running = False
        
        # Disable all plugins
        for plugin in self.plugins.values():
            await plugin.disable()
        
        # Close proxy connection
        await self.proxy.close()
        
        # Emit stop event
        await self.events.emit('framework.stop', self)
    
    def load_plugin(self, name: str) -> PluginBase | None:
        """Load a plugin by name."""
        if name in self.plugins:
            return self.plugins[name]
        
        plugin = self.plugin_registry.create_plugin(name, self)
        if plugin:
            self.plugins[name] = plugin
        return plugin
    
    def unload_plugin(self, name: str) -> None:
        """Unload a plugin."""
        if name in self.plugins:
            asyncio.create_task(self.plugins[name].disable())
            del self.plugins[name]
    
    def get_plugin(self, name: str) -> PluginBase | None:
        """Get a loaded plugin."""
        return self.plugins.get(name)
    
    def set_state(self, key: str, value: Any) -> None:
        """Set instance-specific state."""
        self.state[key] = value
    
    def get_state(self, key: str, default: Any = None) -> Any:
        """Get instance-specific state."""
        return self.state.get(key, default)
    
    @property
    def running(self) -> bool:
        """Check if framework is running."""
        return self._running


class ProxhyFrameworkFactory:
    """Factory for creating ProxhyFramework instances."""
    
    def __init__(self, plugin_registry: PluginRegistry | None = None):
        self.plugin_registry = plugin_registry or PluginRegistry()
        self.instances: List[ProxhyFramework] = []
    
    def create_instance(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        connect_host: Tuple[str, int, str, int] = ("mc.hypixel.net", 25565, "mc.hypixel.net", 25565),
        plugins: List[str] | None = None
    ) -> ProxhyFramework:
        """Create a new framework instance."""
        instance = ProxhyFramework(reader, writer, connect_host, self.plugin_registry)
        
        # Load specified plugins
        if plugins:
            for plugin_name in plugins:
                instance.load_plugin(plugin_name)
        
        self.instances.append(instance)
        return instance
    
    def remove_instance(self, instance: ProxhyFramework) -> None:
        """Remove a framework instance."""
        if instance in self.instances:
            self.instances.remove(instance)
    
    def get_instances(self) -> List[ProxhyFramework]:
        """Get all framework instances."""
        return self.instances.copy()
    
    async def shutdown_all(self) -> None:
        """Shutdown all framework instances."""
        for instance in self.instances:
            await instance.stop()
        self.instances.clear()