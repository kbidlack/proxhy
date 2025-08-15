"""Base plugin system for Proxhy framework."""
from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any, Dict, TYPE_CHECKING

from .events import EventEmitter

if TYPE_CHECKING:
    from .framework import ProxhyFramework


class PluginBase(ABC):
    """Base class for all Proxhy plugins."""
    
    def __init__(self, framework: ProxhyFramework):
        self.framework = framework
        self.events = EventEmitter()
        self._enabled = False
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name identifier."""
        pass
    
    @property
    def version(self) -> str:
        """Plugin version."""
        return "1.0.0"
    
    @property
    def description(self) -> str:
        """Plugin description."""
        return ""
    
    @property
    def enabled(self) -> bool:
        """Whether the plugin is enabled."""
        return self._enabled
    
    async def enable(self) -> None:
        """Enable the plugin."""
        if not self._enabled:
            await self.on_enable()
            self._enabled = True
    
    async def disable(self) -> None:
        """Disable the plugin."""
        if self._enabled:
            await self.on_disable()
            self._enabled = False
    
    async def on_enable(self) -> None:
        """Called when plugin is enabled. Override in subclasses."""
        pass
    
    async def on_disable(self) -> None:
        """Called when plugin is disabled. Override in subclasses."""
        pass
    
    def get_config(self) -> Dict[str, Any]:
        """Get plugin configuration."""
        return {}
    
    def set_config(self, config: Dict[str, Any]) -> None:
        """Set plugin configuration."""
        pass


class PluginRegistry:
    """Registry for managing plugins."""
    
    def __init__(self):
        self._plugins: Dict[str, PluginBase] = {}
        self._plugin_classes: Dict[str, type[PluginBase]] = {}
    
    def register_plugin_class(self, plugin_class: type[PluginBase]) -> None:
        """Register a plugin class."""
        # Get the plugin name from an instance (temporary)
        temp_instance = plugin_class(None)  # type: ignore
        name = temp_instance.name
        self._plugin_classes[name] = plugin_class
    
    def create_plugin(self, name: str, framework: ProxhyFramework) -> PluginBase | None:
        """Create a plugin instance."""
        if name in self._plugin_classes:
            plugin = self._plugin_classes[name](framework)
            self._plugins[name] = plugin
            return plugin
        return None
    
    def get_plugin(self, name: str) -> PluginBase | None:
        """Get a plugin instance by name."""
        return self._plugins.get(name)
    
    def get_all_plugins(self) -> Dict[str, PluginBase]:
        """Get all plugin instances."""
        return self._plugins.copy()
    
    def remove_plugin(self, name: str) -> None:
        """Remove a plugin instance."""
        if name in self._plugins:
            del self._plugins[name]
    
    def list_available_plugins(self) -> list[str]:
        """List all available plugin classes."""
        return list(self._plugin_classes.keys())
    
    def list_loaded_plugins(self) -> list[str]:
        """List all loaded plugin instances."""
        return list(self._plugins.keys())


# Global plugin registry
plugin_registry = PluginRegistry()