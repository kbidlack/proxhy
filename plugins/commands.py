import asyncio
import re
from typing import Any, Callable, Coroutine, Union

from core.command import (
    Command,
    CommandArg,
    CommandContext,
    CommandException,
    CommandGroup,
    CommandRegistry,
    command,
)
from core.events import listen_client, listen_server, subscribe
from protocol.datatypes import Boolean, Buffer, String, TextComponent, VarInt
from proxhy.plugin import ProxhyPlugin

_OTHER_COMMANDS: set[str] = {
    "compass",
    "samsung_ringtone",
    "iphone_ringtone",
    "teams",
    "player_list",
    "garlicbread",
    "fribidiskigma",
    # for when spectating a broadcast
    # since these are just blocked (do nothing)
    "locraw",
    "tip",
}


class HelpPath(CommandArg):
    """Suggests command names and subcommand paths."""

    def __init__(self, value: str):
        self.value = value

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> HelpPath:
        return cls(value)

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        registry: CommandRegistry = ctx.proxy.command_registry
        prior = ctx.raw_args[: ctx.param_index]

        if not prior:
            return [
                name
                for name in registry.command_names()
                if name.startswith(partial.lower())
            ]

        root = registry.get(prior[0].lower())
        if not isinstance(root, CommandGroup):
            return []

        group = root
        for segment in prior[1:]:
            lower = segment.lower()
            if lower in group._subgroups:
                group = group._subgroups[lower]
            else:
                return []

        options: list[str] = []
        seen: set[int] = set()
        for cmd in group._subcommands.values():
            if id(cmd) not in seen:
                seen.add(id(cmd))
                if cmd.name.startswith(partial.lower()):
                    options.append(cmd.name)
        for grp in group._subgroups.values():
            if id(grp) not in seen:
                seen.add(id(grp))
                if grp.name.startswith(partial.lower()):
                    options.append(grp.name)
        return options


class CommandsPluginState:
    command_registry: CommandRegistry
    suggestions: asyncio.Queue[list[str]]
    run_proxhy_command: Callable[[str], Coroutine[Any, Any, None]]


class CommandsPlugin(ProxhyPlugin):
    """
    Plugin that handles command registration, execution, and tab completion.

    Commands are registered per-instance, allowing different proxy instances
    to have different command configurations.
    """

    def _init_0_commands(self):  # 0 so it runs first (alphabetically)
        self.command_registry = CommandRegistry()
        self.suggestions: asyncio.Queue[list[str]] = asyncio.Queue()

        # Discover and register @command decorated methods
        for item in dir(self):
            try:
                obj = getattr(self, item)
                if hasattr(obj, "_command"):
                    command: Command = getattr(obj, "_command")
                    self.command_registry.register(command)
            except AttributeError:
                pass

    @command("help")
    async def _command_help(self, *path: HelpPath):
        """Show available commands or get help for a specific command."""
        if path:
            if path[0].value.lower() == "other":
                return self._build_help_listing(other=True)

            root_name = path[0].value.lower()
            cmd: Command | CommandGroup | None = self.command_registry.get(root_name)
            if cmd is None:
                raise CommandException(
                    TextComponent("Unknown command '")
                    .append(TextComponent(path[0].value).color("gold"))
                    .append("'!")
                )

            for part in path[1:]:
                if not isinstance(cmd, CommandGroup):
                    raise CommandException(
                        TextComponent("'")
                        .append(TextComponent(cmd.name).color("gold"))
                        .append("' has no subcommands!")
                    )
                lower = part.value.lower()
                if lower in cmd._subgroups:
                    cmd = cmd._subgroups[lower]
                elif lower in cmd._subcommands:
                    cmd = cmd._subcommands[lower]
                else:
                    raise CommandException(
                        TextComponent("Unknown subcommand '")
                        .append(TextComponent(part.value).color("gold"))
                        .append("'!")
                    )

            if isinstance(cmd, CommandGroup):
                return self._build_help_listing(cmd)
            return cmd._build_usage_message()

        return self._build_help_listing()

    def _build_help_listing(
        self, group: CommandGroup | None = None, *, other: bool = False
    ) -> TextComponent:
        seen: set[int] = set()
        # (name, description, aliases, help_path, is_group)
        entries: list[tuple[str, str, list[str], str, bool]] = []

        if group is None:
            for name, cmd in self.command_registry.all_commands().items():
                if id(cmd) in seen:
                    continue
                seen.add(id(cmd))
                is_other = cmd.name in _OTHER_COMMANDS
                if is_other != other:
                    continue
                aliases = [a for a in cmd.aliases if a != cmd.name]
                description = cmd.description or ""
                is_group = isinstance(cmd, CommandGroup)
                entries.append((cmd.name, description, aliases, cmd.name, is_group))
        else:
            for sub_name, sub_cmd in group.iter_subcommands():
                if id(sub_cmd) in seen:
                    continue
                seen.add(id(sub_cmd))
                description = sub_cmd.description or ""
                is_group = isinstance(sub_cmd, CommandGroup)
                entries.append((sub_name, description, [], sub_name, is_group))

        entries.sort(key=lambda c: c[0])

        if group is not None:
            msg = TextComponent(f"/{group.full_name}").color("gold").bold()
            if group.description:
                msg.append(
                    TextComponent(f" - {group.description}").color("gray").bold(False)
                )
        elif other:
            msg = TextComponent("Other Commands").color("gold").bold()
            msg.append(TextComponent(f" ({len(entries)})").color("gray").bold(False))
        else:
            msg = TextComponent("Available Commands").color("gold").bold()
            msg.append(TextComponent(f" ({len(entries)})").color("gray").bold(False))

        msg.append(
            TextComponent("\nHover for info.").color("gray").bold(False).italic()
        )

        for name, description, aliases, help_path, is_group in entries:
            line = TextComponent("\n  •").color("white")
            line.appends(TextComponent(f"/{name}").color("yellow"))

            if is_group:
                line.append(TextComponent(" [+]").color("dark_aqua"))

            if aliases:
                line.append(
                    TextComponent(
                        f" ({', '.join(map(lambda s: f'/{s}', aliases))})"
                    ).color("dark_gray")
                )

            if description or is_group:
                hover = TextComponent(description).color("gray").italic(False)
                if is_group:
                    prefix = "\n" if description else ""
                    hover.append(
                        TextComponent(f"{prefix}[+]").color("dark_aqua").italic(False)
                    )
                    hover.appends(
                        TextComponent("- Contains multiple commands")
                        .color("gray")
                        .italic()
                    )
                line.hover_text(hover)

            line.click_event("suggest_command", f"/help {help_path}")
            line.bold(False)

            msg.append(line)

        if group is None and not other:
            footer = (
                TextComponent("\n\n")
                .bold(False)
                .append(
                    TextComponent(
                        "Click to view technical, internal, and easter egg commands\n"
                    )
                    .color("gray")
                    .italic()
                    .click_event("run_command", "/help other")
                )
            )
            msg.append(footer)

        return msg

    def register_command(self, cmd: Command) -> None:
        """
        Register a command with this proxy instance.

        Args:
            cmd: The Command instance to register
        """
        self.command_registry.register(cmd)

    def register_command_group(self, group: CommandGroup) -> None:
        """
        Register a command group with this proxy instance.

        Args:
            group: The CommandGroup instance to register
        """
        self.command_registry.register(group)

    @subscribe("chat:client:/.*")
    async def _commands_event_chat_client_command(self, _match, buff: Buffer):
        await self._run_command(buff.unpack(String))

    async def _run_command(self, message: str):
        segments = message.split()
        cmd_name = segments[0].removeprefix("/").removeprefix("/").casefold()

        command: Union[Command, CommandGroup, None] = self.command_registry.get(
            cmd_name
        )

        if command:
            try:
                args = segments[1:]
                output: str | TextComponent = await command(self, args)
            except CommandException as err:
                if isinstance(err.message, TextComponent):
                    err.message.flatten()

                    for i, child in enumerate(err.message.get_children()):
                        if not child.data.get("color"):
                            err.message.replace_child(i, child.color("dark_red"))
                        if not child.data.get("bold"):
                            err.message.replace_child(i, child.bold(False))

                err.message = TextComponent(err.message)
                if not err.message.data.get("color"):
                    err.message.color("dark_red")

                err.message = err.message.bold(False)

                error_msg = TextComponent("∎ ").bold().color("blue").append(err.message)
                if error_msg.data.get("clickEvent") is None:
                    error_msg = error_msg.click_event("suggest_command", message)

                self.client.chat(error_msg)
            else:
                if output:
                    if segments[0].startswith("//"):  # send output of command
                        # remove chat formatting
                        output = re.sub(r"§.", "", str(output))
                        self.server.chat(output)
                    else:
                        if isinstance(output, TextComponent):
                            if output.data.get("clickEvent") is None:
                                output = output.click_event("suggest_command", message)

                        self.client.chat(output)
        else:
            self.server.send_packet(0x01, String.pack(message))

    @listen_client(0x14)
    async def packet_tab_complete(self, buff: Buffer):
        await self._tab_complete(buff.unpack(String))

    async def _tab_complete(self, text: str):
        precommand = None
        forward = True
        suggestions: list[str] = []

        # generate autocomplete suggestions
        if text.startswith("//"):
            precommand = text.split()[0].removeprefix("//").casefold()
            prefix = "//"
        elif text.startswith("/"):
            precommand = text.split()[0].removeprefix("/").casefold()
            prefix = "/"
        else:
            prefix = ""

        if precommand is not None:
            parts = text.split()

            if " " in text:
                # User has typed at least the command name and started typing args
                command = self.command_registry.get(precommand)

                if command:
                    forward = False
                    # Determine what's been typed
                    # text = "/cmd arg1 arg2 part" -> args = ["arg1", "arg2"], partial = "part"
                    # text = "/cmd arg1 arg2 " -> args = ["arg1", "arg2"], partial = ""
                    if text.endswith(" "):
                        args = parts[1:]
                        partial = ""
                    else:
                        args = parts[1:-1]
                        partial = parts[-1] if len(parts) > 1 else ""

                    try:
                        suggestions = await command.get_suggestions(self, args, partial)
                    except Exception:
                        suggestions = []
            else:
                # Still typing command name
                all_commands = self.command_registry.all_commands()
                suggestions = [
                    f"{prefix}{cmd}"
                    for cmd in all_commands.keys()
                    if cmd.startswith(precommand.lower())
                ]

        if forward:
            self.suggestions.put_nowait(suggestions)
            self.server.send_packet(0x14, String.pack(text), Boolean.pack(False))
        else:
            self.client.send_packet(
                0x3A,
                VarInt.pack(len(suggestions)),
                *(String.pack(s) for s in suggestions),
            )

    @listen_server(0x3A)
    async def packet_server_tab_complete(self, buff: Buffer):
        n_suggestions = buff.unpack(VarInt)
        suggestions: list[str] = []
        for _ in range(n_suggestions):
            suggestions.append(buff.unpack(String))

        try:
            suggestions.extend(self.suggestions.get_nowait())
        except asyncio.QueueEmpty:
            pass  # this should not happen
            # since every case where we receive a tab complete packet
            # from the server should have a corresponding one from the client

        self.client.send_packet(
            0x3A, VarInt.pack(len(suggestions)), *(String.pack(s) for s in suggestions)
        )
