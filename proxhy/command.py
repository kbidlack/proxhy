import inspect
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    get_args,
    get_origin,
)

from protocol.datatypes import TextComponent
from proxhy.errors import CommandException


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

    def __repr__(self):
        return "Parameter: " + ", ".join([f"{k}={v}" for k, v in self.__dict__.items()])


class Command:
    def __init__(self, function, *aliases) -> None:
        self.function = function
        self.name = function.__name__

        sig = inspect.signature(function)
        self.parameters = [
            Parameter(sig.parameters[param]) for param in sig.parameters
        ][1:]
        self.required_parameters = [
            param for param in self.parameters if param.required
        ]
        self.restricted_parameters = [
            (i, param) for i, param in enumerate(self.parameters) if param.options
        ]

        self.aliases = aliases

    async def __call__(self, proxy, message: str):
        segments = message.split()
        args = segments[1:]
        if not self.parameters and args:
            raise CommandException(
                TextComponent("Command")
                .appends(TextComponent(f"{segments[0]}").color("gold"))
                .appends("takes no arguments!")
            )
        elif (len(args) > len(self.parameters)) and not any(
            p.infinite for p in self.parameters
        ):
            raise CommandException(
                TextComponent("Command")
                .appends(TextComponent(segments[0]).color("gold"))
                .appends("takes at most")
                .appends(TextComponent(f"{len(self.parameters)}").color("dark_aqua"))
                .appends("argument(s)!")
            )
        elif len(args) < len(self.required_parameters):
            names = ", ".join([param.name for param in self.required_parameters])
            raise CommandException(
                TextComponent("Command")
                .appends(TextComponent(segments[0]).color("gold"))
                .appends("needs at least")
                .appends(
                    TextComponent(f"{len(self.required_parameters)}").color("dark_aqua")
                )
                .appends("argument(s)! (")
                .append(TextComponent(f"{names}").color("dark_aqua"))
                .append(")")
            )
        else:
            for index, param in self.restricted_parameters:
                if param.options and args[index].lower() not in param.options:
                    raise CommandException(
                        TextComponent("Invalid option '")
                        .append(TextComponent(f"{args[index]}").color("gold"))
                        .append("'. Please choose a correct argument! (")
                        .append(
                            TextComponent(f"{', '.join(param.options)}").color(
                                "dark_aqua"
                            )
                        )
                        .append(")")
                    )

            return await self.function(proxy, *args)


def command[**P](*aliases):
    def wrapper(func: Callable[P, Awaitable[Any]]):
        setattr(func, "_command", Command(func, *(func.__name__, *aliases)))
        return func

    return wrapper
