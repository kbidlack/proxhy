import inspect
import types
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    Optional,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from protocol.datatypes import TextComponent
from proxhy.errors import ProxhyException


class CommandException(ProxhyException):
    """If a command has an error then stuff happens"""

    def __init__(self, message: str | TextComponent):
        self.message = message


class Lazy[T]:
    """
    A lazy wrapper for command arguments that defers conversion until awaited.

    Use ``Lazy[HypixelPlayer]`` as a type annotation on command parameters
    whose conversion is expensive (e.g. API calls) and may not always be needed.
    The conversion only runs when the command function ``await``\\s the parameter.

    Example::

        @command("sc")
        async def _command_sc(self, player: Lazy[HypixelPlayer] = None):
            if player is not None:
                player = await player   # API call happens here
    """

    def __init__(self, coro_factory: Callable[[], Awaitable[T]], value: str = ""):
        self._coro_factory = coro_factory
        self._resolved = False
        self._value: T | None = None
        self.value = value

    def __await__(self):
        return self._resolve().__await__()

    async def _resolve(self) -> T:
        if not self._resolved:
            self._value = await self._coro_factory()
            self._resolved = True
        return self._value  # type: ignore[return-value]


# =============================================================================
# Command Context
# =============================================================================


class LazyArgs:
    """
    Lazily converts command arguments on access.

    Arguments are only converted when accessed via indexing or iteration,
    avoiding unnecessary API calls during tab completion.
    """

    def __init__(
        self,
        ctx: CommandContext,
        raw_args: list[str],
        parameters: list[Parameter],
    ):
        self._ctx = ctx
        self._raw_args = raw_args
        self._parameters = parameters
        self._cache: dict[int, Any] = {}
        self._converted_count = min(len(raw_args), len(parameters))

    def __len__(self) -> int:
        return self._converted_count

    async def get(self, index: int) -> Any:
        """Get a converted argument by index, converting lazily if needed."""
        if index < 0 or index >= self._converted_count:
            raise IndexError(f"Argument index {index} out of range")

        if index in self._cache:
            return self._cache[index]

        param = self._parameters[index]
        if param.infinite:
            raise ValueError("Cannot lazily convert infinite parameters")

        old_param_index = self._ctx.param_index
        self._ctx.param_index = index
        try:
            converted = await param.convert(self._ctx, self._raw_args[index])
            self._cache[index] = converted
            return converted
        finally:
            self._ctx.param_index = old_param_index


@dataclass
class CommandContext:
    """
    Context passed to CommandArg.convert() and suggest() methods.

    Provides access to previously converted arguments and command metadata,
    enabling context-aware validation and suggestions.

    Attributes:
        proxy: The proxy instance (for accessing game state, APIs, etc.)
        args: LazyArgs instance for lazily converted arguments (use `await args.get(i)`)
        raw_args: List of raw string arguments (all arguments, including current)
        param_index: Index of the current parameter being converted/suggested
        command_name: Name of the command being executed
    """

    proxy: Any
    args: LazyArgs | list[Any] = field(default_factory=list)
    raw_args: list[str] = field(default_factory=list)
    param_index: int = 0
    command_name: str = ""

    async def get_arg[T](self, type_: type[T]) -> Optional[T]:
        """
        Get the first converted argument of the specified type.

        Useful for finding related arguments, e.g., getting SettingPath
        when validating SettingValue.

        Args:
            type_: The type to search for

        Returns:
            The first argument matching the type, or None if not found
        """
        if isinstance(self.args, LazyArgs):
            for i in range(len(self.args)):
                if self.args._parameters[i].type_hint == type_:
                    try:
                        arg = await self.args.get(i)
                        return arg
                    except (ValueError, CommandException):
                        pass
        else:
            for arg in self.args:
                if isinstance(arg, Lazy):
                    resolved = await arg
                    if isinstance(resolved, type_):
                        return resolved
                elif isinstance(arg, type_):
                    return arg
        return None


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
            async def convert(cls, ctx: CommandContext, value: str) -> "Player":
                # Fetch player data and return a Player instance
                # ctx.proxy gives access to the proxy instance
                # ctx.args gives access to previously converted arguments
                data = await fetch_player(value)
                return cls(data["name"], data["uuid"])

            @classmethod
            async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
                # Return tab completion suggestions
                # Can use ctx.args to provide context-aware suggestions
                return [p for p in ctx.proxy.players if p.lower().startswith(partial.lower())]
    """

    @classmethod
    @abstractmethod
    async def convert(cls, ctx: CommandContext, value: str) -> Any:
        """
        Convert a string argument to this type.

        Args:
            ctx: Command context with proxy, previously converted args, and metadata
            value: The raw string argument from the command

        Returns:
            An instance of this type

        Raises:
            CommandException: If the value cannot be converted
        """
        ...

    @classmethod
    async def suggest[S: str](cls, ctx: CommandContext, partial: str) -> list[S]:
        """
        Provide tab completion suggestions for this type.

        Args:
            ctx: Command context with proxy, previously converted args, and metadata
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

        # Check for Lazy[X] wrapper — unwrap to get the inner type
        # Also handles Optional[Lazy[X]] (i.e. Union[Lazy[X], None])
        self.is_lazy = get_origin(self.type_hint) is Lazy
        if not self.is_lazy and _is_union_type(self.type_hint):
            union_args = _get_union_args(self.type_hint)
            non_none_args = [a for a in union_args if a is not type(None)]
            if len(non_none_args) == 1 and get_origin(non_none_args[0]) is Lazy:
                self.is_lazy = True
                self.type_hint = non_none_args[0]
        if self.is_lazy:
            lazy_args = get_args(self.type_hint)
            self.type_hint = lazy_args[0] if lazy_args else self.type_hint

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
    async def convert_value(ctx: CommandContext, value: str, type_hint: Any) -> Any:
        """
        Convert a string value to the specified type.

        Supports:
        - CommandArg subclasses (async convert)
        - Basic types: int, float, str, bool
        - Returns the string as-is for unknown types
        """
        # Check if it's a CommandArg subclass
        if isinstance(type_hint, type) and issubclass(type_hint, CommandArg):
            return await type_hint.convert(ctx, value)

        if type_hint is int or type_hint is float:
            if not value.isdigit():
                raise CommandException(
                    f"Could not convert '{value}' to a{'n' if type_hint is int else ''} {type_hint.__name__}!"
                )

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

    async def convert(self, ctx: CommandContext, value: str) -> Any:
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
                    return await self.convert_value(ctx, value, member_type)
                except (ValueError, CommandException) as e:
                    errors.append((member_type, e))
                    continue

            # All types failed - raise an error with details
            # If there's only one non-None type and it raised a CommandException,
            # use that error directly (it's likely more user-friendly)
            non_none_errors = [(t, e) for t, e in errors if t is not type(None)]
            if len(non_none_errors) == 1 and isinstance(
                non_none_errors[0][1], CommandException
            ):
                raise non_none_errors[0][1]

            # Multiple types failed - show generic message
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
            return await self.type_hint.convert(ctx, value)

        else:
            return await self.convert_value(ctx, value, self.type_hint)

    async def get_suggestions(self, ctx: CommandContext, partial: str) -> list[str]:
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
                    member_suggestions = await member_type.suggest(ctx, partial)
                    suggestions.extend(member_suggestions)
            # Deduplicate while preserving order
            seen = set()
            suggestions = [s for s in suggestions if not (s in seen or seen.add(s))]
        elif self.is_custom_type:
            suggestions = await self.type_hint.suggest(ctx, partial)
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
        usage: list[str] | None = None,
    ) -> None:
        self.function = function
        self.name = name or function.__name__  # ty: ignore[unresolved-attribute]
        self.aliases = (self.name, *aliases)
        self.description = inspect.getdoc(function)
        self.usage = usage
        self.parent: CommandGroup | None = None

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

    @property
    def full_name(self) -> str:
        """Get the full command path (e.g., 'broadcast trust add')."""
        if self.parent:
            return f"{self.parent.full_name} {self.name}"
        return self.name

    def _build_usage_message(self) -> TextComponent:
        msg = TextComponent("Usage: ").color("yellow")

        if self.usage:
            msg.append(
                TextComponent(f"/{self.full_name} {self.usage[0]}").color("gold")
            )
            padding = " " * (len("Usage: ") + len(f"/{self.full_name} "))
            for overload in self.usage[1:]:
                msg.append("\n")
                msg.append(TextComponent(padding).color("yellow"))
                msg.append(TextComponent(f"/{self.full_name} {overload}").color("gold"))
        else:
            usage_parts = f"/{self.full_name}"
            for param in self.parameters:
                name = param.name.lstrip("_")
                if param.infinite:
                    usage_parts += f" [{name}...]"
                elif param.required:
                    usage_parts += f" <{name}>"
                else:
                    usage_parts += f" [{name}]"
            msg.append(TextComponent(usage_parts).color("gold"))

        if self.description:
            msg.append("\n")
            msg.append(
                # TextComponent("∟")
                TextComponent("→")
                .color("dark_gray")
                .appends(TextComponent(self.description).color("gray"))
            )

        return msg

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
            raise CommandException(self._build_usage_message())

        has_infinite = any(p.infinite for p in self.parameters)
        if len(args) > len(self.parameters) and not has_infinite:
            raise CommandException(self._build_usage_message())

        if len(args) < len(self.required_parameters):
            raise CommandException(self._build_usage_message())

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

        # Build context and convert arguments to their proper types
        converted_args: list[Any] = []
        ctx = CommandContext(
            proxy=proxy,
            args=converted_args,
            raw_args=args,
            param_index=0,
            command_name=self.name,
        )

        for i, param in enumerate(self.parameters):
            ctx.param_index = i
            if param.infinite:
                # Handle *args - convert remaining arguments
                remaining = args[i:]
                for j, arg in enumerate(remaining):
                    ctx.param_index = i + j
                    if param.is_lazy:
                        idx = i + j
                        lazy = Lazy(
                            lambda p=param, a=arg, ix=idx: self._lazy_convert(
                                ctx, p, a, ix
                            ),
                            value=arg,
                        )
                        converted_args.append(lazy)
                    else:
                        converted = await param.convert(ctx, arg)
                        converted_args.append(converted)
                break
            elif i < len(args):
                if param.is_lazy:
                    lazy = Lazy(
                        lambda p=param, a=args[i], ix=i: self._lazy_convert(
                            ctx, p, a, ix
                        ),
                        value=args[i],
                    )
                    converted_args.append(lazy)
                else:
                    converted = await param.convert(ctx, args[i])
                    converted_args.append(converted)

        return await self.function(proxy, *converted_args)

    @staticmethod
    async def _lazy_convert(
        ctx: CommandContext, param: Parameter, arg: str, index: int
    ) -> Any:
        """Convert a parameter with the correct param_index set on ctx."""
        old_param_index = ctx.param_index
        ctx.param_index = index
        try:
            return await param.convert(ctx, arg)
        finally:
            ctx.param_index = old_param_index

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

        # Build context with lazily converted arguments for suggestions
        ctx = CommandContext(
            proxy=proxy,
            raw_args=args + [partial],
            param_index=arg_index,
            command_name=self.name,
        )
        # Set up lazy args - conversions happen only when accessed
        ctx.args = LazyArgs(ctx, args, self.parameters)

        # Delegate to Parameter.get_suggestions
        return await param.get_suggestions(ctx, partial)


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

    def __init__(
        self,
        name: str,
        *aliases: str,
        help: str | None = None,
        parent: CommandGroup | None = None,
    ):
        self.name = name
        self.aliases = (name, *aliases)
        self.help = help
        self.parent = parent

        self._base_command: Command | None = None
        self._subcommands: dict[str, Command] = {}
        self._subgroups: dict[str, CommandGroup] = {}

    @property
    def description(self) -> str | None:
        return self.help or (
            self._base_command.description if self._base_command else None
        )

    @property
    def full_name(self) -> str:
        """Get the full command path (e.g., 'broadcast setting')."""
        if self.parent:
            return f"{self.parent.full_name} {self.name}"
        return self.name

    def iter_subcommands(
        self, *, recursive: bool = False
    ) -> list[tuple[str, Command | CommandGroup]]:
        """
        Iterate over unique subcommands and subgroups (no alias duplicates).

        Args:
            recursive: If True, also include children of nested subgroups.

        Returns a list of (full_name, cmd_or_group) tuples.
        """
        seen: set[int] = set()
        result: list[tuple[str, Command | CommandGroup]] = []

        for cmd in self._subcommands.values():
            if id(cmd) in seen:
                continue
            seen.add(id(cmd))
            result.append((f"{self.full_name} {cmd.name}", cmd))

        for grp in self._subgroups.values():
            if id(grp) in seen:
                continue
            seen.add(id(grp))
            result.append((f"{grp.full_name}", grp))
            if recursive:
                result.extend(grp.iter_subcommands(recursive=True))

        return result

    def command(
        self, name: str | None = None, *aliases: str, usage: list[str] | None = None
    ):
        """
        Decorator to register a command in this group.

        Args:
            name: Subcommand name. If None, this becomes the base command
                  (executed when no subcommand is given).
            *aliases: Additional aliases for this subcommand.
            usage: Optional list of usage overloads.

        Example:
            @group.command()  # Base command
            async def _base(self): ...

            @group.command("list", "ls")  # Subcommand with alias
            async def _list(self): ...
        """

        def decorator(func: Callable[..., Awaitable[Any]]):
            cmd = Command(func, name=name or self.name, aliases=aliases, usage=usage)
            cmd.parent = self

            if name is None:
                self._base_command = cmd
            else:
                # Register under primary name and all aliases
                self._subcommands[name.lower()] = cmd
                for alias in aliases:
                    self._subcommands[alias.lower()] = cmd

            return func

        return decorator

    def group(self, name: str, *aliases: str, help: str | None = None) -> CommandGroup:
        """
        Create a nested subgroup.

        Args:
            name: The subgroup name
            *aliases: Additional aliases for this subgroup
            help: Optional help text for this subgroup

        Returns:
            The new CommandGroup instance
        """
        subgroup = CommandGroup(name, *aliases, help=help, parent=self)

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

        if self.description:
            msg.append("\n")
            msg.append(TextComponent(self.description).color("gray"))

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


def command(name: str, *aliases: str, usage: list[str] | None = None):
    """
    Decorator to create a simple command (no subcommands).

    The command name is required as the first argument.
    This enforces the `_command_<name>` naming convention for functions.

    Args:
        name: The command name (required).
        *aliases: Additional command aliases.
        usage: Optional list of usage overloads (e.g. ["<player>", "<x> <y> <z>"]).

    Example:
        @command("bc", "broadcast")
        async def _command_bc(self, message: str):
            return f"Broadcasting: {message}"

        @command("tp", "teleport", usage=["<player>", "<x> <y> <z>"])
        async def _command_tp(self, target: Player | float, y: float = None, z: float = None):
            \"\"\"Teleport to a player or coordinate set.\"\"\"
            ...
    """

    def decorator(func: Callable[..., Awaitable[Any]]):
        cmd = Command(func, name=name, aliases=aliases, usage=usage)
        # Store as attribute for discovery by CommandsPlugin
        setattr(func, "_command", cmd)
        return func

    return decorator
