"""Plugin loader with auto-discovery capabilities."""
from __future__ import annotations

import importlib
import inspect
import os
import sys
from pathlib import Path
from typing import List, Type, Dict, Any

from .plugin_system import PluginBase, plugin_registry


class PluginLoader:
    """Auto-discovery and loading of plugins."""
    
    def __init__(self, plugin_directories: List[str] | None = None):
        self.plugin_directories = plugin_directories or []
        self._loaded_modules: Dict[str, Any] = {}
    
    def add_plugin_directory(self, directory: str) -> None:
        """Add a directory to search for plugins."""
        if directory not in self.plugin_directories:
            self.plugin_directories.append(directory)
    
    def discover_plugins(self) -> List[str]:
        """Discover all available plugins in the plugin directories."""
        discovered = []
        
        for directory in self.plugin_directories:
            path = Path(directory)
            if not path.exists() or not path.is_dir():
                continue
            
            for item in path.iterdir():
                if item.is_file() and item.suffix == '.py' and not item.name.startswith('_'):
                    plugin_name = item.stem
                    discovered.append(plugin_name)
                elif item.is_dir() and not item.name.startswith('_') and (item / '__init__.py').exists():
                    plugin_name = item.name
                    discovered.append(plugin_name)
        
        return discovered
    
    def load_plugin_module(self, plugin_name: str, module_path: str) -> Any:
        """Load a plugin module by name and path."""
        if plugin_name in self._loaded_modules:
            return self._loaded_modules[plugin_name]
        
        spec = importlib.util.spec_from_file_location(plugin_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load plugin module: {plugin_name}")
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[plugin_name] = module
        spec.loader.exec_module(module)
        
        self._loaded_modules[plugin_name] = module
        return module
    
    def find_plugin_classes(self, module: Any) -> List[Type[PluginBase]]:
        """Find all plugin classes in a module."""
        plugin_classes = []
        
        for name, obj in inspect.getmembers(module):
            if (inspect.isclass(obj) and 
                issubclass(obj, PluginBase) and 
                obj is not PluginBase):
                plugin_classes.append(obj)
        
        return plugin_classes
    
    def load_plugins_from_directory(self, directory: str) -> List[Type[PluginBase]]:
        """Load all plugins from a specific directory."""
        loaded_classes = []
        path = Path(directory)
        
        if not path.exists() or not path.is_dir():
            return loaded_classes
        
        for item in path.iterdir():
            if item.is_file() and item.suffix == '.py' and not item.name.startswith('_'):
                plugin_name = item.stem
                try:
                    module = self.load_plugin_module(plugin_name, str(item))
                    classes = self.find_plugin_classes(module)
                    loaded_classes.extend(classes)
                except Exception as e:
                    print(f"Failed to load plugin {plugin_name}: {e}")
            
            elif item.is_dir() and not item.name.startswith('_') and (item / '__init__.py').exists():
                plugin_name = item.name
                try:
                    module = self.load_plugin_module(plugin_name, str(item / '__init__.py'))
                    classes = self.find_plugin_classes(module)
                    loaded_classes.extend(classes)
                except Exception as e:
                    print(f"Failed to load plugin {plugin_name}: {e}")
        
        return loaded_classes
    
    def register_discovered_plugins(self) -> List[str]:
        """Register all discovered plugins with the plugin registry."""
        registered = []
        
        for directory in self.plugin_directories:
            plugin_classes = self.load_plugins_from_directory(directory)
            for plugin_class in plugin_classes:
                plugin_registry.register_plugin_class(plugin_class)
                registered.append(plugin_class.__name__)
        
        return registered
    
    def reload_plugin(self, plugin_name: str) -> bool:
        """Reload a plugin (hot-reload for development)."""
        if plugin_name in self._loaded_modules:
            try:
                module = self._loaded_modules[plugin_name]
                importlib.reload(module)
                
                # Re-register plugin classes
                classes = self.find_plugin_classes(module)
                for plugin_class in classes:
                    plugin_registry.register_plugin_class(plugin_class)
                
                return True
            except Exception as e:
                print(f"Failed to reload plugin {plugin_name}: {e}")
                return False
        return False


# Global plugin loader
plugin_loader = PluginLoader()