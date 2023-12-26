from copy import deepcopy
from math import floor

from hypixel import Player


def get_rank(player: Player):
    if player.rank == "VIP":
        return "§a[VIP]"
    elif player.rank == "VIP+":
        return "§a[VIP§6+§a]"
    elif player.rank == "MVP":
        return "§b[MVP]"
    elif player.rank == "MVP+":
        plus = return_plus_color(player)
        return f"§b[MVP{plus}+§b]"
    elif player.rank == "MVP++":
        plus = return_plus_color(player)
        return f"§6[MVP{plus}++§6]"
    elif player.rank == "ADMIN" or player.rank == "OWNER":
        return f"§c[{player.rank}]"
    elif player.rank == "GAME MASTER":
        return "§2[GM]"
    elif player.rank == "YOUTUBE":
        return "§c[§fYOUTUBE§c]"
    elif player.rank == "PIG+++":
        return "§d[PIG§b+++§d]"
    if player.name == "Perlence":
        return "§4[COOL]"
    elif player.name == "KyngK":
        return "§2[§eS§2T§eI§2N§eK§2Y§e]§2"
    return "§7"  # if there are any other weird ranks because you never know ig, also nons lmfao


def return_plus_color(player: Player):
    if player.plus_color:
        return player.plus_color.chat_code
    else:
        return "§c"


# BEDWARS
def format_bw_fkdr(fkdr):
    if fkdr < 1:
        return "§7" + str(fkdr)
    elif fkdr < 2.5:
        return "§e" + str(fkdr)
    elif fkdr < 5:
        return "§2" + str(fkdr)
    elif fkdr < 10:
        return "§b" + str(fkdr)
    elif fkdr < 20:
        return "§4" + str(fkdr)
    elif fkdr < 50:
        return "§5" + str(fkdr)
    elif fkdr < 100:
        return "§c" + str(fkdr)
    elif fkdr < 300:
        return "§d" + str(fkdr)
    elif fkdr < 1000:
        return "§9" + str(fkdr)
    else:
        return "§0" + str(fkdr)


def format_bw_wins(wins):
    if wins < 250:
        return "§7" + str(wins)
    elif wins < 1000:
        return "§e" + str(wins)
    elif wins < 2500:
        return "§2" + str(wins)
    elif wins < 8000:
        return "§b" + str(wins)
    elif wins < 15000:
        return "§4" + str(wins)
    elif wins < 40000:
        return "§5" + str(wins)
    else:
        return "§d" + str(wins)


def format_bw_finals(finals):
    if finals < 1000:
        return "§7" + str(finals)
    elif finals < 4000:
        return "§e" + str(finals)
    elif finals < 10000:
        return "§2" + str(finals)
    elif finals < 25000:
        return "§b" + str(finals)
    elif finals < 50000:
        return "§4" + str(finals)
    elif finals < 100000:
        return "§5" + str(finals)
    else:
        return "§d" + str(finals)


def format_bw_wlr(wlr):
    if wlr < 0.5:
        return "§7" + str(wlr)
    elif wlr < 1:
        return "§e" + str(wlr)
    elif wlr < 2.5:
        return "§2" + str(wlr)
    elif wlr < 5:
        return "§b" + str(wlr)
    elif wlr < 10:
        return "§4" + str(wlr)
    elif wlr < 25:
        return "§5" + str(wlr)
    elif wlr < 100:
        return "§c" + str(wlr)
    elif wlr < 300:
        return "§d" + str(wlr)
    elif wlr < 1000:
        return "§9" + str(wlr)
    else:
        return "§d" + str(wlr)


def format_bw_star(level):
    # Thanks a ton to Tiget on the hypixel forums for creating a list of all the prestige colors up to 3000
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
    except KeyError:  # Occasionally there are errors with the default icon
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


class FormattedPlayer:
    def __new__(cls, original_player: Player):
        player: cls = deepcopy(original_player)
        player.__class__ = cls

        player.rank = get_rank(player)
        player.name = player.name

        player.raw_rank = player.rank
        player.raw_name = player.name

        player.bedwars.level = format_bw_star(player.bedwars.level)
        player.bedwars.final_kills = format_bw_finals(player.bedwars.final_kills)
        player.bedwars.fkdr = format_bw_fkdr(player.bedwars.fkdr)
        player.bedwars.wins = format_bw_wins(player.bedwars.wins)
        player.bedwars.wlr = format_bw_wlr(player.bedwars.wlr)

        player.bedwars.raw_level = player.bedwars.level
        player.bedwars.raw_final_kills = player.bedwars.final_kills
        player.bedwars.raw_fkdr = player.bedwars.fkdr
        player.bedwars.raw_wins = player.bedwars.wins
        player.bedwars.raw_wlr = player.bedwars.wlr

        player.skywars.level = format_sw_star(player.skywars.level, player)
        player.skywars.kills = format_sw_kills(player.skywars.kills)
        player.skywars.kdr = format_sw_kdr(player.skywars.kdr)
        player.skywars.wins = format_sw_wins(player.skywars.wins)
        player.skywars.wlr = format_sw_wlr(player.skywars.wlr)

        player.skywars.raw_level = player.skywars.level
        player.skywars.raw_kills = player.skywars.kills
        player.skywars.raw_kdr = player.skywars.kdr
        player.skywars.raw_wins = player.skywars.wins
        player.skywars.raw_wlr = player.skywars.wlr

        # aliases
        player.bedwars.finals = player.bedwars.final_kills

        # other utils
        player.rank_color = player.rank[:2]
        sep: str = "" if player.rank == "§7" else " "  # no space for non
        player.rankname = sep.join((f"{player.rank}", f"{player.name}"))

        return player

    def format_stats(self, mode: str, *stats: str, sep=" ", name: bool = True) -> str:
        formatted_stats = [f"{getattr(getattr(self, mode), 'level')} {self.rankname}"]
        if name:
            formatted_stats += [
                f"{stat}: {getattr(getattr(self, mode), stat.lower())}"
                for stat in stats
            ]
        else:
            formatted_stats += [
                getattr(getattr(self, mode), stat.lower()) for stat in stats
            ]
        stats_message = f"§f{sep}".join(formatted_stats)

        return stats_message
