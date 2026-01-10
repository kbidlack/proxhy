"""
Custom argument types for the command system.

These types can be used in command signatures to automatically convert
and validate string arguments, as well as provide tab completion suggestions.

Example:
    @command("stats")
    async def _command_stats(self, player: HypixelPlayer):
        return f"FKDR: {player.bedwars.fkdr}"
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

import hypixel

from protocol.datatypes import TextComponent
from proxhy.command import CommandArg
from proxhy.errors import CommandException
from proxhy.utils import PlayerInfo, _Client

if TYPE_CHECKING:
    from core.settings import Setting, SettingGroup


def _resolve_in_proxy_chain(obj: Any, attr: str) -> Any:
    """
    Search for attribute `attr` on `obj` and up the `.proxy` chain.
    Returns the attribute value if found, otherwise None.
    Prevents infinite loops by tracking visited objects.
    """
    # this is so stupid but it works lmao
    seen = set()
    current = obj
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if hasattr(current, attr):
            return getattr(current, attr)
        current = getattr(current, "proxy", None)
    return None


# =============================================================================
# Base Player Type
# =============================================================================


class Player(CommandArg):
    """
    Base class for player argument types.

    Provides shared suggestion logic that includes:
    - Current server players (from proxy.players)
    - Dead/eliminated players (from proxy.all_players if available)

    Subclasses implement their own convert() method for validation.
    """

    name: str
    uuid: str | None

    @classmethod
    async def suggest(cls, proxy: Any, partial: str) -> list[str]:
        """
        Suggest player names from server player list and dead players.

        Checks for:
        - proxy.players: Current players on server (dict uuid -> name)
        - proxy.all_players: All players including dead (set of names)
        """
        suggestions: set[str] = set()
        partial_lower = partial.lower()

        # Try to find all known players first on the proxy chain
        all_players = _resolve_in_proxy_chain(proxy, "all_players")
        if isinstance(all_players, (set, list)):
            for name in all_players:
                if name.lower().startswith(partial_lower):
                    suggestions.add(name)
        else:
            # Fallback to the active players dict (uuid -> name)
            players = _resolve_in_proxy_chain(proxy, "players")
            if isinstance(players, dict):
                for name in players.values():
                    if name.lower().startswith(partial_lower):
                        suggestions.add(name)

        return sorted(suggestions)

    @classmethod
    @abstractmethod
    async def convert(cls, proxy: Any, value: str) -> Player:
        """Convert a string to a Player instance."""
        ...


# =============================================================================
# Player Types
# =============================================================================


class ServerPlayer(Player):
    """
    A player currently on the server.

    This type does NOT validate against any external API - it just checks
    if the player name exists in the current game's player list.
    Useful for commands that work with custom/nicked players.

    Attributes:
        name: The player's display name
        uuid: The player's UUID (if known from the server)
    """

    def __init__(self, name: str, uuid: str | None = None):
        self.name = name
        self.uuid = uuid

    @classmethod
    async def convert(cls, proxy: Any, value: str) -> ServerPlayer:
        """
        Convert a player name to a ServerPlayer.

        Validates that the player exists in the server's player list
        and retrieves their UUID.

        Raises:
            CommandException: If the player is not found in the server's player list
        """
        from proxhy.errors import CommandException

        # Above all prefer all players
        if hasattr(proxy, "all_players"):
            return proxy

        gamestate = _resolve_in_proxy_chain(proxy, "gamestate")
        if gamestate is not None and hasattr(gamestate, "player_list"):
            for uuid, player_info in gamestate.player_list.items():
                if player_info.name.casefold() == value.casefold():
                    return cls(name=player_info.name, uuid=uuid)

        players = _resolve_in_proxy_chain(proxy, "players")
        if isinstance(players, dict):
            for uuid, name in players.items():
                if name.casefold() == value.casefold():
                    return cls(name=name, uuid=uuid)

        raise CommandException(
            TextComponent("Player '")
            .append(TextComponent(value).color("gold"))
            .append("' not found on the server!")
        )


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
    async def convert(cls, proxy: Any, value: str) -> MojangPlayer:
        """
        Convert a player name to a MojangPlayer by querying Mojang API.

        Raises:
            CommandException: If the player is not found or API error occurs
        """
        async with _Client() as client:
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
    async def convert(cls, proxy: Any, value: str) -> HypixelPlayer:
        """
        Convert a player name to a HypixelPlayer by querying Hypixel API.

        Requires the proxy to have a hypixel_client attribute.

        Raises:
            CommandException: If the player is not found, API key is invalid, etc.
        """
        client = _resolve_in_proxy_chain(proxy, "hypixel_client")

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


# =============================================================================
# Settings Types
# =============================================================================


class SettingPath(CommandArg):
    """
    A validated setting path that resolves to a Setting object.

    This type validates the dot-separated path against the proxy's settings
    and provides tab completion for setting names.

    Attributes:
        path: The full dot-separated path to the setting
        setting: The resolved Setting object
    """

    def __init__(self, path: str, setting: Setting):
        self.path = path
        self.setting = setting

    @classmethod
    def _get_all_setting_paths(cls, group: SettingGroup, prefix: str = "") -> list[str]:
        """Recursively get all setting paths from a SettingGroup."""
        from core.settings import Setting, SettingGroup

        paths: list[str] = []

        for attr_name in dir(group):
            if attr_name.startswith("_"):
                continue

            attr = getattr(group, attr_name)
            full_path = f"{prefix}.{attr_name}" if prefix else attr_name

            if isinstance(attr, Setting):
                paths.append(full_path)
            elif isinstance(attr, SettingGroup):
                paths.extend(cls._get_all_setting_paths(attr, full_path))

        return paths

    @classmethod
    async def convert(cls, proxy: Any, value: str) -> SettingPath:
        """
        Convert a setting path string to a SettingPath.

        Raises:
            CommandException: If the path is invalid or doesn't point to a Setting
        """
        from core.settings import Setting, SettingGroup

        settings = _resolve_in_proxy_chain(proxy, "settings")
        if settings is None:
            raise CommandException(
                TextComponent("Settings not available!").color("red")
            )

        parts = value.split(".")
        current: Any = settings
        traversed: list[str] = []

        for part in parts:
            if not hasattr(current, part):
                if isinstance(current, SettingGroup):
                    raise CommandException(
                        TextComponent("Setting group '")
                        .append(
                            TextComponent(".".join(traversed) or "settings").color(
                                "gold"
                            )
                        )
                        .append("' does not have a setting named '")
                        .append(TextComponent(part).color("gold"))
                        .append("'!")
                    )
                elif isinstance(current, Setting):
                    raise CommandException(
                        TextComponent("'")
                        .append(TextComponent(".".join(traversed)).color("gold"))
                        .append("' is a setting, not a group!")
                    )
                else:
                    raise CommandException(
                        TextComponent("Invalid setting path '")
                        .append(TextComponent(value).color("gold"))
                        .append("'!")
                    )

            traversed.append(part)
            current = getattr(current, part)

        if isinstance(current, SettingGroup):
            raise CommandException(
                TextComponent("'")
                .append(TextComponent(value).color("gold"))
                .append("' is a setting group, not a setting!")
            )

        if not isinstance(current, Setting):
            raise CommandException(
                TextComponent("'")
                .append(TextComponent(value).color("gold"))
                .append("' is not a valid setting!")
            )

        return cls(path=value, setting=current)

    @classmethod
    async def suggest(cls, proxy: Any, partial: str) -> list[str]:
        """Suggest setting paths based on partial input."""
        settings = _resolve_in_proxy_chain(proxy, "settings")
        if settings is None:
            return []

        all_paths = cls._get_all_setting_paths(settings)
        partial_lower = partial.lower()
        return [path for path in all_paths if path.lower().startswith(partial_lower)]


class SettingValue(CommandArg):
    """
    A validated setting value.

    This type should be used after SettingPath to validate the value
    against the setting's allowed states. Since we need the setting
    context, this is typically used with runtime validation.

    For now, this just passes through the value as-is (uppercase).
    Validation happens in the command handler with the setting context.
    """

    def __init__(self, value: str):
        self.value = value.upper()
        self.original = value

    @classmethod
    async def convert(cls, proxy: Any, value: str) -> SettingValue:
        """Convert and normalize the value (uppercase)."""
        return cls(value)

    @classmethod
    async def suggest(cls, proxy: Any, partial: str) -> list[str]:
        """
        Suggest setting values.

        Note: Without context of which setting, we can't provide specific suggestions.
        The command handler should provide context-aware suggestions if needed.
        """
        common = ["ON", "OFF"]
        return [v for v in common if v.lower().startswith(partial.lower())]
