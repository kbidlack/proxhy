import asyncio
import re
from typing import Any, Callable, Coroutine, Union

from core.events import listen_client, listen_server, subscribe
from protocol.datatypes import Buffer, String, TextComponent, VarInt
from proxhy.command import Command, CommandGroup, CommandRegistry
from proxhy.errors import CommandException
from proxhy.plugin import ProxhyPlugin


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
    async def _commands_event_chat_client_command(self, buff: Buffer):
        message = buff.unpack(String)

        segments = message.split()
        cmd_name = segments[0].removeprefix("/").removeprefix("/").casefold()

        command: Union[Command, CommandGroup, None] = self.command_registry.get(
            cmd_name
        )

        if command:
            try:
                # Parse arguments (everything after command name)
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

                error_msg = (
                    TextComponent("∎ ")
                    .bold()
                    .color("blue")
                    .append(err.message)
                    .hover_text(message)
                )
                self.client.chat(error_msg)
            else:
                if output:
                    if segments[0].startswith("//"):  # send output of command
                        # remove chat formatting
                        output = re.sub(r"§.", "", str(output))
                        self.server.chat(output)
                    else:
                        self.client.chat(output)
        else:
            self.server.send_packet(0x01, buff.getvalue())

    async def run_proxhy_command(self, command: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        # TODO: catch command exceptions properly here instead of forwarding to user?
        await self._commands_event_chat_client_command(Buffer(String.pack(command)))

    @listen_client(0x14)
    async def packet_tab_complete(self, buff: Buffer):
        text = buff.unpack(String)

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
            self.server.send_packet(0x14, buff.getvalue())
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
