import re

from core.events import listen_client, subscribe
from core.plugin import Plugin
from protocol.datatypes import Buffer, String, TextComponent
from proxhy.errors import CommandException
from proxhy.mcmodels import Game

from .command import command, commands


class CommandsPlugin(Plugin):
    rq_game: Game

    @subscribe("chat:client:/.*")
    async def on_client_chat_command(self, buff: Buffer):
        message = buff.unpack(String)

        segments = message.split()
        command = commands.get(
            segments[0].removeprefix("/").casefold()
        ) or commands.get(segments[0].removeprefix("//").casefold())
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
        if text.startswith("//"):
            self.server.send_packet(0x14, String(text[1:]), buff.read())
        else:
            self.server.send_packet(0x14, buff.getvalue())

    @command("rq")
    async def requeue(self):
        if not self.rq_game.mode:
            raise CommandException("No game to requeue!")
        else:
            self.server.send_packet(0x01, String(f"/play {self.rq_game.mode}"))

    @command()  # Mmm, garlic bread.
    async def garlicbread(self):  # Mmm, garlic bread.
        return TextComponent("Mmm, garlic bread.").color("yellow")  # Mmm, garlic bread.
