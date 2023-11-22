from copy import deepcopy

from hypixel import Player

from math import floor

def get_rank(player):
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
        return  "§4[COOL]"
    elif player.name == "KyngK":
        return "§2[§eS§2T§eI§2N§eK§2Y§e]§2"
    return "§7" # if there are any other weird ranks because you never know ig, also nons lmfao

def return_plus_color(player):
    if player.plus_color:
        return player.plus_color.chat_code
    else:
        return "§c"

# BEDWARS 
def format_bw_fkdr(fkdr):
    if fkdr < 1:
        return "§7" + str(fkdr) + "§f" 
    elif fkdr < 2.5:
        return "§e" + str(fkdr) + "§f"
    elif fkdr < 5:
        return "§2" + str(fkdr) + "§f"
    elif fkdr < 10:
        return "§b" + str(fkdr) + "§f"
    elif fkdr < 20:
        return "§4" + str(fkdr) + "§f"
    elif fkdr < 50:
        return "§5" + str(fkdr) + "§f"
    elif fkdr < 100:
        return "§c" + str(fkdr) + "§f"
    elif fkdr < 300:
        return "§d" + str(fkdr) + "§f"
    elif fkdr < 1000:
        return "§9" + str(fkdr) + "§f"
    else:
        return "§0" + str(fkdr) + "§f"

def format_bw_wins(wins):
    if wins < 250:
        return "§7" + str(wins) + "§f" 
    elif wins < 1000:
        return "§e" + str(wins) + "§f"
    elif wins < 2500:
        return "§2" + str(wins) + "§f"
    elif wins < 8000:
        return "§b" + str(wins) + "§f"
    elif wins < 15000:
        return "§4" + str(wins) + "§f"
    elif wins < 40000:
        return "§5" + str(wins) + "§f"
    else:
        return "§d" + str(wins) + "§f"
 
def format_bw_finals(finals):
    if finals < 1000:
        return "§7" + str(finals) + "§f" 
    elif finals < 4000:
        return "§e" + str(finals) + "§f"
    elif finals < 10000:
        return "§2" + str(finals) + "§f"
    elif finals < 25000:
        return "§b" + str(finals) + "§f"
    elif finals < 50000:
        return "§4" + str(finals) + "§f"
    elif finals < 100000:
        return "§5" + str(finals) + "§f"
    else:
        return "§d" + str(finals) + "§f"

def format_bw_wlr(wlr):
    if wlr < .5:
        return "§7" + str(wlr) + "§f" 
    elif wlr < 1:
        return "§e" + str(wlr) + "§f"
    elif wlr < 2.5:
        return "§2" + str(wlr) + "§f"
    elif wlr < 5:
        return "§b" + str(wlr) + "§f"
    elif wlr < 10:
        return "§4" + str(wlr) + "§f"
    elif wlr < 25:
        return "§5" + str(wlr) + "§f"
    elif wlr < 100:
        return "§c" + str(wlr) + "§f"
    elif wlr < 300:
        return "§d" + str(wlr) + "§f"
    elif wlr < 1000:
        return "§9" + str(wlr) + "§f"
    else:
        return "§d" + str(wlr) + "§f"       

def format_bw_star(level): # Thanks a ton to Tiget on the hypixel forums for creating a list of all the prestige colors up to 3000
    stars = ""
    colors = ["§7", "§f", "§6", "§b", "§2", "§3", "§4", "§d", "§9", "§5"]

    if level < 1000:
        stars = f"{colors[level // 100]}[{level}✫]"
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
    elif level < 3200: # oh my god all of these were so bad to make someone save
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
        return "§7" + str(kills) + "§f" 
    elif kills < 5000:
        return "§e" + str(kills) + "§f"
    elif kills < 15000:
        return "§2" + str(kills) + "§f"
    elif kills < 30000:
        return "§b" + str(kills) + "§f"
    elif kills < 50000:
        return "§4" + str(kills) + "§f"
    elif kills < 10000:
        return "§5" + str(kills) + "§f"
    elif kills < 250000:
        return "§c" + str(kills) + "§f"
    elif kills < 500000:
        return "§d" + str(kills) + "§f"
    else:
        return "§0" + str(kills) + "§f"

def format_sw_wins(wins):
    if wins < 250:
        return "§7" + str(wins) + "§f" 
    elif wins < 1000:
        return "§e" + str(wins) + "§f"
    elif wins < 3000:
        return "§2" + str(wins) + "§f"
    elif wins < 7500:
        return "§b" + str(wins) + "§f"
    elif wins < 15000:
        return "§4" + str(wins) + "§f"
    elif wins < 30000:
        return "§5" + str(wins) + "§f"
    elif wins < 60000:
        return "§c" + str(wins) + "§f"
    elif wins < 100000:
        return "§d" + str(wins) + "§f"
    else:
        return "§0" + str(wins) + "§f"

def format_sw_kdr(kdr):
    if kdr < .75:
        return "§7" + str(kdr) + "§f" 
    elif kdr < 1.5:
        return "§e" + str(kdr) + "§f"
    elif kdr < 3:
        return "§2" + str(kdr) + "§f"
    elif kdr < 5:
        return "§b" + str(kdr) + "§f"
    elif kdr < 10:
        return "§4" + str(kdr) + "§f"
    elif kdr < 25:
        return "§5" + str(kdr) + "§f"
    elif kdr < 50:
        return "§c" + str(kdr) + "§f"
    elif kdr < 100:
        return "§d" + str(kdr) + "§f"
    elif kdr < 250:
        return "§9" + str(kdr) + "§f"
    else:
        return "§0" + str(kdr) + "§f"

def format_sw_wlr(wlr):
    if wlr < .1:
        return "§7" + str(wlr) + "§f" 
    elif wlr < .2:
        return "§e" + str(wlr) + "§f"
    elif wlr < .4:
        return "§2" + str(wlr) + "§f"
    elif wlr < .75:
        return "§b" + str(wlr) + "§f"
    elif wlr < 1:
        return "§4" + str(wlr) + "§f"
    elif wlr < 2.5:
        return "§5" + str(wlr) + "§f"
    elif wlr < 5:
        return "§c" + str(wlr) + "§f"
    elif wlr < 10:
        return "§d" + str(wlr) + "§f"
    elif wlr < 25:
        return "§9" + str(wlr) + "§f"
    else:
        return "§0" + str(wlr) + "§f"

def sw_icon(player): # Thanks SO MUCH to hxzelx on the forums for making a list of all of these. If I had to search up all of these it would be joever
    icons = {"angel_1":"★", "angel_2":"☆", "angel_3":"⁕", "angel_4":"✶","angel_5":"✳","angel_6":"✴","angel_7":"✷",
             "angel_8":"❋","angel_9":"✼","angel_10":"❂","angel_11":"❁","angel_12":"☬","omega_icon":"Ω",
             "favor_icon":"⚔","default":"⋆","iron_prestige":"✙","gold_prestige":"❤","diamond_prestige":"☠",
             "emerald_prestige":"✦","sapphire_prestige":"✌","ruby_prestige":"❦","crystal_prestige":"✵","opal_prestige":"❣",
             "amethyst_prestige":"☯","rainbow_prestige":"✺","first_class_prestige":"✈","assassin_prestige":"⚰",
             "veteran_prestige":"✠","god_like_prestige":"♕","warrior_prestige":"⚡","captain_prestige":"⁂",
             "soldier_prestige":"✰","infantry_prestige":"⁑","sergeant_prestige":"☢","lieutenant_prestige":"✥",
             "admiral_prestige":"♝","general_prestige":"♆","villain_prestige":"☁","skilled_prestige":"⍟",
             "sneaky_prestige":"♗","overlord_prestige":"♔","war_chief_prestige":"♞","warlock_prestige":"✏",
             "emperor_prestige":"❈","mythic_prestige":"§lಠ§d_§5ಠ"}
    try:
        return icons[player._data["stats"]["SkyWars"]["selected_prestige_icon"]]
    except: # Occasionally there are errors with the default icon
        return "⋆"
    
def format_sw_star(level, player):
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
        stars = f"§l§c§k[§r§6{level[0]}§e{level[1]}§a{level[2]}§b{sw_icon(player)}§l§c§k]§r"
    return stars
    
        
    

# add attributes to player object
def format_player(player: Player) -> Player:
    new_player = deepcopy(player)

    new_player.rank = get_rank(player)
    if new_player.rank == "§7": # non, no space needed
        new_player.name = f"§f{new_player.rank}{player.name}§f"
    else:
        new_player.name = f"§f{new_player.rank} {player.name}§f"

    new_player.bedwars.level = format_bw_star(player.bedwars.level)
    new_player.bedwars.final_kills = format_bw_finals(player.bedwars.final_kills)
    new_player.bedwars.fkdr = format_bw_fkdr(player.bedwars.fkdr)
    new_player.bedwars.wins = format_bw_wins(player.bedwars.wins)
    new_player.bedwars.wlr = format_bw_wlr(player.bedwars.wlr)

    new_player.skywars.level = format_sw_star(player.skywars.level, player)
    new_player.skywars.kills = format_sw_kills(player.skywars.kills)
    new_player.skywars.wins = format_sw_wins(player.skywars.wins)
    new_player.skywars.kdr = format_sw_kdr(player.skywars.kdr)
    new_player.skywars.wlr = format_sw_wlr(player.skywars.wlr)

    return new_player