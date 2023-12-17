class Gamemode:
    # TODO add more aliases (duels, )
    gamemodes = {
        "bedwars": frozenset({"bedwars", "bw"}),
        "skywars": frozenset({"skywars", "sw", "s"}),
    }

    def __new__(cls, value: str):
        value = value or ""  # .lower() doesn't work on None
        gamemode = (g for g, a in cls.gamemodes.items() if value.lower() in a)
        return next(gamemode, None)


class Statistic:
    # TODO add more stats
    bedwars = {
        "Finals": frozenset({"finals", "final", "fk", "fks"}),
        "FKDR": frozenset({"fkdr", "fk/d"}),
        "Wins": frozenset({"wins", "win", "w"}),
        "WLR": frozenset({"wlr", "w/l"}),
    }
    skywars = {
        "Kills": frozenset({"kills", "kill", "k"}),
        "KDR": frozenset({"kdr", "k/d"}),
        "Wins": frozenset({"wins", "win", "w"}),
        "WLR": frozenset({"wlr", "w/l"}),
    }

    def __new__(cls, stat: str, mode: str):
        stat = stat or ""  # .lower() doesn't work on None
        if gamemode := getattr(cls, mode, None):
            stats = (s for s, a in gamemode.items() if stat.lower() in a)
            return next(stats, None)
