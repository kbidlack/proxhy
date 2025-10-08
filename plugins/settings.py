import math
from textwrap import fill
from typing import Any

from core.plugin import Plugin
from core.settings import Setting, SettingGroup
from protocol.datatypes import (
    Item,
    SlotData,
    String,
    TextComponent,
)
from protocol.nbt import dumps, from_dict
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.mcmodels import Game
from proxhy.settings import ProxhySettings

from .window import Window


class SettingsPlugin(Plugin):
    rq_game: Game
    settings: ProxhySettings

    def _init_settings(self):
        self.settings = ProxhySettings()

    @command("s")
    async def proxhysettings(self):
        self.settings_window = SettingsMenu(self)

        self.settings_window.open()

    @command("setting")
    async def edit_settings(self, setting_name: str = "", value: str = ""):
        value_oc = value
        value = value.upper()
        setting_attrs = setting_name.split(".")

        if len(setting_attrs) == 1:
            setting_name = setting_attrs[0]
            if not hasattr(self.settings, setting_name):
                msg = (
                    TextComponent("Setting")
                    .appends(TextComponent(f"'{setting_name}'").color("gold"))
                    .appends(TextComponent("does not exist!"))
                )
                raise CommandException(msg)
            setting_attrs = [setting_name]
            parent_obj = self.settings
        else:
            prev_sa = "settings"
            parent_obj = self.settings
            for sa in setting_attrs[:-1]:
                if not hasattr(parent_obj, sa):
                    if isinstance(parent_obj, SettingGroup):
                        msg = (
                            TextComponent("Setting group")
                            .appends(TextComponent(f"'{prev_sa}'").color("gold"))
                            .appends("does not have a setting named")
                            .appends(TextComponent(f"'{sa}'").color("gold"))
                            .append("!")
                        )
                        raise CommandException(msg)
                    elif isinstance(parent_obj, Setting):
                        msg = (
                            TextComponent(f"'{prev_sa}'")
                            .color("gold")
                            .appends("is a setting!")
                        )
                        raise CommandException(msg)
                    else:
                        raise CommandException("This should not happen!")
                prev_sa = sa
                parent_obj = getattr(parent_obj, sa)

        if not hasattr(parent_obj, setting_attrs[-1]):
            if isinstance(parent_obj, SettingGroup):
                msg = (
                    TextComponent("Setting group")
                    .appends(
                        TextComponent(f"'{'.'.join(setting_attrs[:-1])}'").color("gold")
                    )
                    .appends("does not have a setting named")
                    .appends(TextComponent(f"'{setting_attrs[-1]}'").color("gold"))
                    .append("!")
                )
                raise CommandException(msg)
            elif isinstance(parent_obj, Setting):
                msg = (
                    TextComponent(f"'{'.'.join(setting_attrs[:-1])}'")
                    .color("gold")
                    .appends("is a setting!")
                )
                raise CommandException(msg)
            else:
                raise CommandException("This should not happen!")

        setting_obj = getattr(parent_obj, setting_attrs[-1])

        if isinstance(setting_obj, SettingGroup):
            msg = (
                TextComponent(f"'{setting_name}'")
                .color("gold")
                .appends("is a setting group!")
            )
            raise CommandException(msg)
        elif isinstance(setting_obj, Setting):
            setting_obj: Setting
        else:
            raise CommandException("This should not happen!")

        if value and (value not in setting_obj.states):
            msg = TextComponent("Invalid value").appends(
                TextComponent(f"'{value_oc}'")
                .color("gold")
                .appends("for setting")
                .appends(TextComponent(f"'{setting_name}'"))
                .append(";")
                .appends("valid values are: ")
            )
            for i, tc in enumerate(
                map(
                    lambda t: TextComponent(t).color("green"),
                    setting_obj.states.keys(),
                )
            ):
                if not i == len(setting_obj.states.keys()) - 1:
                    msg.append(tc).append(TextComponent(","))
                else:
                    msg.append(tc)

            raise CommandException(msg)

        old_state = setting_obj.get()
        old_state_color = setting_obj.states[old_state]
        new_state = value or setting_obj.toggle()[1]
        setting_obj.set(new_state)
        new_state_color = setting_obj.states[new_state]

        settings_msg = (
            TextComponent("Changed")
            .appends(TextComponent(setting_obj.display_name).color("yellow"))
            .appends(TextComponent("from"))
            .appends(TextComponent(old_state.upper()).bold().color(old_state_color))
            .appends(TextComponent("to"))
            .appends(TextComponent(new_state.upper()).bold().color(new_state_color))
            .append(TextComponent("!"))
        )
        self.client.chat(settings_msg)

        await self.emit(f"setting:{setting_name}", [old_state, new_state])

    @command("rq")
    async def requeue(self):
        if not self.rq_game.mode:
            raise CommandException("No game to requeue!")
        else:
            self.server.send_packet(0x01, String(f"/play {self.rq_game.mode}"))

    @command()  # Mmm, garlic bread.
    async def garlicbread(self):  # Mmm, garlic bread.
        return TextComponent("Mmm, garlic bread.").color("yellow")  # Mmm, garlic bread.


class SettingsMenu(Window):
    # TODO: add support for multiple pages of settings/groups within a category
    def __init__(
        self,
        proxy: Plugin,
        num_slots: int = 18,
        subsetting_path: str = "",
        window_title: str = "Settings",
    ):
        if num_slots % 9 != 0:
            raise ValueError(
                f"Expected multiple of 9 for num_slots; got {num_slots} instead."
            )
        super().__init__(proxy, window_title, "minecraft:chest", num_slots)
        self.num_slots = num_slots
        self.proxy: SettingsPlugin = proxy  # type: ignore
        self.settings = self.proxy.settings
        self.subsetting_path = subsetting_path
        self.subsetting_group: SettingGroup = self.settings.get_setting_by_path(
            subsetting_path
        )  # type: ignore

        self.DISABLED_STATES = {"off", "none", "disabled"}

        self.menu_slots = dict()
        self.window_items = []

        self.build()

    def build(self):
        self.settings = (
            self.proxy.settings
        )  # re-initialize settings so this can rebuild when settings update
        self.subsetting_group: SettingGroup = self.settings.get_setting_by_path(
            self.subsetting_path
        )  # type: ignore
        self.window_items: list[dict] = self.get_formatted_items()
        for i in self.window_items:
            slot, slot_data, callback = i.values()
            self.set_slot(slot - 1, slot_data, callback=callback)

    def clear(self):
        self.menu_slots.clear()
        for i in self.window_items:
            slot, slot_data, callback = i.values()
            self.set_slot(slot - 1, SlotData())  # clear slot

    @staticmethod
    def get_setting_toggle_msg(
        s_display, old_state, new_state, old_state_color, new_state_color
    ) -> TextComponent:
        toggle_msg = (
            TextComponent("Changed")
            .appends(TextComponent(s_display).color("yellow"))
            .appends(TextComponent("from"))
            .appends(TextComponent(old_state.upper()).bold().color(old_state_color))
            .appends(TextComponent("to"))
            .appends(TextComponent(new_state.upper()).bold().color(new_state_color))
            .append(TextComponent("!"))
        )
        return toggle_msg

    def get_state_item(self, state: str) -> SlotData:
        if str(state).lower() in self.DISABLED_STATES:
            item = Item.from_display_name("Red Stained Glass Pane")
            slot_data = SlotData(
                item,
                damage=item.data,
                nbt=dumps(from_dict({"display": {"Name": f"§c§l{state.upper()}"}})),
            )
        else:  # assume enabled in some form
            item = Item.from_display_name("Lime Stained Glass Pane")
            slot_data = SlotData(
                item,
                damage=item.data,
                nbt=dumps(from_dict({"display": {"Name": f"§a§l{state.upper()}"}})),
            )
        return slot_data

    def get_formatted_items(self) -> list[dict]:
        """Return chest menu layout for settings page; centers everything"""

        items = []
        # back button in bottom left
        items.append(
            {
                "slot": self.num_slots - 8,
                "slot_data": SlotData(
                    Item.from_name("minecraft:feather"),
                    nbt=dumps(from_dict({"display": {"Name": "§rBack"}})),
                ),
                "callback": self.back_button_callback,
            }
        )
        # next button in bottom right
        # not implemented yet, but will go to next page (or loop back to first)
        items.append(
            {
                "slot": self.num_slots,
                "slot_data": SlotData(
                    Item.from_name("minecraft:arrow"),
                    nbt=dumps(from_dict({"display": {"Name": "§rNext"}})),
                ),
                "callback": NotImplemented,
            }
        )

        n_settings = len(self.subsetting_group.get_all_settings())
        n_groups = len(self.subsetting_group.get_all_groups())

        # num of slots allocated for each menu feature
        n_alloc_groups = math.ceil(n_groups / 2) * 2
        n_alloc_settings = n_settings * 2
        n_alloc_nav = 2  # feather & arrow
        n_alloc_padding = 6  # base padding around navigation buttons
        if n_settings and n_groups:
            n_alloc_padding += 2  # divide settings & groups
        slots_needed = n_alloc_groups + n_alloc_settings + n_alloc_nav + n_alloc_padding

        if slots_needed > self.num_slots:
            # this is def not how ur supposed to use OverflowError but IDGAF LET ME LIVE MY LIFE
            raise OverflowError(
                f"Got {n_settings} settings and {n_groups} groups; can't fit into {self.num_slots} slots! ({slots_needed} slots required)"
            )

        # align settings to center (slot 5 in the middle)

        # make a list of the actual settings, excluding groups & metadata like description & item
        # setting_entries: list[tuple[str, dict]] = [
        #     (k, v)
        #     for k, v in self.subsettings.items()
        #     if isinstance(v, dict) and "states" in v and "state" in v
        # ]
        # if n_groups > 0:
        #     group_entries = [
        #         (k, v)
        #         for k, v in self.subsettings.items()
        #         if isinstance(v, dict) and "states" not in v and "state" not in v
        #     ]
        # else:  # for type checker, otherwise "group_entries is possibly unbound"
        #     group_entries = []

        for i, s in enumerate(self.subsetting_group.get_all_settings()):
            if n_groups == 0:
                slot = (6 - math.floor(n_settings / 2)) + i - 1
                if (n_settings % 2 == 0) and (
                    (i / n_settings) >= 0.5
                ):  # even & past midpoint
                    slot += 1  # gap in middle for symmetry
            else:
                slot = 4 + (n_alloc_groups // 2) + i

            lore = fill(s.description, width=30).split("\n")
            lore = ["§7" + t for t in lore]
            lore.extend(["", "§8(Click to toggle)"])  # "" adds a newline

            display_nbt: dict[str, Any] = {  # display item
                "display": {"Name": f"§r§l{s.display_name}", "Lore": lore}
            }

            # add glint if setting is enabled
            if s.get().lower() not in self.DISABLED_STATES:
                display_nbt["ench"] = []

            items.append(
                {
                    "slot": slot + 9,
                    "slot_data": SlotData(
                        Item.from_name(s.item), nbt=dumps(from_dict(display_nbt))
                    ),
                    "callback": self.toggle_state_callback,
                }
            )

            items.append(
                {  # state display glass pane, above display item
                    "slot": slot,
                    "slot_data": self.get_state_item(s.get()),
                    "callback": self.toggle_state_callback,
                }
            )

            # save what setting is associated with this slot
            if slot in self.menu_slots:
                raise IndexError(
                    f"Tried to allocate slot {slot} for setting '{s.name}', but it was already allocated for '{self.menu_slots[slot]}'!"
                )
            self.menu_slots[slot] = s.name
            self.menu_slots[slot + 9] = s.name

        if n_groups > 0:
            for i, g in enumerate(self.subsetting_group.get_all_groups()):
                if (
                    n_settings == 0
                ):  # if there are no settings, groups should fill by rows not columns
                    if i <= 5:
                        slot = i + 3
                    else:
                        slot = i + 12
                else:  # if there are settings AND groups, groups should fill by columns to conserve space
                    if i % 2 == 0:
                        slot = math.floor(i / 2) + 3
                    else:
                        slot = math.floor(i / 2) + 12

                lore = fill(g.description, width=30).split("\n")
                lore = ["§7" + t for t in lore]
                lore.extend(["", "§8(Click to open category)"])  # "" adds a newline

                display_nbt: dict[str, Any] = {  # display item
                    "display": {"Name": f"§r§l{g.display_name}", "Lore": lore}
                }

                items.append(
                    {
                        "slot": slot,
                        "slot_data": SlotData(
                            Item.from_name(g.item), nbt=dumps(from_dict(display_nbt))
                        ),
                        "callback": self.open_group_callback,
                    }
                )
                if slot in self.menu_slots:
                    raise IndexError(
                        f"Tried to allocate slot {slot} for setting '{g.name}', but it was already allocated for '{self.menu_slots[slot]}'!"
                    )
                self.menu_slots[slot] = g.name
        return items

    async def toggle_state_callback(
        self,
        window: Window,
        slot: int,
        button: int,
        action_num: int,
        mode: int,
        clicked_item: SlotData,
    ):
        try:
            setting: str = self.menu_slots[slot + 1]
        except KeyError:
            raise KeyError(
                f"Slot {slot + 1} has no associated element.\nElements: {self.menu_slots}"
            )
        s_path: str = self.subsetting_path + "." + setting
        prev_state, next_state = self.settings.toggle_setting_by_path(s_path)
        self.clear()
        self.build()

        s_raw = self.settings.get_setting_by_path(s_path)
        s_display = s_raw.display_name
        prev_color = s_raw.states[prev_state]  # type: ignore
        next_color = s_raw.states[next_state]  # type: ignore
        msg = self.get_setting_toggle_msg(
            s_display, prev_state, next_state, prev_color, next_color
        )

        self.proxy.client.chat(msg)

        await self.proxy.emit(f"setting:{s_path}", [prev_state, next_state])

    def open_group_callback(
        self,
        window: Window,
        slot: int,
        button: int,
        action_num: int,
        mode: int,
        clicked_item: SlotData,
    ):
        try:
            group: str = self.menu_slots[slot + 1]
        except KeyError:
            raise KeyError(
                f"Slot {slot + 1} has no associated element.\nElements: {self.menu_slots}"
            )
        if self.subsetting_path:
            g_path: str = self.subsetting_path + "." + group
        else:
            g_path: str = group  # if we are already at the root
        self.subsetting_path = g_path
        self.clear()
        self.build()

    def back_button_callback(
        self,
        window: Window,
        slot: int,
        button: int,
        action_num: int,
        mode: int,
        clicked_item: SlotData,
    ):
        if self.subsetting_path:
            itemized: list = self.subsetting_path.split(".")
            itemized.remove(itemized[-1])
            self.subsetting_path = ".".join(itemized)
            self.clear()
            self.build()
        else:  # at the root already
            pass
