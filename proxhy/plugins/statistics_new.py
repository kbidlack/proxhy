"""Statistics checking plugin for Proxhy - Hypixel player stats."""
from __future__ import annotations

import asyncio
import datetime
import json
from typing import TYPE_CHECKING, Dict, List, Optional

import hypixel
from hypixel import Player, PlayerNotFound, InvalidApiKey, KeyRequired, RateLimitError

from ..core import PluginBase
from ..utils.formatting import FormattedPlayer
from ..utils.datatypes import String, TextComponent
from ..utils.errors import CommandException

if TYPE_CHECKING:
    from ..core import ProxhyFramework


class StatisticsPlugin(PluginBase):
    """Plugin for checking Hypixel player statistics."""
    
    @property
    def name(self) -> str:
        return "statistics"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def description(self) -> str:
        return "Provides Hypixel player statistics checking functionality"
    
    async def on_enable(self) -> None:
        """Initialize statistics plugin."""
        # Initialize state
        self.framework.set_state("cached_players", {})
        self.framework.set_state("received_player_stats", set())
        self.framework.set_state("players_with_stats", set())
        
        # Initialize Hypixel client
        api_key = self.framework.get_state("hypixel_api_key")
        if api_key:
            hypixel_client = hypixel.Client(api_key)
            self.framework.set_state("hypixel_client", hypixel_client)
        
        # Register for events
        self.framework.events.on("gamestate.teams.updated", self._on_teams_updated)
        self.framework.events.on("command.stats", self._handle_stats_command)
        
        # Start periodic stats update task
        asyncio.create_task(self._stats_update_loop())
    
    async def on_disable(self) -> None:
        """Clean up statistics plugin."""
        hypixel_client = self.framework.get_state("hypixel_client")
        if hypixel_client:
            await hypixel_client.close()
    
    async def _on_teams_updated(self, teams) -> None:
        """Handle team updates from gamestate plugin."""
        # Extract player names from teams
        players = set()
        for team in teams:
            players.update(team.players)
        
        # Store current players
        self.framework.set_state("current_players", players)
        
        # Trigger stats check for new players
        asyncio.create_task(self._check_new_players(players))
    
    async def _check_new_players(self, players: set) -> None:
        """Check stats for newly discovered players."""
        cached_players = self.framework.get_state("cached_players", {})
        received_stats = self.framework.get_state("received_player_stats", set())
        
        new_players = players - received_stats
        if new_players:
            for player in new_players:
                if player not in cached_players:
                    asyncio.create_task(self._fetch_player_stats(player))
    
    async def _fetch_player_stats(self, player_name: str) -> Optional[Dict]:
        """Fetch player statistics from Hypixel API."""
        hypixel_client = self.framework.get_state("hypixel_client")
        if not hypixel_client:
            return None
        
        try:
            player_data = await hypixel_client.player(player_name)
            if player_data:
                # Cache the player data
                cached_players = self.framework.get_state("cached_players", {})
                cached_players[player_name] = {
                    "data": player_data,
                    "timestamp": datetime.datetime.now(),
                    "uuid": player_data.uuid
                }
                self.framework.set_state("cached_players", cached_players)
                
                # Mark as received
                received_stats = self.framework.get_state("received_player_stats", set())
                received_stats.add(player_name)
                self.framework.set_state("received_player_stats", received_stats)
                
                # Emit event
                await self.framework.events.emit("statistics.player.updated", player_name, player_data)
                
                return player_data
                
        except (PlayerNotFound, InvalidApiKey, KeyRequired, RateLimitError) as e:
            print(f"Failed to fetch stats for {player_name}: {e}")
            return None
    
    async def _handle_stats_command(self, target_player: str = None) -> None:
        """Handle stats command."""
        if not target_player:
            # Use current player list to show stats for all
            current_players = self.framework.get_state("current_players", set())
            for player in current_players:
                await self._display_player_stats(player)
        else:
            await self._display_player_stats(target_player)
    
    async def _display_player_stats(self, player_name: str) -> None:
        """Display formatted statistics for a player."""
        cached_players = self.framework.get_state("cached_players", {})
        
        if player_name not in cached_players:
            # Try to fetch stats first
            player_data = await self._fetch_player_stats(player_name)
        else:
            player_data = cached_players[player_name]["data"]
        
        if not player_data:
            self._send_message(f"Could not find statistics for {player_name}")
            return
        
        # Format and display stats
        try:
            formatted_player = FormattedPlayer(player_data)
            stats_message = formatted_player.format_stats()
            self._send_message(stats_message)
        except Exception as e:
            print(f"Error formatting stats for {player_name}: {e}")
            self._send_message(f"Error displaying statistics for {player_name}")
    
    def _send_message(self, message: str) -> None:
        """Send message to client."""
        proxy = self.framework.proxy
        if hasattr(proxy, 'client'):
            try:
                # Create a chat component
                chat_component = TextComponent(message)
                proxy.client.send_packet(0x02, String(json.dumps(chat_component.to_dict())))
            except Exception as e:
                print(f"Error sending message: {e}")
    
    async def _stats_update_loop(self) -> None:
        """Periodic task to update player statistics."""
        while self.enabled:
            try:
                current_players = self.framework.get_state("current_players", set())
                if current_players:
                    # Update stats for all current players periodically
                    for player in current_players:
                        await self._fetch_player_stats(player)
                        await asyncio.sleep(1)  # Rate limiting
                
                # Wait 60 seconds before next update
                await asyncio.sleep(60)
            except Exception as e:
                print(f"Error in stats update loop: {e}")
                await asyncio.sleep(10)  # Wait before retrying
    
    # Public API methods
    def get_player_stats(self, player_name: str) -> Optional[Dict]:
        """Get cached player statistics."""
        cached_players = self.framework.get_state("cached_players", {})
        return cached_players.get(player_name, {}).get("data")
    
    def get_all_cached_players(self) -> Dict:
        """Get all cached player data."""
        return self.framework.get_state("cached_players", {})
    
    async def refresh_player_stats(self, player_name: str) -> bool:
        """Force refresh of player statistics."""
        player_data = await self._fetch_player_stats(player_name)
        return player_data is not None