import inspect
import re

from hypixel.errors import HypixelException, InvalidApiKey, PlayerNotFound
from quarry.types.buffer import Buffer1_7
from twisted.internet import reactor
from twisted.python import threadable

from formatting import FormattedPlayer
from patches import Client, pack_chat

commands = {}


class CommandException(Exception):
    """If a command has an error then stuff happens"""
    def __init__(self, message):
        self.message = message


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
        self.parameters = [Parameter(sig.parameters[param]) for param in sig.parameters][2:]
        self.required_parameters = [param for param in self.parameters if param.required]

        self.aliases = aliases
        commands.update({self.name: self})
        for alias in self.aliases:
            commands.update({alias: self})

    # decorator 
    def __call__(self, bridge, buff: Buffer1_7, message: str):
        segments = message.split()
        args = segments[1:]
        if not self.parameters and args:
            raise CommandException(f"§9§l∎ §4Command <{segments[0]}> takes no arguments!")
        elif (len(args) > len(self.parameters)) and not any(p.infinite for p in self.parameters):
            raise CommandException(f"§9§l∎ §4Command <{segments[0]}> takes at most {len(self.parameters)} argument(s)!")
        elif len(args) < len(self.required_parameters):
            names = ', '.join([param.name for param in self.required_parameters])
            raise CommandException(f"§9§l∎ §4Command <{segments[0]}> needs at least {len(self.required_parameters)} arguments! ({names})")
        else:
            return self.function(bridge, buff, *args)

def command(*aliases):
    return lambda func: Command(func, *aliases)

def run_command(bridge, buff, message: str):
    segments = message.split()
    command = commands.get(segments[0].removeprefix('/')) or commands.get(segments[0].removeprefix('//'))
    if command:
        try:
            output = command(bridge, buff, message)
        except CommandException as err:
            reactor.callFromThread(bridge.downstream.send_packet, "chat_message", pack_chat(err.message))
        else:
            if output:
                if segments[0].startswith('//'): # send output of command
                    # remove chat formatting
                    output = re.sub(r'§.', '', output)
                    reactor.callFromThread(bridge.upstream.send_packet, "chat_message", buff.pack_string(output))
                else:
                    reactor.callFromThread(bridge.downstream.send_packet, "chat_message", pack_chat(output))
    else:
        buff.restore()
        reactor.callFromThread(bridge.upstream.send_packet, "chat_message", buff.pack_string(message))


# COMMANDS
@command("rq")
def requeue(bridge, buff: Buffer1_7):
    if not bridge.game.mode:
        raise CommandException("§9§l∎ §4No game to requeue!")
    else:
        reactor.callFromThread(
            bridge.upstream.send_packet,
            "chat_message",
            buff.pack_string(f"/play {bridge.game.mode}")
        )
        
@command() # Mmm, garlic bread. 
def garlicbread(bridge, buff: Buffer1_7): # Mmm, garlic bread. 
       return "§eMmm, garlic bread." # Mmm, garlic bread. 

@command("sc")
def statcheck(bridge, buff: Buffer1_7, ign=None, gamemode=None, *stats):
    ign = ign or bridge.username
    gamemode = gamemode or bridge.game.gametype

    client: Client = bridge.client
    player = FormattedPlayer(client.player(ign))

    if isinstance(player, PlayerNotFound):
        raise CommandException(f"§9§l∎ §4Player '{ign}' not found!")
    elif isinstance(player, InvalidApiKey):
        raise CommandException(f"§9§l∎ §4Invalid API Key!")
    elif isinstance(player, HypixelException):
        raise CommandException(
            f"§9§l∎ §4An unknown error occurred"
            f"while fetching player '{ign}'! ({player})"
        )

    # TODO move to formatting.py
    # TODO check for gamemode aliases
    if gamemode in sw:
        stats_message = '§f '.join((
            player.skywars.level,
            player.rankname,
            f"Kills: {player.skywars.kills}",
            f"KDR: {player.skywars.kdr}",
            f"Wins: {player.skywars.wins}",
            f"WLR: {player.skywars.wlr}"
        ))
    else:
        stats_message = '§f '.join((
            player.bedwars.level,
            player.rankname,
            f"Kills: {player.bedwars.final_kills}",
            f"FKDR: {player.bedwars.fkdr}",
            f"Wins: {player.bedwars.wins}",
            f"WLR: {player.bedwars.wlr}"
        ))
    return stats_message 
 

# WIP gamemode aliases
sw = ["solo_normal","solo_insane","teams_normal","teams_insane","mega_normal","mega_doubles",
      "solo_insane_tnt_madness","teams_insane_tnt_madness","solo_insane_rush","teams_insane_rush",
      "solo_insane_slime","teams_insane_slime","solo_insane_lucky","teams_insane_lucky",
      "solo_insane_hunters_vs_beasts","sw","SW","skywars"]

# TESTING
@command('t')
def teams(bridge, buff):
    print(bridge.teams)