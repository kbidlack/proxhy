import inspect
import re

from hypixel.errors import HypixelException, InvalidApiKey, PlayerNotFound
from quarry.types.buffer import Buffer1_7

from aliases import Gamemode, Statistic
from errors import CommandException
from formatting import FormattedPlayer
from patches import Client

commands = {}


class Parameter:
    def __init__(self, param):
        self.name = param.name

        if param.default is not inspect._empty:
            self.default = param.default
            self.required = False
        else:
            self.required = True
        
        if param.kind is inspect.Parameter.VAR_POSITIONAL: # *args
            self.infinite = True
            self.required = False
        else:
            self.infinite = False


class Command:
    def __init__(self, function, *aliases) -> None:
        self.function = function
        self.name = function.__name__

        sig = inspect.signature(function)
        # first two parameters should be bridge and buff
        self.parameters = [
            Parameter(sig.parameters[param])
            for param in sig.parameters
        ][2:]
        self.required_parameters = [
            param for param in self.parameters if param.required
        ]

        self.aliases = aliases
        commands.update({self.name: self})
        for alias in self.aliases:
            commands.update({alias: self})

    # decorator 
    def __call__(self, bridge, buff: Buffer1_7, message: str):
        segments = message.split()
        args = segments[1:]
        if not self.parameters and args:
            raise CommandException(
                f"§9§l∎ §4Command <{segments[0]}> takes no arguments!"
            )
        elif ((len(args) > len(self.parameters))
              and not any(p.infinite for p in self.parameters)):
            raise CommandException(
                f"§9§l∎ §4Command <{segments[0]}> takes at most"
                f"{len(self.parameters)} argument(s)!"
            )
        elif len(args) < len(self.required_parameters):
            names = ', '.join([
                param.name for param in self.required_parameters
            ])
            raise CommandException(
                f"§9§l∎ §4Command <{segments[0]}> needs at least"
                f"{len(self.required_parameters)} arguments! ({names})"
            )
        else:
            return self.function(bridge, buff, *args)

def run_command(bridge, buff, message: str):
    segments = message.split()
    command = (commands.get(segments[0].removeprefix('/'))
        or commands.get(segments[0].removeprefix('//')))
    if command:
        try:
            output = command(bridge, buff, message)
        except CommandException as err:
            bridge.downstream.send_chat(err.message)
        else:
            if output:
                if segments[0].startswith('//'): # send output of command
                    # remove chat formatting
                    output = re.sub(r'§.', '', output)
                    bridge.upstream.send_chat(output)
                else:
                    bridge.downstream.send_chat(output)
    else:
        buff.restore()
        bridge.upstream.send_chat(message)

def command(*aliases):
    return lambda func: Command(func, *aliases)


# COMMANDS
@command("rq")
def requeue(bridge, buff: Buffer1_7):
    if not bridge.settings.game.mode:
        raise CommandException("§9§l∎ §4No game to requeue!")
    else:
        bridge.upstream.send_chat(f"/play {bridge.settings.game.mode}")
        
@command() # Mmm, garlic bread. 
def garlicbread(bridge, buff: Buffer1_7): # Mmm, garlic bread. 
       return "§eMmm, garlic bread." # Mmm, garlic bread. 

@command("sc")
def statcheck(bridge, buff: Buffer1_7, ign=None, mode=None, *stats):
    # TODO default gamemode is hypixel stats
    ign = ign or bridge.username
    # verify gamemode
    if mode is None:
        gamemode = Gamemode(bridge.settings.game.gametype) or "bedwars"
    elif (gamemode := Gamemode(mode)) is None:
        raise CommandException(f"§9§l∎ §4Unknown gamemode '{mode}'!")

    # verify stats 
    if not stats:
        if gamemode == "bedwars":
            stats = ("Finals", "FKDR", "Wins", "WLR")
        elif gamemode == "skywars":
            stats = ("Kills", "KDR", "Wins", "WLR")
    elif any(Statistic(stat, gamemode) is None for stat in stats):
        unknown_stat = next(
            (stat for stat in stats if Statistic(stat, gamemode) is None)
        )
        raise CommandException(
            f"§9§l∎ §4Unknown statistic '{unknown_stat}' "
            f"for gamemode {gamemode}!"
        )
    else:
        stats = tuple(Statistic(stat, gamemode) for stat in stats)

    client: Client = bridge.client
    player = client.player(ign)

    if isinstance(player, PlayerNotFound):
        raise CommandException(f"§9§l∎ §4Player '{ign}' not found!")
    elif isinstance(player, InvalidApiKey):
        raise CommandException(f"§9§l∎ §4Invalid API Key!")
    elif isinstance(player, HypixelException):
        raise CommandException(
            f"§9§l∎ §4An unknown error occurred"
            f"while fetching player '{ign}'! ({player})"
        )

    fplayer = FormattedPlayer(player)
    return fplayer.format_stats(gamemode, stats)


# DEBUG
@command('t')
def teams(bridge, _):
    print(bridge.settings.teams)