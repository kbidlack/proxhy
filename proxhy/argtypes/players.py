import re
import shelve
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

import hypixel
from core.command import CommandArg, CommandException
from protocol.datatypes import TextComponent
from proxhy.utils import APIClient, PlayerInfo

from ._argtypes import _resolve_in_proxy_chain

if TYPE_CHECKING:
    from broadcasting.proxy import BroadcastPeerProxy
    from core.command import CommandContext


class Player(CommandArg):
    """
    Base class for player argument types.

    Provides shared suggestion logic that includes:
    - Current server players (from proxy.players)
    - Dead/eliminated players (from proxy.all_players if available)

    Subclasses implement their own convert() method for validation.
    """

    name: str
    uuid: str

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        """
        Suggest player names from server player list and dead players.

        Checks for:
        - proxy.players: Current players on server (dict uuid -> name)
        - proxy.all_players: All players including dead (set of names)
        """
        suggestions: set[str] = set()
        partial_lower = partial.lower()

        gamestate = _resolve_in_proxy_chain(ctx.proxy, "gamestate")
        if gamestate is not None and hasattr(gamestate, "player_list"):
            for _, player_info in gamestate.player_list.items():
                if player_info.name.lower().startswith(partial_lower):
                    suggestions.add(player_info.name)

        return sorted(suggestions)

    @classmethod
    @abstractmethod
    async def convert(cls, ctx: CommandContext, value: str) -> Player:
        """Convert a string to a Player instance."""
        ...


class ServerPlayer(Player):
    """
    A player currently on the server.

    This type does NOT validate against any external API - it just checks
    if the player name exists in the current game's player list.
    Useful for commands that work with custom/nicked players.

    Attributes:
        name: The player's display name
        uuid: The player's UUID
    """

    def __init__(self, name: str, uuid: str = ""):
        self.name = name
        self.uuid = uuid

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> ServerPlayer:
        """
        Convert a player name to a ServerPlayer.

        Validates that the player exists in the server's player list
        and retrieves their UUID.

        Raises:
            CommandException: If the player is not found in the server's player list
        """

        proxy = ctx.proxy

        gamestate = _resolve_in_proxy_chain(proxy, "gamestate")
        if gamestate is not None and hasattr(gamestate, "player_list"):
            for uuid, player_info in gamestate.player_list.items():
                if player_info.name.casefold() == value.casefold():
                    return cls(name=player_info.name, uuid=uuid)

        raise CommandException(
            TextComponent("Player '")
            .append(TextComponent(value).color("gold"))
            .append("' not found on the server!")
        )


class BroadcastPlayer(Player):
    def __init__(self, client: BroadcastPeerProxy):
        self.client = client

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> BroadcastPlayer:
        clients: list[BroadcastPeerProxy] = ctx.proxy.clients

        for client in clients:
            if client.username.lower() == value.lower():
                return cls(client=client)

        raise CommandException(
            TextComponent("Player '")
            .append(TextComponent(value).color("gold"))
            .append("' is not in the broadcast!")
        )

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        clients: list[BroadcastPeerProxy] = ctx.proxy.clients
        return sorted(client.username for client in clients)


class MojangPlayer(Player):
    """
    A player validated against the Mojang API.

    This type verifies the player exists and retrieves their UUID.
    Use this when you need a valid Minecraft account but don't need
    Hypixel-specific stats.

    Attributes:
        name: The player's username (properly capitalized from Mojang)
        uuid: The player's Minecraft UUID
    """

    def __init__(self, name: str, uuid: str):
        self.name = name
        self.uuid = uuid

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> MojangPlayer:
        """
        Convert a player name to a MojangPlayer by querying Mojang API.

        Raises:
            CommandException: If the player is not found or API error occurs
        """
        async with APIClient() as client:
            try:
                info: PlayerInfo = await client.get_profile(value)
                return cls(name=info.name, uuid=info.uuid)
            except hypixel.PlayerNotFound:
                raise CommandException(
                    TextComponent("Player '")
                    .append(TextComponent(value).color("gold"))
                    .append("' was not found!")
                )
            except hypixel.RateLimitError:
                raise CommandException(
                    TextComponent(
                        "Rate limited by Mojang API! Please try again later."
                    ).color("red")
                )
            except Exception as e:
                raise CommandException(
                    TextComponent("Failed to look up player: ").append(
                        TextComponent(str(e)).color("gold")
                    )
                )


class HypixelPlayer(Player):
    """
    A player with full Hypixel stats.

    This type queries the Hypixel API and returns a full Player object
    with all available statistics (bedwars, skywars, etc.).

    Attributes:
        All attributes from hypixel.Player, including:
        - name: Player username
        - uuid: Player UUID
        - bedwars: Bedwars stats
        - skywars: Skywars stats
        - etc.
    """

    _player: hypixel.Player

    def __init__(self, player: hypixel.Player):
        self._player = player

    def __getattr__(self, name: str) -> Any:
        # Delegate attribute access to the wrapped Player object.
        return getattr(self._player, name)

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> HypixelPlayer:
        """
        Convert a player name to a HypixelPlayer by querying Hypixel API.

        Requires the proxy to have a hypixel_client attribute.

        Raises:
            CommandException: If the player is not found, API key is invalid, etc.
        """
        client = _resolve_in_proxy_chain(ctx.proxy, "hypixel_client")

        if client is None:
            raise CommandException(
                TextComponent("Hypixel API client not available!").color("red")
            )

        try:
            player = await client.player(value)
            return cls(player)
        except hypixel.PlayerNotFound:
            raise CommandException(
                TextComponent("Player '")
                .append(TextComponent(value).color("gold"))
                .append("' was not found on Hypixel!")
            )
        except hypixel.KeyRequired:
            raise CommandException(
                TextComponent("Hypixel API key not configured!").color("red")
            )
        except hypixel.InvalidApiKey:
            raise CommandException(
                TextComponent("Invalid Hypixel API key!").color("red")
            )
        except hypixel.RateLimitError:
            raise CommandException(
                TextComponent(
                    "Rate limited by Hypixel API! Please try again later."
                ).color("red")
            )
        except Exception as e:
            raise CommandException(
                TextComponent("Failed to fetch player stats: ").append(
                    TextComponent(str(e)).color("gold")
                )
            )


class AutoboopPlayer(HypixelPlayer):
    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        with shelve.open(ctx.proxy.AB_DATA_PATH) as db:
            user_players = db.get(ctx.proxy.username, {})
            user_values = [
                re.sub(r"§.", "", str(u.split(" ")[-1])) for u in user_players.values()
            ]
            return sorted(user_values)
