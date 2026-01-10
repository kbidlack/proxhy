import re
import shelve
from pathlib import Path

import hypixel
from platformdirs import user_config_dir

from core.events import subscribe
from core.plugin import Plugin
from protocol.datatypes import Buffer, Chat, Item, SlotData, TextComponent
from protocol.nbt import dumps, from_dict
from proxhy.argtypes import HypixelPlayer
from proxhy.command import CommandGroup, CommandRegistry, command
from proxhy.errors import CommandException
from proxhy.mcmodels import Game

from .window import Window, get_trigger


class MiscPlugin(Plugin):
    hypixel_client: hypixel.Client
    rq_game: Game
    command_registry: CommandRegistry  # From CommandsPlugin mixin

    def _init_misc(self):
        self.AB_DATA_PATH = Path(user_config_dir("proxhy")) / "autoboop.db"

        # Set up autoboop command group
        self.autoboop_group = CommandGroup("autoboop", "ab")

        @self.autoboop_group.command("list", "ls")
        async def _autoboop_list(self):
            with shelve.open(self.AB_DATA_PATH) as db:
                players = sorted(db.keys())
                if not players:
                    return TextComponent("No players in autoboop!").color("green")

                self.client.chat(TextComponent("Players in autoboop:").color("green"))
                msg = TextComponent("> ").color("green")
                for i, name in enumerate(players):
                    if i != 0:
                        msg.append(TextComponent(", ").color("green"))
                    msg.append(TextComponent(db.get(name)).color("aqua"))
                return msg

        @self.autoboop_group.command("add")
        async def _autoboop_add(self, player: HypixelPlayer):
            from proxhy.formatting import FormattedPlayer

            fplayer = FormattedPlayer(player._player)

            with shelve.open(self.AB_DATA_PATH) as db:
                if db.get(fplayer.name):
                    raise CommandException(
                        TextComponent("Player ")
                        .append(fplayer.rankname)
                        .appends("is already in autoboop!")
                    )
                db[fplayer.name] = fplayer.rankname

            return (
                TextComponent("Added ")
                .color("green")
                .append(fplayer.rankname)
                .appends(TextComponent("to autoboop!").color("green"))
            )

        @self.autoboop_group.command("remove", "rm")
        async def _autoboop_remove(self, player: HypixelPlayer):
            from proxhy.formatting import FormattedPlayer

            fplayer = FormattedPlayer(player._player)

            with shelve.open(self.AB_DATA_PATH) as db:
                if not db.get(fplayer.name):
                    raise CommandException(
                        TextComponent("Player ")
                        .append(fplayer.rankname)
                        .appends("is not in autoboop!")
                    )
                del db[fplayer.name]

            return (
                TextComponent("Removed ")
                .color("green")
                .append(fplayer.rankname)
                .appends(TextComponent("from autoboop!").color("green"))
            )

        self.command_registry.register(self.autoboop_group)

    @command("fribidiskigma")
    async def _command_fribidiskigma(self):
        """Example window usage demo."""

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
                    TextComponent("You clicked ")
                    .color("green")
                    .append(TextComponent(clicked_item.item.display_name).color("blue"))
                    .appends("in slot")
                    .appends(TextComponent(str(slot)).color("yellow"))
                    .appends("with action #")
                    .append(TextComponent(str(action_num)).color("yellow"))
                    .appends("with trigger")
                    .appends(
                        TextComponent(get_trigger(mode, button, slot)).color("yellow")
                    )
                )

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

    @subscribe(r"chat:server:(Guild|Friend) > ([A-Za-z0-9_]+) joined.$")
    async def on_guild_join(self, buff: Buffer):
        player = re.match(
            r"^(Guild|Friend) > ([A-Za-z0-9_]+) joined\.$", buff.unpack(Chat)
        )

        if not player or not player.group(2):
            return

        player_name = str(player.group(2))

        with shelve.open(self.AB_DATA_PATH) as db:
            if db.get(player_name):
                self.server.chat(f"/boop {player_name}")

        self.client.send_packet(0x02, buff.getvalue())
