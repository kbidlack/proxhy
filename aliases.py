class Gamemode:
    # TODO add more aliases (duels, )
    gamemodes = {
        "bedwars": {"bedwars", "bw"},
        "skywars": {"skywars", "sw", 's'}
    }

    def __new__(cls, value: str):
        value = value or "" # .lower() doesn't work on None
        gamemode = (g for g, a in cls.gamemodes.items() if value.lower() in a)
        return next(gamemode, None)


class Statistic:
    # TODO add more stats
    bedwars = {
        "Finals": {"finals", "final", "fk", "fks"},
        "FKDR": {"fkdr", "fk/d"},
        "Wins": {"wins", "win", 'w'},
        "WLR": {"wlr", "w/l"}
    }
    skywars = {
        "Kills": {"kills", "kill", 'k'},
        "KDR": {"kdr", "k/d"},
        "Wins": {"wins", "win", 'w'},
        "WLR": {"wlr", "w/l"}
    }

    def __new__(cls, stat: str, mode: str):
        stat = stat or "" # .lower() doesn't work on None
        if gamemode := getattr(cls, mode, None):
            stats = (s for s, a in gamemode.items() if stat.lower() in a)
            return next(stats, None)