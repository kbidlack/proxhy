"""Game state management plugin for Proxhy."""
from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Dict, Set

from ..core import PluginBase, State
from ..core.datatypes import Buffer, Byte, String, VarInt
from ..utils.mcmodels import Team

if TYPE_CHECKING:
    from ..core import ProxhyFramework


class GameStatePlugin(PluginBase):
    """Plugin for managing game state information."""
    
    @property
    def name(self) -> str:
        return "gamestate"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def description(self) -> str:
        return "Manages game state including teams and location information"
    
    async def on_enable(self) -> None:
        """Initialize game state management when plugin is enabled."""
        # Initialize state
        self.framework.set_state("teams", [])
        self.framework.set_state("game", {})
        self.framework.set_state("received_locraw", asyncio.Event())
        
        # Register packet handlers
        proxy = self.framework.proxy
        proxy.listeners.register_server_listener(
            0x3E, State.PLAY, self._handle_teams_packet, blocking=False
        )
        proxy.listeners.register_server_listener(
            0x02, State.PLAY, self._handle_server_chat, blocking=False
        )
        
        # Register for events
        self.framework.events.on("packet.server.teams", self._update_teams)
        self.framework.events.on("chat.server.locraw", self._on_chat_locraw)
    
    async def _handle_teams_packet(self, proxy, buff: Buffer) -> None:
        """Handle teams packet from server."""
        # Emit event for teams processing
        await self.framework.events.emit("packet.server.teams", proxy, buff)
    
    async def _handle_server_chat(self, proxy, buff: Buffer) -> None:
        """Handle server chat messages."""
        # Parse chat message and check for locraw data
        try:
            chat_data = buff.unpack(String) # Chat component as JSON string
            message = self._extract_message_text(chat_data)
            
            if message and re.match(r"^\\{.*\\}$", message):
                await self.framework.events.emit("chat.server.locraw", message, buff)
        except Exception as e:
            print(f"Error processing server chat: {e}")
    
    def _extract_message_text(self, chat_json: str) -> str:
        """Extract plain text from chat component JSON."""
        try:
            chat_data = json.loads(chat_json)
            if isinstance(chat_data, str):
                return chat_data
            elif isinstance(chat_data, dict):
                return chat_data.get("text", "")
            return ""
        except (json.JSONDecodeError, TypeError):
            return chat_json  # Return as-is if not JSON
    
    async def _update_teams(self, proxy, buff: Buffer) -> None:
        """Update team information."""
        teams = self.framework.get_state("teams", [])
        
        name = buff.unpack(String)
        mode = buff.unpack(Byte)

        # team creation
        if mode == 0:
            display_name = buff.unpack(String)
            prefix = buff.unpack(String)
            suffix = buff.unpack(String)
            friendly_fire = buff.unpack(Byte)
            name_tag_visibility = buff.unpack(String)
            color = buff.unpack(Byte)

            player_count = buff.unpack(VarInt)
            players = set()
            for _ in range(player_count):
                players.add(buff.unpack(String))

            # Create new team
            team = Team(
                name,
                display_name,
                prefix,
                suffix,
                friendly_fire,
                name_tag_visibility,
                color,
                players,
            )
            teams.append(team)
            
        # team removal
        elif mode == 1:
            # Remove team by name
            teams[:] = [team for team in teams if team.name != name]
            
        # team information update
        elif mode == 2:
            team = self._find_team_by_name(teams, name)
            if team:
                team.display_name = buff.unpack(String)
                team.prefix = buff.unpack(String)
                team.suffix = buff.unpack(String)
                team.friendly_fire = buff.unpack(Byte)
                team.name_tag_visibility = buff.unpack(String)
                team.color = buff.unpack(Byte)
                
        # player add/remove
        elif mode == 3 or mode == 4:
            player_count = buff.unpack(VarInt)
            for _ in range(player_count):
                player = buff.unpack(String)
                team = self._find_team_by_name(teams, name)
                if team:
                    if mode == 3:  # add player
                        team.players.add(player)
                    else:  # remove player
                        team.players.discard(player)

        # Update state
        self.framework.set_state("teams", teams)
        
        # Emit event for other plugins
        await self.framework.events.emit("gamestate.teams.updated", teams)
    
    def _find_team_by_name(self, teams, name: str) -> Team | None:
        """Find a team by name."""
        for team in teams:
            if team.name == name:
                return team
        return None
    
    async def _on_chat_locraw(self, message: str, buff: Buffer) -> None:
        """Handle locraw chat messages."""
        received_locraw = self.framework.get_state("received_locraw")
        
        if not received_locraw.is_set():
            if "limbo" in message:  # sometimes returns limbo right when you join
                teams = self.framework.get_state("teams", [])
                if not teams:  # probably in limbo
                    return
                else:
                    # Try again
                    client_type = self.framework.get_state("client_type", "unknown")
                    if client_type != "lunar":
                        await asyncio.sleep(0.1)
                        # Send locraw command again
                        proxy = self.framework.proxy
                        proxy.server.send_packet(0x01, String("/locraw"))
                        return
            else:
                received_locraw.set()
                self._update_game(json.loads(message))
        else:
            self._update_game(json.loads(message))
    
    def _update_game(self, game: dict) -> None:
        """Update game information."""
        current_game = self.framework.get_state("game", {})
        current_game.update(game)
        self.framework.set_state("game", current_game)
        
        # Emit event for other plugins
        asyncio.create_task(
            self.framework.events.emit("gamestate.game.updated", current_game)
        )
        
        if game.get("mode"):
            # Update request game info if available
            rq_game = self.framework.get_state("rq_game", {})
            rq_game.update(game)
            self.framework.set_state("rq_game", rq_game)
    
    # Public API methods for other plugins
    def get_teams(self) -> list:
        """Get current teams."""
        return self.framework.get_state("teams", [])
    
    def get_game(self) -> dict:
        """Get current game information."""
        return self.framework.get_state("game", {})
    
    def get_team_by_player(self, player_name: str) -> Team | None:
        """Find which team a player is on."""
        teams = self.get_teams()
        for team in teams:
            if player_name in team.players:
                return team
        return None