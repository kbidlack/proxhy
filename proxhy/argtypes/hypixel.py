from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypedDict

from core.command import CommandArg, CommandException
from protocol.datatypes import TextComponent

if TYPE_CHECKING:
    from core.command import CommandContext

# https://api.hypixel.net/v2/resources/games
type GAMETYPE_T = Literal[
    "arcade",
    "arena",
    "battleground",
    "bedwars",
    "build_battle",
    "duels",
    "gingerbread",
    "mcgo",
    "murder_mystery",
    "paintball",
    "pit",
    "quakecraft",
    "skyblock",
    "skywars",
    "speed_uhc",
    "super_smash",
    "survival_games",
    "tntgames",
    "uhc",
    "vampirez",
    "walls",
    "walls3",
    "wool_games",
]


class GameInfo(TypedDict):
    display_name: str
    main_alias: str
    aliases: list[str]


class Gamemode(CommandArg):
    mode: GAMETYPE_T

    GAMES: dict[GAMETYPE_T, GameInfo] = {
        "arcade": {
            "display_name": "Arcade Games",
            "main_alias": "arcade",
            "aliases": ["arcade-games", "arcadegames", "arc"],
        },
        "arena": {
            "display_name": "Arena Brawl",
            "main_alias": "arena",
            "aliases": ["arena-brawl", "arenabrawl"],
        },
        "battleground": {
            "display_name": "Warlords",
            "main_alias": "warlords",
            "aliases": ["wl"],
        },
        "bedwars": {
            "display_name": "Bed Wars",
            "main_alias": "bedwars",
            "aliases": ["bedwar", "bw", "bws"],
        },
        "build_battle": {
            "display_name": "Build Battle",
            "main_alias": "build_battle",
            "aliases": ["buildbattle", "bb"],
        },
        "duels": {
            "display_name": "Duels",
            "main_alias": "duels",
            "aliases": ["duel"],
        },
        "gingerbread": {
            "display_name": "Turbo Kart Racers",
            "main_alias": "tkr",
            "aliases": ["turbo-kart-racers", "turbokartracers"],
        },
        "mcgo": {
            "display_name": "Cops and Crims",
            "main_alias": "cops_and_crims",
            "aliases": ["copsandcrims", "copsncrims", "cnc"],
        },
        "murder_mystery": {
            "display_name": "Murder Mystery",
            "main_alias": "murder_mystery",
            "aliases": ["murdermystery", "mm"],
        },
        "paintball": {
            "display_name": "Paintball",
            "main_alias": "paintball",
            "aliases": [],
        },
        "pit": {
            "display_name": "The Pit",
            "main_alias": "pit",
            "aliases": [],
        },
        "quakecraft": {
            "display_name": "Quakecraft",
            "main_alias": "quake",
            "aliases": ["quakecraft"],
        },
        "skyblock": {
            "display_name": "SkyBlock",
            "main_alias": "skyblock",
            "aliases": ["sb"],
        },
        "skywars": {
            "display_name": "SkyWars",
            "main_alias": "skywars",
            "aliases": ["sw"],
        },
        "speed_uhc": {
            "display_name": "Speed UHC",
            "main_alias": "speed_uhc",
            "aliases": ["speeduhc", "suhc"],
        },
        "super_smash": {
            "display_name": "Smash Heroes",
            "main_alias": "smash",
            "aliases": ["smash-heroes", "smashheroes", "sh"],
        },
        "survival_games": {
            "display_name": "Blitz Survival Games",
            "main_alias": "blitz",
            "aliases": ["blitz-survival-games", "bsg"],
        },
        "tntgames": {
            "display_name": "TNT Games",
            "main_alias": "tnt",
            "aliases": ["tnt-games", "tntgames"],
        },
        "uhc": {
            "display_name": "UHC Champions",
            "main_alias": "uhc",
            "aliases": [],
        },
        "vampirez": {
            "display_name": "VampireZ",
            "main_alias": "vampirez",
            "aliases": ["vz"],
        },
        "walls": {
            "display_name": "Walls",
            "main_alias": "walls",
            "aliases": [],
        },
        "walls3": {
            "display_name": "Mega Walls",
            "main_alias": "mega_walls",
            "aliases": ["megawalls", "mw"],
        },
        "wool_games": {
            "display_name": "Wool Games",
            "main_alias": "wool_games",
            "aliases": ["woolgames", "wg"],
        },
    }

    @staticmethod
    def _build_reverse_lookup(
        games: dict[GAMETYPE_T, GameInfo],
    ) -> dict[str, GAMETYPE_T]:
        out: dict[str, GAMETYPE_T] = {}
        for canonical, data in games.items():
            out[canonical] = canonical
            out[data["main_alias"]] = canonical
            for alias in data["aliases"]:
                out[alias] = canonical
        return out

    GAME_LOOKUP = _build_reverse_lookup(GAMES)

    def __init__(self, mode_str: GAMETYPE_T):
        self.mode_str = mode_str  # e.g. "bedwars" or "skywars"
        self.display_name = self.GAMES[mode_str]["display_name"]

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> Gamemode:
        s = value.lower().strip()

        if mode_str := cls.GAME_LOOKUP.get(s):
            return cls(mode_str=mode_str)
        else:
            raise CommandException(
                TextComponent("Invalid or unsupported gamemode '")
                .append(TextComponent(value).color("gold"))
                .append("'!")
            )

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        s = partial.lower().strip()

        return [
            data["main_alias"]
            for data in cls.GAMES.values()
            if data["main_alias"].startswith(s)
        ]


@dataclass
class SubNode:
    """A node in the submode tree. Either a leaf (has id) or a branch (has children)."""

    id: str | None = None
    aliases: list[str] = field(default_factory=list)
    children: dict[str, SubNode] | None = None

    @staticmethod
    def leaf(id: str, aliases: list[str] | None = None) -> SubNode:
        return SubNode(id=id, aliases=aliases or [])

    @staticmethod
    def branch(
        children: dict[str, SubNode], aliases: list[str] | None = None
    ) -> SubNode:
        return SubNode(aliases=aliases or [], children=children)


class Submode(CommandArg):
    SUBMODES: dict[GAMETYPE_T, dict[str, SubNode]] = {
        "arcade": {
            "zombies-prison": SubNode.leaf("arcade_zombies_prison", ["zp"]),
            "zombies-dead-end": SubNode.leaf("arcade_zombies_dead_end", ["zde"]),
            "zombies-bad-blood": SubNode.leaf("arcade_zombies_bad_blood", ["zbb"]),
            "zombies-alien-arcadium": SubNode.leaf(
                "arcade_zombies_alien_arcadium", ["zaa"]
            ),
            "throw-out": SubNode.leaf("arcade_throw_out"),
            "galaxy-wars": SubNode.leaf("arcade_starwars", ["starwars"]),
            "football": SubNode.leaf("arcade_soccer", ["soccer"]),
            "hypixel-says": SubNode.leaf("arcade_simon_says", ["simon-says"]),
            "pixel-party": SubNode.leaf("arcade_pixel_party"),
            "pixel-painters": SubNode.leaf("arcade_pixel_painters"),
            "party-games": SubNode.leaf("arcade_party_games_1", ["pg"]),
            "mini-walls": SubNode.leaf("arcade_mini_walls", ["mw"]),
            "hole-in-the-wall": SubNode.leaf("arcade_hole_in_the_wall", ["hitw"]),
            "prop-hunt": SubNode.leaf("arcade_hide_and_seek_prop_hunt"),
            "party-pooper": SubNode.leaf("arcade_hide_and_seek_party_pooper"),
            "farm-hunt": SubNode.leaf("arcade_farm_hunt"),
            "ender-spleef": SubNode.leaf("arcade_ender_spleef"),
            "dropper": SubNode.leaf("arcade_dropper"),
            "dragon-wars": SubNode.leaf("arcade_dragon_wars", ["dragonwars"]),
            "blocking-dead": SubNode.leaf("arcade_day_one"),
            "creeper-attack": SubNode.leaf("arcade_creeper_defense"),
            "bounty-hunters": SubNode.leaf("arcade_bounty_hunters"),
        },
        "arena": {
            "1v1": SubNode.leaf("arena_1v1"),
            "2v2": SubNode.leaf("arena_2v2"),
            "4v4": SubNode.leaf("arena_4v4"),
        },
        "battleground": {
            "team-deathmatch": SubNode.leaf("warlords_team_deathmatch", ["tdm"]),
            "domination": SubNode.leaf("warlords_domination", ["dom"]),
            "ctf": SubNode.leaf("warlords_ctf_mini"),
        },
        "bedwars": {
            "solo": SubNode.leaf("bedwars_eight_one", ["solos", "1s"]),
            "doubles": SubNode.leaf("bedwars_eight_two", ["2s"]),
            "3v3v3v3": SubNode.leaf("bedwars_four_three", ["3s"]),
            "4v4v4v4": SubNode.leaf("bedwars_four_four", ["4s"]),
            "4v4": SubNode.leaf("bedwars_two_four"),
            "duels": SubNode.leaf("bedwars_two_one_duels", ["duel"]),
            "practice": SubNode.leaf("bedwars_practice"),
            "rush": SubNode.branch(
                {
                    "doubles": SubNode.leaf("bedwars_eight_two_rush", ["2s"]),
                    "4v4v4v4": SubNode.leaf("bedwars_four_four_rush", ["4s"]),
                }
            ),
            "ultimate": SubNode.branch(
                {
                    "doubles": SubNode.leaf("bedwars_eight_two_ultimate", ["2s"]),
                    "4v4v4v4": SubNode.leaf("bedwars_four_four_ultimate", ["4s"]),
                }
            ),
            "voidless": SubNode.branch(
                {
                    "doubles": SubNode.leaf("bedwars_eight_two_voidless", ["2s"]),
                    "4v4v4v4": SubNode.leaf("bedwars_four_four_voidless", ["4s"]),
                }
            ),
            "armed": SubNode.branch(
                {
                    "doubles": SubNode.leaf("bedwars_eight_two_armed", ["2s"]),
                    "4v4v4v4": SubNode.leaf("bedwars_four_four_armed", ["4s"]),
                }
            ),
            "lucky": SubNode.branch(
                {
                    "doubles": SubNode.leaf("bedwars_eight_two_lucky", ["2s"]),
                    "4v4v4v4": SubNode.leaf("bedwars_four_four_lucky", ["4s"]),
                }
            ),
            "castle": SubNode.leaf("bedwars_castle"),
        },
        "build_battle": {
            "solo": SubNode.leaf("build_battle_solo_normal", ["solos"]),
            "solo-1.14": SubNode.leaf(
                "build_battle_solo_normal_latest", ["solos-1.14"]
            ),
            "teams": SubNode.leaf("build_battle_teams_normal"),
            "pro": SubNode.leaf("build_battle_solo_pro"),
            "guess-the-build": SubNode.leaf("build_battle_guess_the_build", ["gtb"]),
        },
        "duels": {
            "uhc": SubNode.branch(
                {
                    "1v1": SubNode.leaf("duels_uhc_duel", ["solo"]),
                    "2v2": SubNode.leaf("duels_uhc_doubles", ["doubles"]),
                    "4v4": SubNode.leaf("duels_uhc_four"),
                    "deathmatch": SubNode.leaf("duels_uhc_meetup"),
                }
            ),
            "sw": SubNode.branch(
                {
                    "1v1": SubNode.leaf("duels_sw_duel", ["solo"]),
                    "2v2": SubNode.leaf("duels_sw_doubles", ["doubles"]),
                },
                aliases=["skywars"],
            ),
            "sumo": SubNode.leaf("duels_sumo_duel"),
            "nodebuff": SubNode.leaf("duels_potion_duel"),
            "parkour": SubNode.leaf("duels_parkour_eight"),
            "op": SubNode.branch(
                {
                    "1v1": SubNode.leaf("duels_op_duel", ["solo"]),
                    "2v2": SubNode.leaf("duels_op_doubles", ["doubles"]),
                }
            ),
            "mw": SubNode.branch(
                {
                    "1v1": SubNode.leaf("duels_mw_duel", ["solo"]),
                    "2v2": SubNode.leaf("duels_mw_doubles", ["doubles"]),
                },
                aliases=["mega-walls"],
            ),
            "arena": SubNode.leaf("duels_duel_arena"),
            "combo": SubNode.leaf("duels_combo_duel"),
            "classic": SubNode.leaf("duels_classic_duel"),
            "bridge": SubNode.branch(
                {
                    "1v1": SubNode.leaf("duels_bridge_duel", ["solo"]),
                    "2v2": SubNode.leaf("duels_bridge_doubles", ["doubles"]),
                    "3v3": SubNode.leaf("duels_bridge_threes"),
                    "4v4": SubNode.leaf("duels_bridge_four"),
                    "2v2v2v2": SubNode.leaf("duels_bridge_2v2v2v2"),
                    "3v3v3v3": SubNode.leaf("duels_bridge_3v3v3v3"),
                    "ctf": SubNode.leaf("duels_capture_threes"),
                }
            ),
            "boxing": SubNode.leaf("duels_boxing_duel"),
            "bow-spleef": SubNode.leaf("duels_bowspleef_duel"),
            "bow": SubNode.leaf("duels_bow_duel"),
            "blitz": SubNode.leaf("duels_blitz_duel"),
        },
        "gingerbread": {},
        "mcgo": {
            "defusal": SubNode.leaf("mcgo_normal"),
            "gun-game": SubNode.leaf("mcgo_gungame", ["gg"]),
            "team-deathmatch": SubNode.leaf("mcgo_deathmatch", ["tdm"]),
        },
        "murder_mystery": {
            "classic": SubNode.leaf("murder_classic"),
            "double-up": SubNode.leaf("murder_double_up"),
            "assassins": SubNode.leaf("murder_assassins"),
            "infection": SubNode.leaf("murder_infection"),
        },
        "paintball": {},
        "pit": {},
        "quakecraft": {
            "solo": SubNode.leaf("quake_solo"),
            "teams": SubNode.leaf("quake_teams"),
        },
        "skyblock": {},
        "skywars": {
            "solo": SubNode.branch(
                {
                    "normal": SubNode.leaf("solo_normal"),
                    "insane": SubNode.leaf("solo_insane"),
                }
            ),
            "doubles": SubNode.branch(
                {
                    "normal": SubNode.leaf("teams_normal"),
                    "insane": SubNode.leaf("teams_insane"),
                }
            ),
            "mega": SubNode.leaf("mega_normal"),
            "mega-doubles": SubNode.leaf("mega_doubles"),
            "tnt": SubNode.branch(
                {
                    "solo": SubNode.leaf("solo_insane_tnt_madness"),
                    "doubles": SubNode.leaf("teams_insane_tnt_madness", ["teams"]),
                },
                aliases=["tnt-madness"],
            ),
            "slime": SubNode.branch(
                {
                    "solo": SubNode.leaf("solo_insane_slime"),
                    "doubles": SubNode.leaf("teams_insane_slime", ["teams"]),
                }
            ),
            "rush": SubNode.branch(
                {
                    "solo": SubNode.leaf("solo_insane_rush"),
                    "doubles": SubNode.leaf("teams_insane_rush", ["teams"]),
                }
            ),
            "lucky": SubNode.branch(
                {
                    "solo": SubNode.leaf("solo_insane_lucky"),
                    "doubles": SubNode.leaf("teams_insane_lucky", ["teams"]),
                }
            ),
        },
        "speed_uhc": {
            "solo": SubNode.leaf("speed_solo_normal"),
            "teams": SubNode.leaf("speed_team_normal"),
        },
        "super_smash": {
            "solo": SubNode.leaf("super_smash_solo_normal"),
            "2v2": SubNode.leaf("super_smash_2v2_normal"),
            "teams": SubNode.leaf("super_smash_teams_normal"),
            "1v1": SubNode.leaf("super_smash_1v1_normal"),
            "friends": SubNode.leaf("super_smash_friends_normal"),
        },
        "survival_games": {
            "solo": SubNode.leaf("blitz_solo_normal", ["solos"]),
            "teams": SubNode.leaf("blitz_teams_normal"),
        },
        "tntgames": {
            "tnt-run": SubNode.leaf("tnt_tntrun"),
            "tnt-tag": SubNode.leaf("tnt_tntag"),
            "pvp-run": SubNode.leaf("tnt_pvprun"),
            "wizards": SubNode.leaf("tnt_capture"),
            "bow-spleef": SubNode.leaf("tnt_bowspleef"),
        },
        "uhc": {
            "solo": SubNode.leaf("uhc_solo"),
            "teams": SubNode.leaf("uhc_teams"),
        },
        "vampirez": {},
        "walls": {},
        "walls3": {
            "standard": SubNode.leaf("mw_standard"),
            "face-off": SubNode.leaf("mw_face_off"),
        },
        "wool_games": {
            "wool-wars": SubNode.leaf("wool_wool_wars_two_four", ["ww"]),
            "sheep-wars": SubNode.leaf("wool_sheep_wars_two_six", ["sw"]),
            "ctw": SubNode.leaf(
                "wool_capture_the_wool_two_twenty", ["capture-the-wool"]
            ),
        },
    }

    @staticmethod
    def _build_reverse_lookup(
        nodes: dict[str, SubNode],
    ) -> dict[str, str]:
        out: dict[str, str] = {}
        for canonical, node in nodes.items():
            out[canonical] = canonical
            for alias in node.aliases:
                out[alias] = canonical
        return out

    @staticmethod
    def _build_all_lookups(
        submodes: dict[GAMETYPE_T, dict[str, SubNode]],
    ) -> dict[int, dict[str, str]]:
        lookups: dict[int, dict[str, str]] = {}

        def _traverse(level: dict[str, SubNode]):
            if id(level) in lookups:
                return
            out: dict[str, str] = {}
            for canonical, node in level.items():
                out[canonical] = canonical
                for alias in node.aliases:
                    out[alias] = canonical
                if node.children is not None:
                    _traverse(node.children)
            lookups[id(level)] = out

        for level in submodes.values():
            _traverse(level)

        return lookups

    _LOOKUPS = _build_all_lookups(SUBMODES)

    def __init__(self, name: str, node: SubNode):
        self.name = name
        self.node = node

    @property
    def play_id(self) -> str | None:
        return self.node.id

    @classmethod
    def _resolve_current_level(cls, ctx: CommandContext) -> dict[str, SubNode] | None:
        mode: GAMETYPE_T | None = None
        mode_index = -1
        for i, raw in enumerate(ctx.raw_args):
            if m := Gamemode.GAME_LOOKUP.get(raw.lower().strip()):
                mode = m
                mode_index = i
                break

        if mode is None:
            return None

        level = cls.SUBMODES.get(mode, {})

        for raw in ctx.raw_args[mode_index + 1 : ctx.param_index]:
            if level is None:
                return None
            lookup = cls._LOOKUPS[id(level)]
            canonical = lookup.get(raw.lower().strip())
            if canonical is None:
                return None
            node = level[canonical]
            if node.children is None:
                return None
            level = node.children

        return level

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> Submode:
        s = value.lower().strip()
        level = cls._resolve_current_level(ctx)

        if level is None or not level:
            prior = ctx.raw_args[: ctx.param_index]
            path = " ".join(prior) if prior else "this mode"
            raise CommandException(
                TextComponent(path).color("gold").appends("does not have any submodes!")
            )

        lookup = cls._LOOKUPS[id(level)]
        canonical = lookup.get(s)
        if canonical is None:
            options = ", ".join(sorted(level.keys()))
            raise CommandException(
                TextComponent("Invalid submode '")
                .append(TextComponent(value).color("gold"))
                .append("'. Options: ")
                .append(TextComponent(options).color("dark_aqua"))
            )

        return cls(name=canonical, node=level[canonical])

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        s = partial.lower().strip()
        level = cls._resolve_current_level(ctx)

        if level is None:
            return []

        return sorted(name for name in level if name.startswith(s))


@dataclass(frozen=True)
class Stat:
    name: str
    json_key: str
    main: str
    aliases: list[str]


class Statistic(CommandArg):
    STATS: dict[GAMETYPE_T, dict[str, Stat]] = {
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
        stats: dict[GAMETYPE_T, dict[str, Stat]],
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
            [gamemode.mode_str] if gamemode is not None else list(Gamemode.GAMES.keys())
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
            statistics = list(cls.STATS[gamemode.mode_str].keys())
        else:
            statistics: list[str] = []
            for gm in Gamemode.GAMES:
                statistics.extend(cls.STATS[gm].keys())

        matches = [stat for stat in statistics if stat.startswith(s)]
        matches.sort(key=len)
        return matches
