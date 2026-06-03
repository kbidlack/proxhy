# nearly 500 lines of fake code
# credit for most of the busywork goes to someone other than me
from collections import defaultdict
from typing import cast

from hypixel import Player
from hypixel.color import Color

from proxhy.argtypes.hypixel import GAMETYPE_T
from proxhy.utils import safe_div
from proxhypixel.mappings import BEDWARS_DREAM_MAPPING_SIMPLE, BEDWARS_MAPPING_FULL

SUPPORTED_MODES: set[GAMETYPE_T] = {"bedwars", "skywars"}


def _resolve_player(player: Player | dict) -> dict:
    """Return the raw player data dict from a Player or dict."""
    if isinstance(player, dict):
        return player
    return player._data


def _resolve_rank(data: dict) -> str | None:
    """Resolve rank string from raw player data, mirroring hypixel.py logic."""
    pr = data.get("packageRank")
    npr = data.get("newPackageRank")
    mpr = data.get("monthlyPackageRank")
    prefix = data.get("prefix")
    rank = data.get("rank")
    if prefix:
        # strip §X color codes and brackets
        for c in (
            "§0",
            "§1",
            "§2",
            "§3",
            "§4",
            "§5",
            "§6",
            "§7",
            "§8",
            "§9",
            "§a",
            "§b",
            "§c",
            "§d",
            "§e",
            "§f",
        ):
            prefix = prefix.replace(c, "")
        return prefix.replace("[", "").replace("]", "")
    elif rank:
        if rank == "YOUTUBER":
            return "YOUTUBE"
        elif pr:
            return pr.replace("_", "").replace("PLUS", "+")
        elif rank == "NORMAL":
            return None
        return rank.replace("_", " ")
    elif mpr == "SUPERSTAR":
        return "MVP++"
    elif npr and npr != "NONE":
        return npr.replace("_", "").replace("PLUS", "+")
    return None


def get_rank(player: Player | dict):
    data = _resolve_player(player)
    rank = _resolve_rank(data)
    if rank == "VIP":
        return "§a[VIP]"
    elif rank == "VIP+":
        return "§a[VIP§6+§a]"
    elif rank == "MVP":
        return "§b[MVP]"
    elif rank == "MVP+":
        plus = return_plus_color(player)
        return f"§b[MVP{plus}+§b]"
    elif rank == "MVP++":
        plus = return_plus_color(player)
        bracket = return_monthly_color(player)
        return f"{bracket}[MVP{plus}++{bracket}]"
    elif rank == "ADMIN" or rank == "OWNER":
        return f"§c[{rank}]"
    elif rank == "GAME MASTER":
        return "§2[GM]"
    elif rank == "YOUTUBE":
        return "§c[§fYOUTUBE§c]"
    elif rank == "PIG+++":
        return "§d[PIG§b+++§d]"
    return "§7"  # if there are any other weird ranks because you never know ig, also nons lol


def get_rankname(player: Player | dict) -> str:
    data = _resolve_player(player)
    rank = get_rank(player)
    name = data.get("displayname", "")
    sep = " " if rank != "§7" else ""  # no space for nons
    return sep.join((f"{rank}", f"{name}"))


def return_plus_color(player: Player | dict):
    data = _resolve_player(player)
    plus_color_name = data.get("rankPlusColor")
    if plus_color_name:
        color = Color.from_type(plus_color_name)
        if color:
            return color.chat_code
    return "§c"


def return_monthly_color(player: Player | dict) -> str:
    data = _resolve_player(player)
    monthly_color_name = data.get("monthlyRankColor")
    if monthly_color_name:
        color = Color.from_type(monthly_color_name)
        if color:
            return color.chat_code
    return "§6"


def format_other(other):
    return "§7" + str(other)


# BEDWARS
def format_bw_fkdr(fkdr: float):
    if fkdr < 1:
        return "§7" + str(fkdr)
    elif fkdr < 2.5:
        return "§f" + str(fkdr)
    elif fkdr < 5:
        return "§e" + str(fkdr)
    elif fkdr < 10:
        return "§b" + str(fkdr)
    elif fkdr < 20:
        return "§a" + str(fkdr)
    elif fkdr < 50:
        return "§3" + str(fkdr)
    elif fkdr < 100:
        return "§c" + str(fkdr)
    elif fkdr < 1000:
        return "§5" + str(fkdr)
    else:
        return "§0" + str(fkdr)


def format_bw_wins(wins: int):
    if wins < 250:
        return "§7" + str(wins)
    elif wins < 1000:
        return "§f" + str(wins)
    elif wins < 3000:
        return "§e" + str(wins)
    elif wins < 5000:
        return "§b" + str(wins)
    elif wins < 10000:
        return "§a" + str(wins)
    elif wins < 25000:
        return "§3" + str(wins)
    elif wins < 50000:
        return "§c" + str(wins)
    elif wins < 100000:
        return "§5" + str(wins)
    else:
        return "§0" + str(wins)


def format_bw_finals(finals: int):
    if finals < 250:
        return "§7" + str(finals)
    elif finals < 1000:
        return "§f" + str(finals)
    elif finals < 3000:
        return "§e" + str(finals)
    elif finals < 5000:
        return "§b" + str(finals)
    elif finals < 10000:
        return "§a" + str(finals)
    elif finals < 25000:
        return "§3" + str(finals)
    elif finals < 50000:
        return "§c" + str(finals)
    elif finals < 100000:
        return "§5" + str(finals)
    else:
        return "§0" + str(finals)


def format_bw_wlr(wlr: float):
    if wlr < 0.5:
        return "§7" + str(wlr)
    elif wlr < 1:
        return "§f" + str(wlr)
    elif wlr < 2.5:
        return "§e" + str(wlr)
    elif wlr < 5:
        return "§b" + str(wlr)
    elif wlr < 10:
        return "§a" + str(wlr)
    elif wlr < 25:
        return "§3" + str(wlr)
    elif wlr < 100:
        return "§c" + str(wlr)
    elif wlr < 1000:
        return "§5" + str(wlr)
    else:
        return "§0" + str(wlr)


def format_bw_star(level: float):
    # Thanks a ton to Tiget on the hypixel forums for creating a list of all the prestige colors up to 3000
    # ^ I can't find this post but here's one with up to 2000:
    # https://hypixel.net/threads/tool-bedwars-prestige-colors-in-minecraft-color-code-and-hex-code-high-effort-post.3841719/
    stars = ""
    colors = ["§7", "§f", "§6", "§b", "§2", "§3", "§4", "§d", "§9", "§5"]

    if level < 1000:
        stars = f"{colors[int(level // 100)]}[{level}✫]"
    elif level < 1100:
        slevel = str(level)
        stars += f"§c[§6{slevel[0]}§e{slevel[1]}§a{slevel[2]}§b{slevel[3]}§d✫§5]"
    elif level < 1200:
        stars += f"§7[§f{level}§7✪]"
    elif level < 1300:
        stars += f"§7[§e{level}§6✪§7]"
    elif level < 1400:
        stars += f"§7[§b{level}§3✪§7]"
    elif level < 1500:
        stars += f"§7[§a{level}§2✪§7]"
    elif level < 1600:
        stars += f"§7[§3{level}§9✪§7]"
    elif level < 1700:
        stars += f"§7[§c{level}§4✪§7]"
    elif level < 1800:
        stars += f"§7[§d{level}§5✪§7]"
    elif level < 1900:
        stars += f"§7[§9{level}§1✪§7]"
    elif level < 2000:
        stars += f"§7[§5{level}§8✪§7]"
    elif level < 2100:
        slevel = str(level)
        stars += f"§8[§7{slevel[0]}§f{slevel[1:3]}§7{slevel[3]}✪§8]"
    elif level < 2200:
        slevel = str(level)
        stars += f"§f[{slevel[0]}§e{slevel[1:3]}§6{slevel[3]}⚝]"
    elif level < 2300:
        slevel = str(level)
        stars += f"§6[{slevel[0]}§f{slevel[1:3]}§b{slevel[3]}§3⚝]"
    elif level < 2400:
        slevel = str(level)
        stars += f"§5[{slevel[0]}§d{slevel[1:3]}§6{slevel[3]}§e⚝]"
    elif level < 2500:
        slevel = str(level)
        stars += f"§b[{slevel[0]}§f{slevel[1:3]}§7{slevel[3]}⚝§8]"
    elif level < 2600:
        slevel = str(level)
        stars += f"§f[{slevel[0]}§a{slevel[1:3]}§2{slevel[3]}⚝]"
    elif level < 2700:
        slevel = str(level)
        stars += f"§4[{slevel[0]}§c{slevel[1:3]}§d{slevel[3]}⚝§5]"
    elif level < 2800:
        slevel = str(level)
        stars += f"§e[{slevel[0]}§f{slevel[1:3]}§8{slevel[3]}⚝]"
    elif level < 2900:
        slevel = str(level)
        stars += f"§a[{slevel[0]}§2{slevel[1:3]}§6{slevel[3]}⚝§e]"
    elif level < 3000:
        slevel = str(level)
        stars += f"§b[{slevel[0]}§3{slevel[1:3]}§9{slevel[3]}⚝§1]"
    elif level < 3100:
        slevel = str(level)
        stars += f"§e[{slevel[0]}§6{slevel[1:3]}§c{slevel[3]}⚝§4]"
    elif level < 3200:  # oh my god all of these were so bad to make someone save
        slevel = str(level)
        stars += f"§9[{slevel[0]}§3{slevel[1:3]}§6{slevel[3]}✥§3]"
    elif level < 3300:
        slevel = str(level)
        stars += f"§c[§4{slevel[0]}§7{slevel[1:3]}§4{slevel[3]}§c✥]"
    elif level < 3400:
        slevel = str(level)
        stars += f"§9[{slevel[0:2]}§d{slevel[2]}§c{slevel[3]}✥§4]"
    elif level < 3500:
        slevel = str(level)
        stars += f"§2[§a{slevel[0]}§d{slevel[1:3]}§c{slevel[3]}✥§2]"
    elif level < 3600:
        slevel = str(level)
        stars += f"§c[{slevel[0]}§4{slevel[1:3]}§2{slevel[3]}§a✥]"
    elif level < 3700:
        slevel = str(level)
        stars += f"§a[{slevel[0:2]}§b{slevel[2]}§9{slevel[3]}✥§1]"
    elif level < 3800:
        slevel = str(level)
        stars += f"§4[{slevel[0]}§c{slevel[1:3]}§c{slevel[3]}§3✥]"
    elif level < 3900:
        slevel = str(level)
        stars += f"§1[{slevel[0]}§9{slevel[1]}§5{slevel[2:4]}§d✥§1]"
    elif level < 4000:
        slevel = str(level)
        stars += f"§c[{slevel[0]}§a{slevel[1:3]}§3{slevel[3]}§9✥]"
    elif level < 4100:
        slevel = str(level)
        stars += f"§5[{slevel[0]}§c{slevel[1:3]}§6{slevel[3]}✥§e]"
    elif level < 4200:
        slevel = str(level)
        stars += f"§e[{slevel[0]}§6{slevel[1]}§c{slevel[2]}§d{slevel[3]}✥§5]"
    elif level < 4300:
        slevel = str(level)
        stars += f"§1[§9{slevel[0]}§3{slevel[1]}§b{slevel[2]}§f{slevel[3]}§7✥]"
    elif level < 4400:
        slevel = str(level)
        stars += f"§0[§5{slevel[0]}§8{slevel[1:3]}§5{slevel[3]}✥§0]"
    elif level < 4500:
        slevel = str(level)
        stars += f"§2[{slevel[0]}§a{slevel[1]}§e{slevel[2]}§6{slevel[3]}§5✥§d]"
    elif level < 4600:
        slevel = str(level)
        stars += f"§f[{slevel[0]}§b{slevel[1:3]}§3{slevel[3]}✥]"
    elif level < 4700:
        slevel = str(level)
        stars += f"§3[§b{slevel[0]}§e{slevel[1:3]}§6{slevel[3]}§d✥§5]"
    elif level < 4800:
        slevel = str(level)
        stars += f"§f[§4{slevel[0]}§c{slevel[1:3]}§9{slevel[3]}§1✥§9]"
    elif level < 4900:
        slevel = str(level)
        stars += f"§5[{slevel[0]}§c{slevel[1]}§6{slevel[2]}§e{slevel[3]}§b✥§3]"
    elif level < 5000:
        slevel = str(level)
        stars += f"§2[§a{slevel[0]}§f{slevel[1:3]}§a{slevel[3]}✥§2]"
    else:
        slevel = str(level)
        stars += f"§4[{slevel[0]}§5{slevel[1]}§9{slevel[2:4]}§1✥§0]"

    return stars


# SKYWARS
# ironically skywars stats don't even work in _update_stats yet
# TODO fix these colors
def format_sw_kills(kills):
    if kills < 1000:
        return "§7" + str(kills)
    elif kills < 5000:
        return "§e" + str(kills)
    elif kills < 15000:
        return "§2" + str(kills)
    elif kills < 30000:
        return "§b" + str(kills)
    elif kills < 50000:
        return "§4" + str(kills)
    elif kills < 10000:
        return "§5" + str(kills)
    elif kills < 250000:
        return "§c" + str(kills)
    elif kills < 500000:
        return "§d" + str(kills)
    else:
        return "§0" + str(kills)


def format_sw_wins(wins):
    if wins < 250:
        return "§7" + str(wins)
    elif wins < 1000:
        return "§e" + str(wins)
    elif wins < 3000:
        return "§2" + str(wins)
    elif wins < 7500:
        return "§b" + str(wins)
    elif wins < 15000:
        return "§4" + str(wins)
    elif wins < 30000:
        return "§5" + str(wins)
    elif wins < 60000:
        return "§c" + str(wins)
    elif wins < 100000:
        return "§d" + str(wins)
    else:
        return "§0" + str(wins)


def format_sw_kdr(kdr):
    if kdr < 0.75:
        return "§7" + str(kdr)
    elif kdr < 1.5:
        return "§e" + str(kdr)
    elif kdr < 3:
        return "§2" + str(kdr)
    elif kdr < 5:
        return "§b" + str(kdr)
    elif kdr < 10:
        return "§4" + str(kdr)
    elif kdr < 25:
        return "§5" + str(kdr)
    elif kdr < 50:
        return "§c" + str(kdr)
    elif kdr < 100:
        return "§d" + str(kdr)
    elif kdr < 250:
        return "§9" + str(kdr)
    else:
        return "§0" + str(kdr)


def format_sw_wlr(wlr):
    if wlr < 0.1:
        return "§7" + str(wlr)
    elif wlr < 0.2:
        return "§e" + str(wlr)
    elif wlr < 0.4:
        return "§2" + str(wlr)
    elif wlr < 0.75:
        return "§b" + str(wlr)
    elif wlr < 1:
        return "§4" + str(wlr)
    elif wlr < 2.5:
        return "§5" + str(wlr)
    elif wlr < 5:
        return "§c" + str(wlr)
    elif wlr < 10:
        return "§d" + str(wlr)
    elif wlr < 25:
        return "§9" + str(wlr)
    else:
        return "§0" + str(wlr)


def format_player_dict(player: Player | dict, gamemode: GAMETYPE_T):
    data = _resolve_player(player)
    if gamemode == "bedwars":
        bedwars_data = data.get("stats", {}).get("Bedwars", {})
        fdict: dict[str, str | float | int] = dict(format_bedwars_dict(bedwars_data))
        level = bedwars_data.get("bedwars_level", 1)
        finals = bedwars_data.get("final_kills_bedwars", 0)
        final_deaths = bedwars_data.get("final_deaths_bedwars", 0)
        fdict["star"] = format_bw_star(level)
        fdict["raw_level"] = level
        fdict["raw_fkdr"] = safe_div(finals, final_deaths)
        fdict["rankname"] = get_rankname(data)
        fdict["raw_name"] = data.get("displayname", "")
        return fdict
    elif gamemode == "skywars":
        skywars_data = data.get("stats", {}).get("SkyWars", {})
        fdict = dict(format_skywars_dict(skywars_data))
        xp = skywars_data.get("skywars_experience", 0)
        level = _sw_xp_to_level(xp)
        kills = skywars_data.get("kills", 0)
        deaths = skywars_data.get("deaths", 0)
        wins = skywars_data.get("wins", 0)
        losses = skywars_data.get("losses", 0)
        fdict["star"] = (skywars_data.get("levelFormattedWithBrackets") or "").rstrip()
        fdict["raw_level"] = level
        fdict["raw_kdr"] = safe_div(kills, deaths)
        fdict["raw_wlr"] = safe_div(wins, losses)
        fdict["rankname"] = get_rankname(data)
        fdict["raw_name"] = data.get("displayname", "")
        return fdict
    else:
        raise NotImplementedError("this is not implemented 🤯")


_SW_XP_THRESHOLDS = [0, 20, 70, 150, 250, 500, 1000, 2000, 3500, 6000, 10000, 15000]


def _sw_xp_to_level(xp: int | float) -> float:
    for i in range(1, len(_SW_XP_THRESHOLDS)):
        if xp < _SW_XP_THRESHOLDS[i]:
            prev = _SW_XP_THRESHOLDS[i - 1]
            return (i - 1) + (xp - prev) / (_SW_XP_THRESHOLDS[i] - prev)
    return 12 + (xp - 15000) / 10000


def format_skywars_dict(_data: dict):
    _map_dict = {
        # combat
        "kills": format_sw_kills,
        "deaths": format_sw_kills,
        "kdr": format_sw_kdr,
        "assists": format_sw_kills,
        "melee_kills": format_sw_kills,
        "void_kills": format_sw_kills,
        "bow_kills": format_sw_kills,
        "fall_kills": format_other,
        "mob_kills": format_other,
        "arrows_hit": format_other,
        "arrows_shot": format_other,
        "killstreak": format_other,
        "survived_players": format_other,
        # wins
        "wins": format_sw_wins,
        "losses": format_sw_wins,
        "wlr": format_sw_wlr,
        "winstreak": format_sw_wins,
        # game info
        "games": format_other,
        "chests_opened": format_other,
        "time_played": format_other,
        "quits": format_other,
        # records
        "most_kills_game": format_other,
        "fastest_win": format_other,
        "longest_bow_shot": format_other,
        "longest_bow_kill": format_other,
        # overall only
        "highestWinstreak": format_sw_wins,
        "highestKillstreak": format_other,
        "games_played_skywars": format_other,
        "blocks_broken": format_other,
        "blocks_placed": format_other,
        "egg_thrown": format_other,
        "enderpearls_thrown": format_other,
        "items_enchanted": format_other,
        "refill_chest_destroy": format_other,
        "souls_gathered": format_other,
        "soul_well": format_other,
        "soul_well_legendaries": format_other,
        "soul_well_rares": format_other,
        "paid_souls": format_other,
        "souls": format_other,
        "heads": format_other,
        "coins": format_other,
        "challenge_wins": format_other,
        "shard": format_other,
    }

    base_keys = list(_map_dict.keys())
    data: defaultdict[str, int | float | str] = defaultdict(int, _data.copy())

    modes = [
        "",
        "solo",
        "solo_normal",
        "solo_insane",
        "team",
        "team_normal",
        "team_insane",
        "mega",
        "mega_normal",
        "mega_doubles",
        "ranked",
        "ranked_normal",
        "crazytourney_normal",
        "tourney_teams_tourney",
    ]
    for mode in modes:
        suffix = f"_{mode}" if mode else ""

        for key in base_keys:
            _map_dict[f"{key}{suffix}"] = _map_dict[key]

        kills = cast(int, data[f"kills{suffix}"])
        deaths = cast(int, data[f"deaths{suffix}"])
        wins = cast(int, data[f"wins{suffix}"])
        losses = cast(int, data[f"losses{suffix}"])

        data[f"kdr{suffix}"] = safe_div(kills, deaths)
        data[f"wlr{suffix}"] = safe_div(wins, losses)

    for key in data:
        if func := _map_dict.get(key):
            data[key] = func(data[key])

    return data


def format_bedwars_dict(_data: dict):
    _map_dict = {
        "fkdr": format_bw_fkdr,
        "kdr": format_bw_fkdr,
        "bblr": format_other,
        "wlr": format_bw_wlr,
        "beds_broken_bedwars": format_bw_wins,  # beds; beds_broken, beds_destroyed
        "beds_lost_bedwars": format_bw_wins,  # beds_lost; bedslost
        "bw_unique_challenges_completed": format_other,  # challenges
        "total_challenges_completed": format_other,  # total_challenges
        "kills_bedwars": format_other,  # kills
        "deaths_bedwars": format_other,  # deaths; dies
        "final_kills_bedwars": format_bw_finals,  # finals; final_kills, fkills, fks
        "final_deaths_bedwars": format_bw_finals,  # final_deaths; fdeaths
        "entity_attack_kills_bedwars": format_other,  # entity_kills
        "entity_attack_deaths_bedwars": format_other,  # entity_deaths
        "entity_explosion_kills_bedwars": format_other,  # explosion_kills
        "entity_explosion_deaths_bedwars": format_other,  # explosion_deaths
        "fall_kills_bedwars": format_other,  # fall_kills
        "fall_deaths_bedwars": format_other,  # falls; fall_deaths
        "fire_kills_bedwars": format_other,  # fire_kills
        "fire_deaths_bedwars": format_other,  # fire_deaths
        "fire_tick_kills_bedwars": format_other,  # fire_tick_kills
        "fire_tick_deaths_bedwars": format_other,  # fire_tick_deaths
        "magic_kills_bedwars": format_other,  # magic_kills
        "magic_deaths_bedwars": format_other,  # magic_deaths
        "projectile_kills_bedwars": format_other,  # projectile_kills
        "projectile_deaths_bedwars": format_other,  # projectile_deaths
        "void_kills_bedwars": format_other,  # void_kills
        "void_deaths_bedwars": format_other,  # voids
        "drowning_deaths_bedwars": format_other,  # drowns
        "suffocation_deaths_bedwars": format_other,  # suffocation_deaths
        "suffocation_final_deaths_bedwars": format_bw_finals,  # suffocation_final_deaths
        "entity_attack_final_kills_bedwars": format_bw_finals,  # entity_finals
        "entity_attack_final_deaths_bedwars": format_bw_finals,  # entity_final_deaths
        "entity_explosion_final_kills_bedwars": format_bw_finals,  # explosion_finals
        "entity_explosion_final_deaths_bedwars": format_bw_finals,  # explosion_final_deaths
        "fall_final_kills_bedwars": format_bw_finals,  # fall_finals; fall_final_kills
        "fall_final_deaths_bedwars": format_bw_finals,  # fall_final_deaths; fall_fdeaths
        "fire_final_kills_bedwars": format_bw_finals,  # fire_finals
        "fire_final_deaths_bedwars": format_bw_finals,  # fire_final_deaths
        "fire_tick_final_kills_bedwars": format_bw_finals,  # fire_tick_finals
        "fire_tick_final_deaths_bedwars": format_bw_finals,  # fire_tick_final_deaths
        "magic_final_kills_bedwars": format_bw_finals,  # magic_final_kills
        "magic_final_deaths_bedwars": format_bw_finals,  # magic_final_deaths
        "projectile_final_kills_bedwars": format_bw_finals,  # projectile_final_kills
        "projectile_final_deaths_bedwars": format_bw_finals,  # projectile_final_deaths
        "void_final_kills_bedwars": format_bw_finals,  # void_final_kills
        "void_final_deaths_bedwars": format_bw_finals,  # void_final_deaths
        "wins_bedwars": format_bw_wins,  # wins
        "losses_bedwars": format_bw_wins,  # losses
        "games_played_bedwars": format_bw_wins,  # games; plays
        "winstreak": format_bw_wins,  # winstreak; ws
        "iron_resources_collected_bedwars": format_other,  # iron
        "gold_resources_collected_bedwars": format_other,  # gold
        "diamond_resources_collected_bedwars": format_other,  # diamonds; dias
        "emerald_resources_collected_bedwars": format_other,  # emeralds; ems
        "resources_collected_bedwars": format_other,  # resources_collected; collects
        "wrapped_present_resources_collected_bedwars": format_other,  # presents
        "items_purchased_bedwars": format_other,  # purchases; items
        "coins": format_other,
        "Experience": format_other,
    }

    keys = _map_dict.copy().keys()
    data: defaultdict[str, int | float] = defaultdict(int, _data.copy())

    # construct simplified values
    # e.g. 'rush_final_kills' for sum of
    # 'eight_two_rush_final_kills', 'eight_one_rush_final_kills', and 'four_four_rush_final_kills'
    for mode in BEDWARS_DREAM_MAPPING_SIMPLE.values():  # e.g. 'rush'
        for mkey in keys:  # e.g. 'final_kills'
            total_stat_value = 0
            value_key = f"{mode}_{mkey}"  # e.g. 'rush_final_kills'
            _map_dict[value_key] = _map_dict[mkey]
            for key in data:  # e.g. 'eight_two_rush_final_kills'
                # if 'eight_two_rush_final_kills' ends with 'rush_final_kills'
                if key.endswith(value_key):
                    # rush final kills value += data['eight_two_rush_final_kills']
                    total_stat_value += data[key]

            data[value_key] = total_stat_value

    for mode in list(BEDWARS_MAPPING_FULL.values()) + [""]:
        if mode:
            mode_ = mode + "_"
        else:
            mode_ = mode

        for key in keys:  # TODO: preload this
            _map_dict[f"{mode}_{key}"] = _map_dict[key]

        kills = data[f"{mode_}kills_bedwars"]
        deaths = data[f"{mode_}deaths_bedwars"]

        finals = data[f"{mode_}final_kills_bedwars"]
        final_deaths = data[f"{mode_}final_deaths_bedwars"]

        beds = data[f"{mode_}beds_broken_bedwars"]
        beds_lost = data[f"{mode_}beds_lost_bedwars"]

        wins = data[f"{mode_}wins_bedwars"]
        losses = data[f"{mode_}losses_bedwars"]

        data[f"{mode_}fkdr"] = safe_div(finals, final_deaths)
        data[f"{mode_}kdr"] = safe_div(kills, deaths)
        data[f"{mode_}wlr"] = safe_div(wins, losses)
        data[f"{mode_}bblr"] = safe_div(beds, beds_lost)

    for key in data:
        if func := _map_dict.get(key):
            data[key] = func(data[key])  # type: ignore

    return data
