import inspect
from hypixel.errors import PlayerNotFound

from quarry.types.buffer import Buffer1_7

from patches import Client, pack_chat

commands = {}


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
            self.function(bridge, buff, *args)

def command(*aliases):
    return lambda func: Command(func, *aliases)

def run_command(bridge, buff, message: str):
    segments = message.split()
    command = segments[0].removeprefix('/')
    if commands.get(command):
        commands[command](bridge, buff, message)
    else:
        buff.restore()
        bridge.upstream.send_packet("chat_message", buff.pack_string(message))


# COMMANDS
@command("rq")
def requeue(bridge, buff: Buffer1_7):
    if bridge.game.get('mode') is None:
        bridge.downstream.send_packet(
            "chat_message",
            pack_chat("§9§l∎ §4No game to requeue!", 0)
        )
    else:
        bridge.upstream.send_packet(
            "chat_message",
            buff.pack_string(f"/play {bridge.game['mode']}")
        )

@command("sc", "cs")
def statcheck(bridge, buff: Buffer1_7, ign, gamemode=None):
    if gamemode is None:
        gamemode = bridge.game.get('mode')
    # TODO check for gamemode aliases
    
    client: Client = bridge.client
    try:
        player = client.player(ign)[0]
    except PlayerNotFound:
        bridge.downstream.send_packet(
            "chat_message",
            f"Player '{ign}' not found!"
        )
    else:
        bridge.downstream.send_packet(
            "chat_message",
            pack_chat(
                f"[{player.bedwars.level}] | {player.name} FKDR: {player.bedwars.fkdr} Wins: {player.bedwars.wins} Finals: {player.bedwars.final_kills} WLR: {player.bedwars.wins/player.bedwars.losses}"
            )
        )