"""Simple test plugin without relative imports."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.plugin_system import PluginBase

class TestPlugin(PluginBase):
    """Simple test plugin."""
    
    @property
    def name(self) -> str:
        return "test"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def description(self) -> str:
        return "Simple test plugin for framework validation"
    
    async def on_enable(self) -> None:
        """Enable the test plugin."""
        print(f"Test plugin enabled on framework: {self.framework}")
    
    async def on_disable(self) -> None:
        """Disable the test plugin."""
        print("Test plugin disabled")