import inspect

from hypixel.errors import InvalidApiKey, PlayerNotFound
from quarry.types.buffer import Buffer1_7

from formatting import (color_bw_stars, format_bw_finals, format_bw_fkdr,
                        format_bw_wins, format_bw_wlr, get_rank)
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
            bridge.downstream.send_packet(
                "chat_message",
                pack_chat(f"§9§l∎ §4Command <{segments[0]}> takes no arguments!")
            )
        elif len(args) > len(self.parameters):
            bridge.downstream.send_packet(
                "chat_message",
                pack_chat(f"§9§l∎ §4Command <{segments[0]}> takes at most {len(self.parameters)} argument(s)!")
            )
        elif len(args) < len(self.required_parameters):
            names = ', '.join([param.name for param in self.required_parameters])
            bridge.downstream.send_packet(
                "chat_message",
                pack_chat(f"§9§l∎ §4Command <{segments[0]}> needs at least {len(self.required_parameters)} arguments! ({names})")
            )
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
            bridge.downstream.send_packet("chat_message", pack_chat(err.message))
        else:
            if output:
                if segments[0].startswith('//'): # send output of command
                    bridge.upstream.send_packet("chat_message", buff.pack_string(output))
                else:
                    bridge.downstream.send_packet("chat_message", pack_chat(output))
    else:
        buff.restore()
        bridge.upstream.send_packet("chat_message", buff.pack_string(message))


# COMMANDS
@command("rq")
def requeue(bridge, buff: Buffer1_7):
    if bridge.game.get('mode') is None:
        raise CommandException("§9§l∎ §4No game to requeue!")
    else:
        bridge.upstream.send_packet(
            "chat_message",
            buff.pack_string(f"/play {bridge.game['mode']}")
        )
        
@command("garlicbread") # Mmm, garlic bread.
def garlicbread(bridge, buff: Buffer1_7): # Mmm, garlic bread.
       return "§eMmm, garlic bread." # Mmm, garlic bread.

@command("sc", "cs")
def statcheck(bridge, buff: Buffer1_7, ign=None, gamemode=None):
    if gamemode is None:
        # TODO check for gamemode aliases
        gamemode = bridge.game.get('mode')
    if ign is None:
        ign = bridge.username
    
    client: Client = bridge.client
    try:
        player = client.player(ign)[0]
        losses = player.bedwars.losses or 1 # ZeroDivisionError

        stats_message = color_bw_stars(player.bedwars.level)
        stats_message += f"§f {get_rank(player)} {player.name} "
        stats_message += f"§fFKDR: {format_bw_fkdr(player.bedwars.fkdr)} "
        stats_message += f"Wins: {format_bw_wins(player.bedwars.wins)} "
        stats_message += f"Finals: {format_bw_finals(player.bedwars.final_kills)} "
        stats_message += f"WLR: {format_bw_wlr(round(player.bedwars.wins / losses, 2))}"
        return stats_message
    except PlayerNotFound: 
        raise CommandException(f"§9§l∎ §4Player '{ign}' not found!")
    except InvalidApiKey:
        raise CommandException(f"§9§l∎ §4Invalid API Key!")
