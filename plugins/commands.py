import asyncio
import re

from core.events import listen_client, listen_server, subscribe
from core.plugin import Plugin
from protocol.datatypes import Buffer, String, TextComponent, VarInt
from proxhy.command import Command
from proxhy.errors import CommandException


class CommandsPlugin(Plugin):
    def _init_commands(self):
        self.commands: dict[str, Command] = {}
        self.suggestions: asyncio.Queue[list[str]] = asyncio.Queue()

        for item in dir(self):
            try:
                obj = getattr(self, item)
                if hasattr(obj, "_command"):
                    command: Command = getattr(obj, "_command")
                    for alias in command.aliases:
                        self.commands.update({alias: command})
            except AttributeError:
                pass  # yeah

    @subscribe("chat:client:/.*")
    async def on_client_chat_command(self, buff: Buffer):
        message = buff.unpack(String)

        segments = message.split()
        command = self.commands.get(
            segments[0].removeprefix("/").casefold()
        ) or self.commands.get(segments[0].removeprefix("//").casefold())
        if command:
            try:
                output: str | TextComponent = await command(self, message)
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

    @listen_client(0x14)
    async def packet_tab_complete(self, buff: Buffer):
        text = buff.unpack(String)

        precommand = None

        suggestions: list[str] = []

        # generate autocomplete suggestions
        if text.startswith("/"):
            precommand = text.split()[0].removeprefix("/")
        elif text.startswith("//"):
            precommand = text.split()[0].removeprefix("//")
        else:
            ...  # TODO: add dead players if setting is on

        if precommand is not None:
            if " " in text:
                # typed space; indicating starting to type parameters
                # TODO: add parameter completion logic
                suggestions = []
            else:
                # still typing command name
                suggestions = [
                    f"/{command}"
                    for command in self.commands.keys()
                    if command.startswith(precommand)
                ]

        # technically we can await put() here since maxsize is inf but whatever
        self.suggestions.put_nowait(suggestions)

        return self.server.send_packet(0x14, buff.getvalue())

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
