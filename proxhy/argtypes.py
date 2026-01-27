from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Literal

import hypixel

from protocol.datatypes import TextComponent
from proxhy.command import CommandArg
from proxhy.errors import CommandException
from proxhy.hypixels import Stat
from proxhy.utils import PlayerInfo, _Client

if TYPE_CHECKING:
    from core.settings import Setting, SettingGroup
    from proxhy.command import CommandContext


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
        from proxhy.errors import CommandException

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
    async def convert(cls, ctx: CommandContext, value: str) -> SettingPath:
        """
        Convert a setting path string to a SettingPath.

        Raises:
            CommandException: If the path is invalid or doesn't point to a Setting
        """
        from core.settings import Setting, SettingGroup

        settings = _resolve_in_proxy_chain(ctx.proxy, "settings")
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
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        """Suggest setting paths based on partial input."""
        settings = _resolve_in_proxy_chain(ctx.proxy, "settings")
        if settings is None:
            return []

        all_paths = cls._get_all_setting_paths(settings)
        partial_lower = partial.lower()
        return [path for path in all_paths if path.lower().startswith(partial_lower)]


class SettingValue(CommandArg):
    """
    A validated setting value.

    This type uses the command context to validate the value against
    the setting's allowed states when a SettingPath is available.

    Attributes:
        value: The normalized (uppercase) value
        original: The original value as provided by the user
    """

    def __init__(self, value: str):
        self.value = value.upper()
        self.original = value

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> SettingValue:
        """
        Convert and validate the setting value.

        If a SettingPath is available in context, validates that the value
        is one of the setting's allowed states.

        Raises:
            CommandException: If the value is not valid for the setting
        """
        setting_path = await ctx.get_arg(SettingPath)

        if setting_path is not None:
            normalized = value.upper()
            if normalized not in setting_path.setting.states:
                valid_states = ", ".join(setting_path.setting.states.keys())
                raise CommandException(
                    TextComponent("Invalid value '")
                    .append(TextComponent(value).color("gold"))
                    .append("' for setting '")
                    .append(TextComponent(setting_path.path).color("gold"))
                    .append("'. Valid values: ")
                    .append(TextComponent(valid_states).color("green"))
                )

        return cls(value)

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        """
        Suggest setting values based on the setting's allowed states.

        If a SettingPath is available in context, suggests from the setting's
        actual states. Otherwise, suggests common values (ON, OFF).
        """
        setting_path = await ctx.get_arg(SettingPath)

        if setting_path is not None:
            # Suggest from the setting's actual allowed states
            states = list(setting_path.setting.states.keys())
            return [s for s in states if s.lower().startswith(partial.lower())]

        # Fallback to common values
        common = ["ON", "OFF"]
        return [v for v in common if v.lower().startswith(partial.lower())]


type Gamemode_T = Literal["bedwars"]


class Gamemode(CommandArg):
    mode: Gamemode_T

    GAMES: dict[Gamemode_T, dict[str, list[str]]] = {
        "bedwars": {
            "aliases": ["bedwar", "bw", "bws"],
        },
    }

    @staticmethod
    def _build_reverse_lookup(
        games: dict[Gamemode_T, dict[str, list[str]]],
    ) -> dict[str, Gamemode_T]:
        out: dict[str, Gamemode_T] = {}
        for canonical, data in games.items():
            out[canonical] = canonical
            for alias in data.get("aliases", []):
                out[alias] = canonical
        return out

    GAME_LOOKUP = _build_reverse_lookup(GAMES)

    def __init__(self, mode: Gamemode_T):
        self.mode = mode  # e.g. "bedwars" or "skywars"

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> Gamemode:
        s = value.lower().strip()

        if mode := cls.GAME_LOOKUP.get(s):
            return cls(mode=mode)
        else:
            raise CommandException(f"Invalid or unsupported gamemode '{value}'")

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[Gamemode_T]:
        s = partial.lower().strip()

        return [g for g in cls.GAMES.keys() if g.startswith(s)]


class Statistic(CommandArg):
    STATS: dict[Gamemode_T, dict[str, Stat]] = {
        "bedwars": {
            # custom
            "fkdr": Stat(
                name="FKDR",
                json_key="fkdr",
                main="fkdr",
                aliases=["fk/d"],
            ),
            "kdr": Stat(
                name="KDR",
                json_key="kdr",
                main="kdr",
                aliases=["k/d"],
            ),
            "wlr": Stat(
                name="WLR",
                json_key="wlr",
                main="wlr",
                aliases=["w/l"],
            ),
            "bblr": Stat(
                name="BBLR",
                json_key="bblr",
                main="bblr",
                aliases=["bb/l"],
            ),
            # -----------
            "beds": Stat(
                name="Beds Broken",
                json_key="beds_broken_bedwars",
                main="beds",
                aliases=["beds_broken", "beds_destroyed"],
            ),
            "beds_lost": Stat(
                name="Beds Lost",
                json_key="beds_lost_bedwars",
                main="beds_lost",
                aliases=["bedslost"],
            ),
            "challenges": Stat(
                name="Unique Challenges Completed",
                json_key="bw_unique_challenges_completed",
                main="challenges",
                aliases=[],
            ),
            "deaths": Stat(
                name="Deaths",
                json_key="deaths_bedwars",
                main="deaths",
                aliases=["dies"],
            ),
            "diamonds": Stat(
                name="Diamonds Collected",
                json_key="diamond_resources_collected_bedwars",
                main="diamonds",
                aliases=["dias"],
            ),
            "drowns": Stat(
                name="Drowning Deaths",
                json_key="drowning_deaths_bedwars",
                main="drowns",
                aliases=[],
            ),
            "emeralds": Stat(
                name="Emeralds Collected",
                json_key="emerald_resources_collected_bedwars",
                main="emeralds",
                aliases=["ems"],
            ),
            # entity attack
            "entity_deaths": Stat(
                name="Entity Deaths",
                json_key="entity_attack_deaths_bedwars",
                main="entity_deaths",
                aliases=[],
            ),
            "entity_final_deaths": Stat(
                name="Entity Final Deaths",
                json_key="entity_attack_final_deaths_bedwars",
                main="entity_final_deaths",
                aliases=[],
            ),
            "entity_finals": Stat(
                name="Entity Finals",
                json_key="entity_attack_final_kills_bedwars",
                main="entity_finals",
                aliases=[],
            ),
            "entity_kills": Stat(
                name="Entity Kills",
                json_key="entity_attack_kills_bedwars",
                main="entity_kills",
                aliases=[],
            ),
            # explosions
            "explosion_deaths": Stat(
                name="Explosion Deaths",
                json_key="entity_explosion_deaths_bedwars",
                main="explosion_deaths",
                aliases=[],
            ),
            "explosion_final_deaths": Stat(
                name="Explosion Final Deaths",
                json_key="entity_explosion_final_deaths_bedwars",
                main="explosion_final_deaths",
                aliases=[],
            ),
            "explosion_finals": Stat(
                name="Explosion Finals",
                json_key="entity_explosion_final_kills_bedwars",
                main="explosion_finals",
                aliases=["explosion_final_kills"],
            ),
            "explosion_kills": Stat(
                name="Explosion Kills",
                json_key="entity_explosion_kills_bedwars",
                main="explosion_kills",
                aliases=[],
            ),
            # falls
            "falls": Stat(
                name="Fall Deaths",
                json_key="fall_deaths_bedwars",
                main="falls",
                aliases=["fall_deaths"],
            ),
            "fall_final_deaths": Stat(
                name="Fall Final Deaths",
                json_key="fall_final_deaths_bedwars",
                main="fall_final_deaths",
                aliases=["fall_fdeaths"],
            ),
            "fall_finals": Stat(
                name="Fall Finals",
                json_key="fall_final_kills_bedwars",
                main="fall_finals",
                aliases=["fall_final_kills"],
            ),
            "fall_kills": Stat(
                name="Fall Kills",
                json_key="fall_kills_bedwars",
                main="fall_kills",
                aliases=[],
            ),
            # finals
            "final_deaths": Stat(
                name="Final Deaths",
                json_key="final_deaths_bedwars",
                main="final_deaths",
                aliases=["fdeaths"],
            ),
            "finals": Stat(
                name="Finals",
                json_key="final_kills_bedwars",
                main="finals",
                aliases=["final_kills", "fkills", "fks"],
            ),
            # fire
            "fire_deaths": Stat(
                name="Fire Deaths",
                json_key="fire_deaths_bedwars",
                main="fire_deaths",
                aliases=[],
            ),
            "fire_final_deaths": Stat(
                name="Fire Final Deaths",
                json_key="fire_final_deaths_bedwars",
                main="fire_final_deaths",
                aliases=[],
            ),
            "fire_finals": Stat(
                name="Fire Finals",
                json_key="fire_final_kills_bedwars",
                main="fire_finals",
                aliases=["fire_final_kills"],
            ),
            "fire_kills": Stat(
                name="Fire Kills",
                json_key="fire_kills_bedwars",
                main="fire_kills",
                aliases=[],
            ),
            # fire tick
            "fire_tick_deaths": Stat(
                name="Fire Tick Deaths",
                json_key="fire_tick_deaths_bedwars",
                main="fire_tick_deaths",
                aliases=[],
            ),
            "fire_tick_final_deaths": Stat(
                name="Fire Tick Final Deaths",
                json_key="fire_tick_final_deaths_bedwars",
                main="fire_tick_final_deaths",
                aliases=[],
            ),
            "fire_tick_finals": Stat(
                name="Fire Tick Finals",
                json_key="fire_tick_final_kills_bedwars",
                main="fire_tick_finals",
                aliases=["fire_tick_final_kills"],
            ),
            "fire_tick_kills": Stat(
                name="Fire Tick Kills",
                json_key="fire_tick_kills_bedwars",
                main="fire_tick_kills",
                aliases=[],
            ),
            # general
            "games": Stat(
                name="Games Played",
                json_key="games_played_bedwars",
                main="games",
                aliases=["plays"],
            ),
            "gold": Stat(
                name="Gold Collected",
                json_key="gold_resources_collected_bedwars",
                main="gold",
                aliases=[],
            ),
            "iron": Stat(
                name="Iron Collected",
                json_key="iron_resources_collected_bedwars",
                main="iron",
                aliases=[],
            ),
            "purchases": Stat(
                name="Items Purchased",
                json_key="items_purchased_bedwars",
                main="purchases",
                aliases=["items"],
            ),
            "kills": Stat(
                name="Kills",
                json_key="kills_bedwars",
                main="kills",
                aliases=[],
            ),
            "losses": Stat(
                name="Losses",
                json_key="losses_bedwars",
                main="losses",
                aliases=[],
            ),
            # magic
            "magic_deaths": Stat(
                name="Magic Deaths",
                json_key="magic_deaths_bedwars",
                main="magic_deaths",
                aliases=[],
            ),
            "magic_final_deaths": Stat(
                name="Magic Final Deaths",
                json_key="magic_final_deaths_bedwars",
                main="magic_final_deaths",
                aliases=[],
            ),
            "magic_finals": Stat(
                name="Magic Finals",
                json_key="magic_final_kills_bedwars",
                main="magic_finals",
                aliases=["magic_final_kills"],
            ),
            "magic_kills": Stat(
                name="Magic Kills",
                json_key="magic_kills_bedwars",
                main="magic_kills",
                aliases=[],
            ),
            # projectile
            "projectile_deaths": Stat(
                name="Projectile Deaths",
                json_key="projectile_deaths_bedwars",
                main="projectile_deaths",
                aliases=[],
            ),
            "projectile_final_deaths": Stat(
                name="Projectile Final Deaths",
                json_key="projectile_final_deaths_bedwars",
                main="projectile_final_deaths",
                aliases=[],
            ),
            "projectile_finals": Stat(
                name="Projectile Finals",
                json_key="projectile_final_kills_bedwars",
                main="projectile_finals",
                aliases=["projectile_final_kills"],
            ),
            "projectile_kills": Stat(
                name="Projectile Kills",
                json_key="projectile_kills_bedwars",
                main="projectile_kills",
                aliases=[],
            ),
            # misc
            "collects": Stat(
                name="Resources Collected",
                json_key="resources_collected_bedwars",
                main="collects",
                aliases=["resources_collected"],
            ),
            "suffocation_deaths": Stat(
                name="Suffocation Deaths",
                json_key="suffocation_deaths_bedwars",
                main="suffocation_deaths",
                aliases=[],
            ),
            "suffocation_final_deaths": Stat(
                name="Suffocation Final Deaths",
                json_key="suffocation_final_deaths_bedwars",
                main="suffocation_final_deaths",
                aliases=[],
            ),
            "total_challenges": Stat(
                name="Total Challenges Completed",
                json_key="total_challenges_completed",
                main="total_challenges",
                aliases=[],
            ),
            # void
            "voids": Stat(
                name="Void Deaths",
                json_key="void_deaths_bedwars",
                main="voids",
                aliases=[],
            ),
            "void_final_deaths": Stat(
                name="Void Final Deaths",
                json_key="void_final_deaths_bedwars",
                main="void_final_deaths",
                aliases=[],
            ),
            "void_finals": Stat(
                name="Void Finals",
                json_key="void_final_kills_bedwars",
                main="void_finals",
                aliases=["void_final_kills"],
            ),
            "void_kills": Stat(
                name="Void Kills",
                json_key="void_kills_bedwars",
                main="void_kills",
                aliases=[],
            ),
            # wins
            "wins": Stat(
                name="Wins",
                json_key="wins_bedwars",
                main="wins",
                aliases=[],
            ),
            "winstreak": Stat(
                name="Winstreak",
                json_key="winstreak",
                main="winstreak",
                aliases=["ws"],
            ),
            # seasonal
            "presents": Stat(
                name="Presents Collected",
                json_key="wrapped_present_resources_collected_bedwars",
                main="presents",
                aliases=[],
            ),
        }
    }

    @staticmethod
    def _build_stat_lookup(
        stats: dict[Gamemode_T, dict[str, Stat]],
    ) -> dict[str, dict[str, Stat]]:
        out: dict[str, dict[str, Stat]] = {}

        for gamemode, stat_map in stats.items():
            lookup: dict[str, Stat] = {}
            for stat in stat_map.values():
                lookup[stat.main] = stat
                for a in stat.aliases:
                    if a in lookup:
                        raise ValueError(f"Duplicate alias {a} in {gamemode}")
                    lookup[a] = stat
            out[gamemode] = lookup

        return out

    STAT_LOOKUP = _build_stat_lookup(STATS)

    def __init__(self, stat: Stat):
        self.stat = stat

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> Statistic:
        s = value.lower().strip()
        gamemode = await ctx.get_arg(Gamemode)

        gamemodes = (
            [gamemode.mode] if gamemode is not None else list(Gamemode.GAMES.keys())
        )

        for gm in gamemodes:
            if stat := cls.STAT_LOOKUP[gm].get(s):
                return cls(stat=stat)
            else:
                raise CommandException(f"Invalid statistic '{value}'")
        else:
            # bow to the type checker gods
            raise CommandException("This should not happen!")

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        s = partial.lower().strip()

        gamemode = await ctx.get_arg(Gamemode)

        if gamemode is not None:
            statistics = list(cls.STATS[gamemode.mode].keys())
        else:
            statistics = []
            gamemodes = (
                [gamemode.mode] if gamemode is not None else list(Gamemode.GAMES.keys())
            )
            for gm in gamemodes:
                statistics.extend(cls.STATS[gm].keys())

        return sorted([stat for stat in statistics if stat.startswith(s)], key=len)
