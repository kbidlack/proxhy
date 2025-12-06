import re
import shelve
from pathlib import Path
from typing import Literal

import hypixel
from platformdirs import user_config_dir

from core.events import listen_client, subscribe
from core.plugin import Plugin
from protocol.datatypes import Buffer, Chat, Item, SlotData, String, TextComponent
from protocol.nbt import dumps, from_dict
from proxhy.command import Command, command
from proxhy.errors import CommandException
from proxhy.formatting import FormattedPlayer
from proxhy.mcmodels import Game

from .window import Window, get_trigger


class CommandsPlugin(Plugin):
    rq_game: Game
    hypixel_client: hypixel.Client

    def _init_commands(self):
        self.commands: dict[str, Command] = {}
        self.AB_DATA_PATH = Path(user_config_dir("proxhy")) / "autoboop.db"

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

    @command("ab")
    async def autoboop(
        self, action: Literal["add", "remove", "list"], player: str = ""
    ):
        if action in {"add", "remove"} and not player:
            raise CommandException(f"Please specify a player to {action}!")

        if action in {"list"} and player:
            raise CommandException(
                TextComponent("/autoboop list")
                .color("gold")
                .appends("takes no arguments!")
            )

        try:
            fplayer = FormattedPlayer
            if player:
                fplayer = FormattedPlayer(await self.hypixel_client.player(player))
        except hypixel.PlayerNotFound:
            raise CommandException(
                TextComponent("Player '")
                .appends(TextComponent(player).color("blue"))
                .appends("' was not found!")
            )
        except hypixel.InvalidApiKey:
            raise CommandException("Invalid API Key!")

        with shelve.open(self.AB_DATA_PATH) as db:
            if action == "list":
                players = sorted(db.keys())
                if not players:
                    return self.client.chat(
                        TextComponent("No players in autoboop!").color("green")
                    )
                self.client.chat(TextComponent("Players in autoboop:").color("green"))
                msg = TextComponent("> ").color("green")
                for i, player in enumerate(players):
                    if i != 0:
                        msg.append(TextComponent(", ").color("green"))
                    msg.append(TextComponent(db.get(player)).color("aqua"))
                self.client.chat(msg)
            elif action == "add":
                if db.get(fplayer.name):
                    raise CommandException(
                        TextComponent("Player")
                        .appends(fplayer.rankname)
                        .appends("is already in autoboop!")
                    )
                db[fplayer.name] = fplayer.rankname
                self.client.chat(
                    TextComponent("Added")
                    .color("green")
                    .appends(
                        TextComponent(fplayer.rankname).appends(
                            TextComponent("to autoboop!").color("green")
                        )
                    )
                )
            else:  # remove
                if not db.get(fplayer.name):
                    raise CommandException(
                        TextComponent("Player")
                        .appends(fplayer.rankname)
                        .appends("is not in autoboop!")
                    )
                del db[fplayer.name]
                self.client.chat(
                    TextComponent("Removed")
                    .color("green")
                    .appends(
                        TextComponent(fplayer.rankname).appends(
                            TextComponent("from autoboop!").color("green")
                        )
                    )
                )

    @subscribe(r"chat:server:(Guild|Friend) > ([A-Za-z0-9_]+) joined.$")
    async def on_guild_join(self, buff: Buffer):
        player = re.match(
            r"^(Guild|Friend) > ([A-Za-z0-9_]+) joined\.$", buff.unpack(Chat)
        )

        if (not player) or (not player.group(2)):
            return

        player = str(player.group(2))

        with shelve.open(self.AB_DATA_PATH) as db:
            if db.get(player):
                self.server.chat(f"/boop {player}")

        self.client.send_packet(0x02, buff.getvalue())

    @command()
    async def fribidiskigma(self):
        async def grass_callback(
            window: Window,
            slot: int,
            button: int,
            action_num: int,
            mode: int,
            clicked_item: SlotData,
        ):
            if clicked_item.item is not None:
                self.client.chat(
                    TextComponent("You clicked")
                    .color("green")
                    .appends(
                        TextComponent(f"{clicked_item.item.display_name}").color("blue")
                    )
                    .appends(TextComponent("in slot").color("green"))
                    .appends(TextComponent(f"{slot}").color("yellow"))
                    .appends(TextComponent("with action #").color("green"))
                    .append(TextComponent(f"{action_num}").color("yellow"))
                    .appends(TextComponent("with trigger").color("green"))
                    .appends(
                        TextComponent(f" {get_trigger(mode, button, slot)}").color(
                            "yellow"
                        )
                    )
                )

            lambda: window  # do something with window

        # example window usage
        self.settings_window = Window(self, "Settings", num_slots=18)

        self.settings_window.set_slot(3, SlotData(Item.from_name("minecraft:stone")))

        self.settings_window.open()

        self.settings_window.set_slot(
            4,
            SlotData(
                Item.from_name("minecraft:grass"),
                nbt=dumps(from_dict({"display": {"Name": "§aFribidi Skigma"}})),
            ),
            callback=grass_callback,
        )
        self.settings_window.set_slot(
            5,
            SlotData(Item.from_name("minecraft:grass")),
            callback=grass_callback,
        )

        return
