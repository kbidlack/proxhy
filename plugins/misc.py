from protocol.datatypes import Item, SlotData, String, TextComponent
from protocol.nbt import dumps, from_dict
from proxhy.argtypes import Gamemode, Submode
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.plugin import ProxhyPlugin

from .window import Window, get_trigger


class MiscPluginState:
    pass


class MiscPlugin(ProxhyPlugin):
    @command("rq")
    async def _command_requeue(self):
        """Requeue the last played game."""
        if not self.rq_game.mode:
            raise CommandException("No game to requeue!")
        self.server.send_packet(0x01, String.pack(f"/play {self.rq_game.mode}"))

    @command("play")
    async def _command_play(self, mode: Gamemode, *submodes: Submode):
        """Convenient aliases for Hypixel's /play command. Ex. /play bedwars solo"""
        server = self.client  # TEST: remove
        if not submodes:
            if Submode.SUBMODES.get(mode.mode_str):
                raise CommandException("Please specify a submode!")
            # no submodes for this game, play directly
            server.chat(f"/play {mode.mode_str}")
        elif submodes[-1].play_id is None:
            raise CommandException("Please specify a complete submode!")
        else:
            server.chat(f"/play {submodes[-1].play_id}")

    @command("pos")
    async def _command_pos(self):
        """Get your current position."""
        self.client.chat(
            f"{self.gamestate.position.x} {self.gamestate.position.y} {self.gamestate.position.z}"
        )

    @command("garlicbread")  # Mmm, garlic bread.
    async def _command_garlicbread(self):  # Mmm, garlic bread.
        """Mmm, garlic bread."""  # Mmm, garlic bread.
        return TextComponent("Mmm, garlic bread.").color("yellow")  # Mmm, garlic bread.

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
