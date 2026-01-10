from __future__ import annotations

import inspect
import types
from abc import ABC, abstractmethod
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from protocol.datatypes import TextComponent
from proxhy.errors import CommandException


def _is_union_type(type_hint: Any) -> bool:
    """Check if a type hint is a Union type (including X | Y syntax)."""
    origin = get_origin(type_hint)
    return origin is Union or origin is types.UnionType


def _get_union_args(type_hint: Any) -> tuple[Any, ...]:
    """Get the member types of a Union."""
    return get_args(type_hint)


# =============================================================================
# Custom Argument Types
# =============================================================================


class CommandArg(ABC):
    """
    Base class for custom command argument types.

    Subclass this to create custom types that can be used in command signatures.
    The type will automatically convert string arguments and provide tab suggestions.

    Example:
        class Player(CommandArg):
            def __init__(self, name: str, uuid: str):
                self.name = name
                self.uuid = uuid

            @classmethod
            async def convert(cls, proxy, value: str) -> "Player":
                # Fetch player data and return a Player instance
                data = await fetch_player(value)
                return cls(data["name"], data["uuid"])

            @classmethod
            async def suggest(cls, proxy, partial: str) -> list[str]:
                # Return tab completion suggestions
                return [p for p in proxy.players if p.lower().startswith(partial.lower())]
    """

    @classmethod
    @abstractmethod
    async def convert(cls, proxy: Any, value: str) -> Any:
        """
        Convert a string argument to this type.

        Args:
            proxy: The proxy instance (for accessing game state, APIs, etc.)
            value: The raw string argument from the command

        Returns:
            An instance of this type

        Raises:
            CommandException: If the value cannot be converted
        """
        ...

    @classmethod
    async def suggest(cls, proxy: Any, partial: str) -> list[str]:
        """
        Provide tab completion suggestions for this type.

        Args:
            proxy: The proxy instance
            partial: The partially typed argument

        Returns:
            List of suggestion strings
        """
        return []


# =============================================================================
# Parameter Handling
# =============================================================================


class Parameter:
    """Represents a command parameter with its metadata."""

    def __init__(self, param: inspect.Parameter, type_hint: Any = None):
        self.name = param.name
        self.type_hint = type_hint or param.annotation

        # Check if required (no default value)
        if param.default is not inspect._empty:
            self.default = param.default
            self.required = False
        else:
            self.default = None
            self.required = True

        # Check for *args (infinite arguments)
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            self.infinite = True
            self.required = False
        else:
            self.infinite = False

        # Check for Literal type (restricted options)
        if get_origin(self.type_hint) is Literal:
            self.options = get_args(self.type_hint)
        else:
            self.options = None

        # Check for Union type (e.g., ServerPlayer | float)
        if _is_union_type(self.type_hint):
            self.is_union = True
            self.union_types = _get_union_args(self.type_hint)
        else:
            self.is_union = False
            self.union_types = None

        # Check if this is a custom CommandArg type
        self.is_custom_type = isinstance(self.type_hint, type) and issubclass(
            self.type_hint, CommandArg
        )

    def __repr__(self):
        return "Parameter: " + ", ".join([f"{k}={v}" for k, v in self.__dict__.items()])

    @staticmethod
    async def convert_value(proxy: Any, value: str, type_hint: Any) -> Any:
        """
        Convert a string value to the specified type.

        Supports:
        - CommandArg subclasses (async convert)
        - Basic types: int, float, str, bool
        - Returns the string as-is for unknown types
        """
        # Check if it's a CommandArg subclass
        if isinstance(type_hint, type) and issubclass(type_hint, CommandArg):
            return await type_hint.convert(proxy, value)

        # Handle basic types
        if type_hint is int:
            return int(value)
        elif type_hint is float:
            return float(value)
        elif type_hint is bool:
            lower = value.lower()
            if lower in ("true", "yes", "1", "on"):
                return True
            elif lower in ("false", "no", "0", "off"):
                return False
            raise ValueError(f"Cannot convert '{value}' to bool")
        elif type_hint is str:
            return value

        # Unknown type, return as string
        return value

    async def convert(self, proxy: Any, value: str) -> Any:
        """
        Convert a string value to this parameter's type.

        For union types, tries each type in order until one succeeds.
        """
        if self.is_union and self.union_types:
            # Try each type in the union in order
            errors = []
            for member_type in self.union_types:
                # Skip NoneType in unions (for Optional types)
                if member_type is type(None):
                    continue
                try:
                    return await self.convert_value(proxy, value, member_type)
                except (ValueError, CommandException) as e:
                    errors.append((member_type, e))
                    continue

            # All types failed - raise an error with details
            type_names = [
                t.__name__ if hasattr(t, "__name__") else str(t)
                for t in self.union_types
                if t is not type(None)
            ]
            raise CommandException(
                TextComponent("Could not parse '")
                .append(TextComponent(value).color("gold"))
                .append("' as any of: ")
                .append(TextComponent(", ".join(type_names)).color("dark_aqua"))
            )

        elif self.is_custom_type:
            return await self.type_hint.convert(proxy, value)

        else:
            return await self.convert_value(proxy, value, self.type_hint)

    async def get_suggestions(self, proxy: Any, partial: str) -> list[str]:
        """Get tab completion suggestions for this parameter."""
        suggestions: list[str] = []

        if self.options:
            # Literal type - suggest from options
            suggestions = [
                str(o)
                for o in self.options
                if str(o).lower().startswith(partial.lower())
            ]
        elif self.is_union and self.union_types:
            # Union type - collect suggestions from all CommandArg members
            for member_type in self.union_types:
                if isinstance(member_type, type) and issubclass(
                    member_type, CommandArg
                ):
                    member_suggestions = await member_type.suggest(proxy, partial)
                    suggestions.extend(member_suggestions)
            # Deduplicate while preserving order
            seen = set()
            suggestions = [
                s
                for s in suggestions
                if not (s in seen or seen.add(s))  # type: ignore
            ]
        elif self.is_custom_type:
            suggestions = await self.type_hint.suggest(proxy, partial)

        return suggestions


# =============================================================================
# Command Class
# =============================================================================


class Command:
    """
    Represents a single command (or subcommand).

    Handles argument parsing, validation, type conversion, and execution.
    """

    def __init__(
        self,
        function: Callable[..., Awaitable[Any]],
        name: str | None = None,
        aliases: tuple[str, ...] = (),
    ) -> None:
        self.function = function
        self.name = name or function.__name__
        self.aliases = (self.name, *aliases)

        # Get type hints for proper annotation resolution
        try:
            hints = get_type_hints(function)
        except Exception:
            hints = {}

        # Parse parameters (skip 'self')
        sig = inspect.signature(function)
        params = list(sig.parameters.values())[1:]  # Skip self
        self.parameters = [Parameter(p, hints.get(p.name)) for p in params]
        self.required_parameters = [p for p in self.parameters if p.required]
        self.restricted_parameters = [
            (i, p) for i, p in enumerate(self.parameters) if p.options
        ]

    async def __call__(self, proxy: Any, args: list[str]) -> Any:
        """
        Execute the command with the given arguments.

        Args:
            proxy: The proxy instance
            args: List of string arguments (command name already stripped)

        Returns:
            The command's return value (usually str or TextComponent)
        """
        # Validate argument count
        if not self.parameters and args:
            raise CommandException(
                TextComponent("Command ")
                .append(TextComponent(self.name).color("gold"))
                .appends("takes no arguments!")
            )

        has_infinite = any(p.infinite for p in self.parameters)
        if len(args) > len(self.parameters) and not has_infinite:
            raise CommandException(
                TextComponent("Command ")
                .append(TextComponent(self.name).color("gold"))
                .appends("takes at most")
                .appends(TextComponent(str(len(self.parameters))).color("dark_aqua"))
                .appends("argument(s)!")
            )

        if len(args) < len(self.required_parameters):
            names = ", ".join([p.name for p in self.required_parameters])
            raise CommandException(
                TextComponent("Command ")
                .append(TextComponent(self.name).color("gold"))
                .appends("needs at least")
                .appends(
                    TextComponent(str(len(self.required_parameters))).color("dark_aqua")
                )
                .appends("argument(s)! (")
                .append(TextComponent(names).color("dark_aqua"))
                .append(")")
            )

        # Validate restricted parameters (Literal types)
        for index, param in self.restricted_parameters:
            if index < len(args) and param.options:
                if args[index].lower() not in [str(o).lower() for o in param.options]:
                    raise CommandException(
                        TextComponent("Invalid option '")
                        .append(TextComponent(args[index]).color("gold"))
                        .append("'. Please choose a correct argument! (")
                        .append(
                            TextComponent(
                                ", ".join(str(o) for o in param.options)
                            ).color("dark_aqua")
                        )
                        .append(")")
                    )

        # Convert arguments to their proper types
        converted_args = []
        for i, param in enumerate(self.parameters):
            if param.infinite:
                # Handle *args - convert remaining arguments
                remaining = args[i:]
                converted = [await param.convert(proxy, arg) for arg in remaining]
                converted_args.extend(converted)
                break
            elif i < len(args):
                # Convert single argument using Parameter.convert
                converted = await param.convert(proxy, args[i])
                converted_args.append(converted)

        return await self.function(proxy, *converted_args)

    async def get_suggestions(
        self, proxy: Any, args: list[str], partial: str
    ) -> list[str]:
        """
        Get tab completion suggestions for the current argument position.

        Args:
            proxy: The proxy instance
            args: Arguments typed so far (complete ones)
            partial: The partially typed current argument

        Returns:
            List of suggestion strings
        """
        arg_index = len(args)

        if arg_index >= len(self.parameters):
            # Check if last param is infinite
            if self.parameters and self.parameters[-1].infinite:
                param = self.parameters[-1]
            else:
                return []
        else:
            param = self.parameters[arg_index]

        # Delegate to Parameter.get_suggestions
        return await param.get_suggestions(proxy, partial)


# =============================================================================
# Command Group
# =============================================================================


class CommandGroup:
    """
    A group of related commands with a shared prefix.

    Supports nested subgroups and a base command for when no subcommand is given.

    Example:
        broadcast = CommandGroup("broadcast", "bc")

        @broadcast.command()
        async def _base(self):
            return "Usage: /broadcast <list|join|leave>"

        @broadcast.command("list")
        async def _list(self):
            return "Players: ..."

        setting = broadcast.group("setting", "set")

        @setting.command("add")
        async def _add(self, name: str, value: str):
            return f"Added {name}={value}"
    """

    def __init__(self, name: str, *aliases: str, parent: CommandGroup | None = None):
        self.name = name
        self.aliases = (name, *aliases)
        self.parent = parent

        self._base_command: Command | None = None
        self._subcommands: dict[str, Command] = {}
        self._subgroups: dict[str, CommandGroup] = {}

    @property
    def full_name(self) -> str:
        """Get the full command path (e.g., 'broadcast setting')."""
        if self.parent:
            return f"{self.parent.full_name} {self.name}"
        return self.name

    def command(self, name: str | None = None, *aliases: str):
        """
        Decorator to register a command in this group.

        Args:
            name: Subcommand name. If None, this becomes the base command
                  (executed when no subcommand is given).
            *aliases: Additional aliases for this subcommand.

        Example:
            @group.command()  # Base command
            async def _base(self): ...

            @group.command("list", "ls")  # Subcommand with alias
            async def _list(self): ...
        """

        def decorator(func: Callable[..., Awaitable[Any]]):
            cmd = Command(func, name=name or self.name, aliases=aliases)

            if name is None:
                self._base_command = cmd
            else:
                # Register under primary name and all aliases
                self._subcommands[name.lower()] = cmd
                for alias in aliases:
                    self._subcommands[alias.lower()] = cmd

            return func

        return decorator

    def group(self, name: str, *aliases: str) -> CommandGroup:
        """
        Create a nested subgroup.

        Args:
            name: The subgroup name
            *aliases: Additional aliases for this subgroup

        Returns:
            The new CommandGroup instance
        """
        subgroup = CommandGroup(name, *aliases, parent=self)

        # Register under primary name and all aliases
        self._subgroups[name.lower()] = subgroup
        for alias in aliases:
            self._subgroups[alias.lower()] = subgroup

        return subgroup

    def _build_usage_message(self) -> TextComponent:
        """Build a usage message showing available subcommands."""
        msg = TextComponent("Usage: ").color("yellow")
        msg.append(TextComponent(f"/{self.full_name} ").color("gold"))
        msg.append(TextComponent("<").color("gray"))

        # Collect unique subcommand names (not aliases)
        subcommand_names = set()
        for cmd in self._subcommands.values():
            subcommand_names.add(cmd.name)
        for grp in self._subgroups.values():
            subcommand_names.add(grp.name)

        options = sorted(subcommand_names)
        msg.append(TextComponent("|".join(options)).color("white"))
        msg.append(TextComponent(">").color("gray"))

        return msg

    async def __call__(self, proxy: Any, args: list[str]) -> Any:
        """
        Execute this command group with the given arguments.

        Routes to the appropriate subcommand or base command.
        """
        if not args:
            # No subcommand given
            if self._base_command:
                return await self._base_command(proxy, [])
            else:
                return self._build_usage_message()

        subcommand_name = args[0].lower()
        remaining_args = args[1:]

        # Check for subgroup first
        if subcommand_name in self._subgroups:
            return await self._subgroups[subcommand_name](proxy, remaining_args)

        # Check for subcommand
        if subcommand_name in self._subcommands:
            return await self._subcommands[subcommand_name](proxy, remaining_args)

        # Unknown subcommand
        raise CommandException(
            TextComponent("Unknown subcommand '")
            .append(TextComponent(args[0]).color("gold"))
            .append("'. ")
            .append(self._build_usage_message())
        )

    async def get_suggestions(
        self, proxy: Any, args: list[str], partial: str
    ) -> list[str]:
        """Get tab completion suggestions."""
        if not args:
            # Suggest subcommands and subgroups
            all_options = list(self._subcommands.keys()) + list(self._subgroups.keys())
            # Filter to unique names (not aliases) that match partial
            seen = set()
            suggestions = []
            for opt in all_options:
                if opt.lower().startswith(partial.lower()) and opt not in seen:
                    seen.add(opt)
                    suggestions.append(opt)
            return suggestions

        subcommand_name = args[0].lower()
        remaining_args = args[1:]

        # Delegate to subgroup
        if subcommand_name in self._subgroups:
            return await self._subgroups[subcommand_name].get_suggestions(
                proxy, remaining_args, partial
            )

        # Delegate to subcommand
        if subcommand_name in self._subcommands:
            return await self._subcommands[subcommand_name].get_suggestions(
                proxy, remaining_args, partial
            )

        return []


# =============================================================================
# Command Registry (per-instance)
# =============================================================================


class CommandRegistry:
    """
    Per-instance command registry.

    Each proxy instance has its own registry, allowing different proxies
    to have different command sets or configurations.
    """

    def __init__(self):
        self._commands: dict[str, Command | CommandGroup] = {}

    def register(self, cmd: Command | CommandGroup) -> None:
        """Register a command or command group."""
        for alias in cmd.aliases:
            self._commands[alias.lower()] = cmd

    def get(self, name: str) -> Command | CommandGroup | None:
        """Get a command by name or alias."""
        return self._commands.get(name.lower())

    def all_commands(self) -> dict[str, Command | CommandGroup]:
        """Get all registered commands."""
        return self._commands.copy()

    def command_names(self) -> list[str]:
        """Get all unique command names (not aliases)."""
        seen = set()
        names = []
        for cmd in self._commands.values():
            if cmd.name not in seen:
                seen.add(cmd.name)
                names.append(cmd.name)
        return names


# =============================================================================
# Decorator for Simple Commands
# =============================================================================


def command(name: str, *aliases: str):
    """
    Decorator to create a simple command (no subcommands).

    The command name is required as the first argument.
    This enforces the `_command_<name>` naming convention for functions.

    Args:
        name: The command name (required).
        *aliases: Additional command aliases.

    Example:
        @command("bc", "broadcast")
        async def _command_bc(self, message: str):
            return f"Broadcasting: {message}"

        @command("ping")
        async def _command_ping(self):
            return "Pong!"
    """

    def decorator(func: Callable[..., Awaitable[Any]]):
        cmd = Command(func, name=name, aliases=aliases)
        # Store as attribute for discovery by CommandsPlugin
        setattr(func, "_command", cmd)
        return func

    return decorator
