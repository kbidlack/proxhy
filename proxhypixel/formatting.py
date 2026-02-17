# nearly 500 lines of fake code
# credit for most of the busywork goes to someone other than me
from collections import defaultdict
from math import floor

from hypixel import Player
from hypixel.color import Color

from proxhy.argtypes.hypixel import GAMETYPE_T
from proxhy.utils import safe_div
from proxhypixel.mappings import (
    BEDWARS_DREAM_MAPPING_SIMPLE,
    BEDWARS_MAPPING_FULL,
)

SUPPORTED_MODES: set[GAMETYPE_T] = {"bedwars"}


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
        return f"§6[MVP{plus}++§6]"
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


def format_other(other):
    return "§7" + str(other)


# BEDWARS
def format_bw_fkdr(fkdr):
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


def format_bw_wins(wins):
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


def format_bw_finals(finals):
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


def format_bw_wlr(wlr):
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


def format_bw_star(level):
    # Thanks a ton to Tiget on the hypixel forums for creating a list of all the prestige colors up to 3000
    # ^ I can't find this post but here's one with up to 2000:
    # https://hypixel.net/threads/tool-bedwars-prestige-colors-in-minecraft-color-code-and-hex-code-high-effort-post.3841719/
    stars = ""
    colors = ["§7", "§f", "§6", "§b", "§2", "§3", "§4", "§d", "§9", "§5"]

    if level < 1000:
        stars = f"{colors[int(level // 100)]}[{level}✫]"
    elif level < 1100:
        level = str(level)
        stars += f"§c[§6{level[0]}§e{level[1]}§a{level[2]}§b{level[3]}§d✫§5]"
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
        level = str(level)
        stars += f"§8[§7{level[0]}§f{level[1:3]}§7{level[3]}✪§8]"
    elif level < 2200:
        level = str(level)
        stars += f"§f[{level[0]}§e{level[1:3]}§6{level[3]}⚝]"
    elif level < 2300:
        level = str(level)
        stars += f"§6[{level[0]}§f{level[1:3]}§b{level[3]}§3⚝]"
    elif level < 2400:
        level = str(level)
        stars += f"§5[{level[0]}§d{level[1:3]}§6{level[3]}§e⚝]"
    elif level < 2500:
        level = str(level)
        stars += f"§b[{level[0]}§f{level[1:3]}§7{level[3]}⚝§8]"
    elif level < 2600:
        level = str(level)
        stars += f"§f[{level[0]}§a{level[1:3]}§2{level[3]}⚝]"
    elif level < 2700:
        level = str(level)
        stars += f"§4[{level[0]}§c{level[1:3]}§d{level[3]}⚝§5]"
    elif level < 2800:
        level = str(level)
        stars += f"§e[{level[0]}§f{level[1:3]}§8{level[3]}⚝]"
    elif level < 2900:
        level = str(level)
        stars += f"§a[{level[0]}§2{level[1:3]}§6{level[3]}⚝§e]"
    elif level < 3000:
        level = str(level)
        stars += f"§b[{level[0]}§3{level[1:3]}§9{level[3]}⚝§1]"
    elif level < 3100:
        level = str(level)
        stars += f"§e[{level[0]}§6{level[1:3]}§c{level[3]}⚝§4]"
    elif level < 3200:  # oh my god all of these were so bad to make someone save
        level = str(level)
        stars += f"§9[{level[0]}§3{level[1:3]}§6{level[3]}✥§3]"
    elif level < 3300:
        level = str(level)
        stars += f"§c[§4{level[0]}§7{level[1:3]}§4{level[3]}§c✥]"
    elif level < 3400:
        level = str(level)
        stars += f"§9[{level[0:2]}§d{level[2]}§c{level[3]}✥§4]"
    elif level < 3500:
        level = str(level)
        stars += f"§2[§a{level[0]}§d{level[1:3]}§c{level[3]}✥§2]"
    elif level < 3600:
        level = str(level)
        stars += f"§c[{level[0]}§4{level[1:3]}§2{level[3]}§a✥]"
    elif level < 3700:
        level = str(level)
        stars += f"§a[{level[0:2]}§b{level[2]}§9{level[3]}✥§1]"
    elif level < 3800:
        level = str(level)
        stars += f"§4[{level[0]}§c{level[1:3]}§c{level[3]}§3✥]"
    elif level < 3900:
        level = str(level)
        stars += f"§1[{level[0]}§9{level[1]}§5{level[2:4]}§d✥§1]"
    elif level < 4000:
        level = str(level)
        stars += f"§c[{level[0]}§a{level[1:3]}§3{level[3]}§9✥]"
    elif level < 4100:
        level = str(level)
        stars += f"§5[{level[0]}§c{level[1:3]}§6{level[3]}✥§e]"
    elif level < 4200:
        level = str(level)
        stars += f"§e[{level[0]}§6{level[1]}§c{level[2]}§d{level[3]}✥§5]"
    elif level < 4300:
        level = str(level)
        stars += f"§1[§9{level[0]}§3{level[1]}§b{level[2]}§f{level[3]}§7✥]"
    elif level < 4400:
        level = str(level)
        stars += f"§0[§5{level[0]}§8{level[1:3]}§5{level[3]}✥§0]"
    elif level < 4500:
        level = str(level)
        stars += f"§2[{level[0]}§a{level[1]}§e{level[2]}§6{level[3]}§5✥§d]"
    elif level < 4600:
        level = str(level)
        stars += f"§f[{level[0]}§b{level[1:3]}§3{level[3]}✥]"
    elif level < 4700:
        level = str(level)
        stars += f"§3[§b{level[0]}§e{level[1:3]}§6{level[3]}§d✥§5]"
    elif level < 4800:
        level = str(level)
        stars += f"§f[§4{level[0]}§c{level[1:3]}§9{level[3]}§1✥§9]"
    elif level < 4900:
        level = str(level)
        stars += f"§5[{level[0]}§c{level[1]}§6{level[2]}§e{level[3]}§b✥§3]"
    elif level < 5000:
        level = str(level)
        stars += f"§2[§a{level[0]}§f{level[1:3]}§a{level[3]}✥§2]"
    else:
        level = str(level)
        stars += f"§4[{level[0]}§5{level[1]}§9{level[2:4]}§1✥§0]"

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


def sw_icon(player: Player):
    # Thanks SO MUCH to hxzelx on the forums for making a list of all of these.
    # If I had to search up all of these it would be joever
    icons = {
        "angel_1": "★",
        "angel_2": "☆",
        "angel_3": "⁕",
        "angel_4": "✶",
        "angel_5": "✳",
        "angel_6": "✴",
        "angel_7": "✷",
        "angel_8": "❋",
        "angel_9": "✼",
        "angel_10": "❂",
        "angel_11": "❁",
        "angel_12": "☬",
        "omega_icon": "Ω",
        "favor_icon": "⚔",
        "default": "⋆",
        "iron_prestige": "✙",
        "gold_prestige": "❤",
        "diamond_prestige": "☠",
        "emerald_prestige": "✦",
        "sapphire_prestige": "✌",
        "ruby_prestige": "❦",
        "crystal_prestige": "✵",
        "opal_prestige": "❣",
        "amethyst_prestige": "☯",
        "rainbow_prestige": "✺",
        "first_class_prestige": "✈",
        "assassin_prestige": "⚰",
        "veteran_prestige": "✠",
        "god_like_prestige": "♕",
        "warrior_prestige": "⚡",
        "captain_prestige": "⁂",
        "soldier_prestige": "✰",
        "infantry_prestige": "⁑",
        "sergeant_prestige": "☢",
        "lieutenant_prestige": "✥",
        "admiral_prestige": "♝",
        "general_prestige": "♆",
        "villain_prestige": "☁",
        "skilled_prestige": "⍟",
        "sneaky_prestige": "♗",
        "overlord_prestige": "♔",
        "war_chief_prestige": "♞",
        "warlock_prestige": "✏",
        "emperor_prestige": "❈",
        "mythic_prestige": "§lಠ§d_§5ಠ",
    }
    try:
        return icons[player._data["stats"]["SkyWars"]["selected_prestige_icon"]]
    except KeyError:  # occasionally there are errors with the default icon
        return "⋆"


def format_sw_star(level, player: Player):
    stars = ""
    colors = ["§7", "§f", "§6", "§b", "§2", "§3", "§4", "§d", "§9", "§5"]
    level = floor(level)
    if level < 50:
        stars = f"{colors[int(level // 5)]}[{level}{sw_icon(player)}]"
    elif level < 55:
        level = str(level)
        stars = f"§c[§6{level[0]}§e{level[1]}§a{sw_icon(player)}§b]"
    elif level < 60:
        stars = f"§7[§f{level}{sw_icon(player)}§7]"
    elif level < 65:
        stars = f"§4[§c{level}{sw_icon(player)}§4]"
    elif level < 70:
        stars = f"§c[§f{level}{sw_icon(player)}§c]"
    elif level < 75:
        stars = f"§e[§6{level}{sw_icon(player)}§7]"
    elif level < 80:
        stars = f"§f[§1{level}{sw_icon(player)}§f]"
    elif level < 85:
        stars = f"§f[§b{level}{sw_icon(player)}§f]"
    elif level < 90:
        stars = f"§f[§3{level}{sw_icon(player)}§f]"
    elif level < 95:
        stars = f"§a[§3{level}{sw_icon(player)}§a]"
    elif level < 100:
        stars = f"§c[§e{level}{sw_icon(player)}§c]"
    elif level < 105:
        stars = f"§9[§1{level}{sw_icon(player)}§9]"
    elif level < 110:
        stars = f"§6[§4{level}{sw_icon(player)}§6]"
    elif level < 115:
        stars = f"§1[§d{level}{sw_icon(player)}§1]"
    elif level < 120:
        stars = f"§8[§7{level}{sw_icon(player)}§8]"
    elif level < 125:
        stars = f"§d[§5{level}{sw_icon(player)}§d]"
    elif level < 130:
        stars = f"§f[§e{level}{sw_icon(player)}§f]"
    elif level < 135:
        stars = f"§c[§e{level}{sw_icon(player)}§c]"
    elif level < 140:
        stars = f"§6[§c{level}{sw_icon(player)}§6]"
    elif level < 145:
        stars = f"§a[§c{level}{sw_icon(player)}§a]"
    elif level < 150:
        stars = f"§a[§b{level}{sw_icon(player)}§a]"
    else:
        level = str(level)
        stars = f"§l§c§k[§r§6§l{level[0]}§e§l{level[1]}§a§l{level[2]}§b§l{sw_icon(player)}§l§c§k]§r"
    return stars


def format_player_dict(player: Player | dict, gamemode: GAMETYPE_T):
    data = _resolve_player(player)
    if gamemode == "bedwars":
        bedwars_data = data.get("stats", {}).get("Bedwars", {})
        fdict = dict(format_bedwars_dict(bedwars_data))
        level = bedwars_data.get("bedwars_level", 1)
        finals = bedwars_data.get("final_kills_bedwars", 0)
        final_deaths = bedwars_data.get("final_deaths_bedwars", 0)
        fdict["star"] = format_bw_star(level)
        fdict["raw_level"] = level
        fdict["raw_fkdr"] = safe_div(finals, final_deaths)
        fdict["rankname"] = get_rankname(data)
        fdict["raw_name"] = data.get("displayname", "")
        return fdict
    else:
        raise NotImplementedError("this is not implemented 🤯")


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
            data[key] = func(data[key])

    return data
