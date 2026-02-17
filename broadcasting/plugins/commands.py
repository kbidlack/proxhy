import re
from typing import Optional

from broadcasting.plugin import BroadcastPeerPlugin
from core.events import subscribe
from plugins.commands import Command, CommandException, CommandGroup, CommandsPlugin
from protocol.datatypes import (
    Buffer,
    String,
    TextComponent,
    VarInt,
)


class BroadcastPeerCommandsPlugin(BroadcastPeerPlugin, CommandsPlugin):
    async def _run_command(self, message: str):
        segments = message.split()
        cmd_name = segments[0].removeprefix("/").removeprefix("/").casefold()

        command: Optional[Command | CommandGroup] = self.command_registry.get(cmd_name)

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
                        self.proxy.bc_chat(self.username, output)
                    else:
                        if isinstance(output, TextComponent):
                            if output.data.get("clickEvent") is None:
                                output = output.click_event("suggest_command", message)
                        self.client.chat(output)
        else:
            self.client.chat(
                TextComponent(f"Unknown command '{cmd_name}'")
                .color("red")
                .click_event("suggest_command", message)
            )

    async def _tab_complete(self, text: str):
        precommand = None
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

        self.client.send_packet(
            0x3A,
            VarInt.pack(len(suggestions)),
            *(String.pack(s) for s in suggestions),
        )

    @subscribe("chat:client:.*")
    async def _broadcast_peer_base_event_chat_client_any(self, _match, buff: Buffer):
        msg = buff.unpack(String)
        if msg.startswith("/"):
            return  # command plugin

        self.proxy.bc_chat(self.username, msg)
