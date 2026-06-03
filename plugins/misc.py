from importlib.metadata import version
from typing import TYPE_CHECKING

from petty.nbt import dumps, from_dict
from petty.protocol.datatypes import Item, SlotData, String, TextComponent
from plugins.commands import CommandException, command
from proxhy.argtypes import Gamemode, Submode
from proxhy.utils import zero_pad_calver

from .window import Window, get_trigger

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin


class MiscPlugin:
    @command("version")
    async def _command_version(self: ProxhyPlugin):
        """Get the currently running version of Proxhy."""
        return TextComponent(zero_pad_calver(version("proxhy"))).color("yellow")

    @command("rq")
    async def _command_requeue(self: ProxhyPlugin):
        """Requeue the last played game."""
        if not self.rq_game.mode:
            raise CommandException("No game to requeue!")
        self.upstream.send_packet(0x01, String.pack(f"/play {self.rq_game.mode}"))

    @command("play")
    async def _command_play(self: ProxhyPlugin, mode: Gamemode, *submodes: Submode):
        """Convenient aliases for Hypixel's /play command. Ex. /play bedwars solo"""
        if mode.raw_play_id:
            self.upstream.chat(f"/play {mode.raw_play_id}")
        elif not submodes:
            if submode_options := Submode.SUBMODES.get(mode.mode_str):
                options = ", ".join(sorted(submode_options.keys()))
                raise CommandException(
                    TextComponent("Please specify a submode! Options: ").append(
                        TextComponent(options).color("dark_aqua")
                    )
                )
            # no submodes for this game, play directly
            self.upstream.chat(f"/play {mode.mode_str}")
        elif submodes[-1].play_id is None:
            options = ", ".join(sorted((submodes[-1].node.children or {}).keys()))
            raise CommandException(
                TextComponent("Please specify a complete submode! Options: ").append(
                    TextComponent(options).color("dark_aqua")
                )
            )
        else:
            self.upstream.chat(f"/play {submodes[-1].play_id}")

    @command("pos")
    async def _command_pos(self: ProxhyPlugin):
        """Get your current position."""
        self.downstream.chat(
            f"{self.gamestate.position.x} {self.gamestate.position.y} {self.gamestate.position.z}"
        )

    @command("garlicbread")  # Mmm, garlic bread.
    async def _command_garlicbread(self: ProxhyPlugin):  # Mmm, garlic bread.
        """Mmm, garlic bread."""  # Mmm, garlic bread.
        return TextComponent("Mmm, garlic bread.").color("yellow")  # Mmm, garlic bread.

    @command("fribidiskigma")
    async def _command_fribidiskigma(self: ProxhyPlugin):
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
                self.downstream.chat(
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
