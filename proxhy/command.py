import inspect
from collections.abc import Awaitable, Callable
from typing import Literal, get_args, get_origin

from errors import CommandException

commands: dict[str, Callable[..., str], Awaitable[str | None]] = {}


class Parameter:
    def __init__(self, param: inspect.Parameter):
        self.name = param.name

        if param.default is not inspect._empty:
            self.default = param.default
            self.required = False
        else:
            self.required = True

        if param.kind is inspect.Parameter.VAR_POSITIONAL:  # *args
            self.infinite = True
            self.required = False
        else:
            self.infinite = False

        if get_origin(param.annotation) is Literal:
            self.options = get_args(param.annotation)
        else:
            self.options = None


class Command:
    def __init__(self, function, *aliases) -> None:
        self.function = function
        self.name = function.__name__

        sig = inspect.signature(function)
        # first two parameters should be bridge and buff
        self.parameters = [
            Parameter(sig.parameters[param]) for param in sig.parameters
        ][2:]
        self.required_parameters = [
            param for param in self.parameters if param.required
        ]
        self.restricted_parameters = [
            (i, param) for i, param in enumerate(self.parameters) if param.options
        ]

        self.aliases = aliases
        commands.update({self.name: self})
        for alias in self.aliases:
            commands.update({alias: self})

    # decorator
    async def __call__(self, proxy, message: str):
        segments = message.split()
        args = segments[1:]
        if not self.parameters and args:
            raise CommandException(
                f"§9§l∎ §4Command <{segments[0]}> takes no arguments!"
            )
        elif (len(args) > len(self.parameters)) and not any(
            p.infinite for p in self.parameters
        ):
            raise CommandException(
                f"§9§l∎ §4Command <{segments[0]}> takes at most "
                f"{len(self.parameters)} argument(s)!"
            )
        elif len(args) < len(self.required_parameters):
            names = ", ".join([param.name for param in self.required_parameters])
            raise CommandException(
                f"§9§l∎ §4Command <{segments[0]}> needs at least "
                f"{len(self.required_parameters)} argument(s)! ({names})"
            )
        else:
            for index, param in self.restricted_parameters:
                if param.options and args[index].lower() not in param.options:
                    raise CommandException(
                        f"§9§l∎ §4Invalid option '{args[index]}'. "
                        f"Please choose a correct argument! ({', '.join(param.options)})"
                    )

            return await self.function(proxy, *args)


def command(*aliases):
    return lambda func: Command(func, *aliases)
