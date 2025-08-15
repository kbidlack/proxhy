"""Command handling plugin for Proxhy."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict, List, Callable, Any

from ..core import PluginBase, State
from ..core.datatypes import Buffer, String
from ..utils.errors import CommandException

if TYPE_CHECKING:
    from ..core import ProxhyFramework


class CommandsPlugin(PluginBase):
    """Plugin for handling chat commands."""
    
    @property
    def name(self) -> str:
        return "commands"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def description(self) -> str:
        return "Handles chat commands and provides command framework"
    
    def __init__(self, framework: ProxhyFramework):
        super().__init__(framework)
        self.commands: Dict[str, Callable] = {}
        self.command_aliases: Dict[str, str] = {}
    
    async def on_enable(self) -> None:
        """Initialize command handling."""
        # Register packet handlers for client chat
        proxy = self.framework.proxy
        proxy.listeners.register_client_listener(
            0x01, State.PLAY, self._handle_client_chat, blocking=False
        )
        
        # Register built-in commands
        self.register_command("help", self._help_command, ["h"])
        self.register_command("stats", self._stats_command, ["s", "stat"])
        self.register_command("reload", self._reload_command, ["rl"])
        
        # Listen for command registration events from other plugins
        self.framework.events.on("command.register", self._on_command_register)
    
    async def _handle_client_chat(self, proxy, buff: Buffer) -> None:
        """Handle client chat messages to detect commands."""
        try:
            message = buff.unpack(String)
            
            if message.startswith("/proxhy ") or message.startswith("/p "):
                # Extract command and arguments
                parts = message.split(" ", 2)
                if len(parts) >= 2:
                    command = parts[1].lower()
                    args = parts[2] if len(parts) > 2 else ""
                    
                    # Process the command
                    await self._execute_command(command, args)
                    return  # Don't forward to server
            
        except Exception as e:
            print(f"Error handling client chat: {e}")
        
        # Forward to server if not a proxhy command
        proxy.server.send_packet(0x01, buff.getvalue())
    
    async def _execute_command(self, command: str, args: str) -> None:
        """Execute a registered command."""
        # Check aliases
        actual_command = self.command_aliases.get(command, command)
        
        if actual_command in self.commands:
            try:
                # Parse arguments
                arg_list = self._parse_arguments(args) if args else []
                
                # Execute command
                await self.commands[actual_command](*arg_list)
                
                # Emit command execution event
                await self.framework.events.emit(f"command.{actual_command}", *arg_list)
                
            except CommandException as e:
                self._send_message(f"Command error: {e}")
            except Exception as e:
                print(f"Error executing command '{command}': {e}")
                self._send_message(f"Internal error executing command: {command}")
        else:
            self._send_message(f"Unknown command: {command}. Type '/proxhy help' for available commands.")
    
    def _parse_arguments(self, args_string: str) -> List[str]:
        """Parse command arguments string into a list."""
        # Simple space-based parsing for now
        # Could be enhanced to handle quoted arguments, etc.
        return [arg.strip() for arg in args_string.split() if arg.strip()]
    
    def register_command(self, name: str, handler: Callable, aliases: List[str] = None) -> None:
        """Register a new command."""
        self.commands[name.lower()] = handler
        
        if aliases:
            for alias in aliases:
                self.command_aliases[alias.lower()] = name.lower()
        
        print(f"Registered command: {name} (aliases: {aliases or []})")
    
    def unregister_command(self, name: str) -> None:
        """Unregister a command."""
        name_lower = name.lower()
        if name_lower in self.commands:
            del self.commands[name_lower]
            
            # Remove aliases
            aliases_to_remove = [alias for alias, cmd in self.command_aliases.items() if cmd == name_lower]
            for alias in aliases_to_remove:
                del self.command_aliases[alias]
    
    async def _on_command_register(self, name: str, handler: Callable, aliases: List[str] = None) -> None:
        """Handle command registration events from other plugins."""
        self.register_command(name, handler, aliases)
    
    def _send_message(self, message: str) -> None:
        """Send a message to the client."""
        proxy = self.framework.proxy
        try:
            # Create chat component
            import json
            from ..utils.datatypes import TextComponent
            
            chat_component = TextComponent(f"§6[Proxhy]§r {message}")
            proxy.client.send_packet(0x02, String(json.dumps(chat_component.to_dict())))
        except Exception as e:
            print(f"Error sending message: {e}")
    
    # Built-in commands
    async def _help_command(self, *args) -> None:
        """Show available commands."""
        commands_list = list(self.commands.keys())
        commands_list.sort()
        
        self._send_message("Available commands:")
        for i in range(0, len(commands_list), 5):
            chunk = commands_list[i:i+5]
            self._send_message("  " + ", ".join(chunk))
        
        self._send_message("Usage: /proxhy <command> [args] or /p <command> [args]")
    
    async def _stats_command(self, *args) -> None:
        """Trigger statistics display."""
        target_player = args[0] if args else None
        await self.framework.events.emit("command.stats", target_player)
    
    async def _reload_command(self, *args) -> None:
        """Reload plugins (development feature)."""
        plugin_name = args[0] if args else None
        
        if plugin_name:
            # Reload specific plugin
            self._send_message(f"Reloading plugin: {plugin_name}")
            await self.framework.events.emit("plugin.reload", plugin_name)
        else:
            # Reload all plugins
            self._send_message("Reloading all plugins...")
            await self.framework.events.emit("plugin.reload.all")
    
    # Public API
    def get_available_commands(self) -> List[str]:
        """Get list of available commands."""
        return list(self.commands.keys())
    
    def get_command_aliases(self) -> Dict[str, str]:
        """Get command aliases mapping."""
        return self.command_aliases.copy()