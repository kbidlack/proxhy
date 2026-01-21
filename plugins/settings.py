import math
from textwrap import fill
from typing import Any

from core.settings import SettingGroup
from protocol.datatypes import (
    Item,
    SlotData,
    TextComponent,
)
from protocol.nbt import dumps, from_dict
from proxhy.argtypes import SettingPath, SettingValue
from proxhy.command import command
from proxhy.plugin import ProxhyPlugin
from proxhy.settings import ProxhySettings

from .window import Window


class SettingsPluginState:
    settings: ProxhySettings


class SettingsPlugin(ProxhyPlugin):
    def _init_settings(self):
        self.settings = ProxhySettings()

    @command("s")
    async def _command_settings(self):
        """Open the settings GUI."""
        self.settings_window = SettingsMenu(self)
        self.settings_window.open()

    @command("setting", "set")
    async def _command_setting(
        self,
        setting: SettingPath = None,  # type: ignore
        value: SettingValue = None,  # type: ignore
    ):
        """Toggle or set a setting value."""
        if setting is None:
            return (
                TextComponent("Usage: ")
                .color("yellow")
                .append(TextComponent("/setting <path> [value]").color("gold"))
            )

        # Note: SettingValue validation is now handled automatically via CommandContext

        # Get old state and set new state
        old_state = setting.setting.get()
        old_color = setting.setting.states[old_state]

        if value is not None:
            setting.setting.set(value.value)
            new_state = value.value
        else:
            _, new_state = setting.setting.toggle()

        new_color = setting.setting.states[new_state]

        # Send confirmation message
        self.client.chat(
            TextComponent("Changed ")
            .append(TextComponent(setting.setting.display_name).color("yellow"))
            .appends("from")
            .appends(TextComponent(old_state).bold().color(old_color))
            .appends("to")
            .appends(TextComponent(new_state).bold().color(new_color))
            .append("!")
        )

        await self.emit(f"setting:{setting.path}", [old_state, new_state])


class SettingsMenu(Window):
    def __init__(
        self,
        proxy: ProxhyPlugin,
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
        self.menu_slots: dict[int, str] = {}
        self.window_items: list[dict] = []

        self.build()

    def build(self):
        self.settings = self.proxy.settings
        self.subsetting_group = self.settings.get_setting_by_path(self.subsetting_path)  # type: ignore
        self.window_items = self.get_formatted_items()
        for item in self.window_items:
            slot, slot_data, callback = item.values()
            self.set_slot(slot - 1, slot_data, callback=callback)

    def clear(self):
        self.menu_slots.clear()
        for item in self.window_items:
            slot = item["slot"]
            self.set_slot(slot - 1, SlotData())

    @staticmethod
    def get_setting_toggle_msg(
        s_display: str,
        old_state: str,
        new_state: str,
        old_state_color: str,
        new_state_color: str,
    ) -> TextComponent:
        return (
            TextComponent("Changed ")
            .append(TextComponent(s_display).color("yellow"))
            .appends("from")
            .appends(TextComponent(old_state.upper()).bold().color(old_state_color))  # type: ignore[arg-type]
            .appends("to")
            .appends(TextComponent(new_state.upper()).bold().color(new_state_color))  # type: ignore[arg-type]
            .append("!")
        )

    def get_state_item(self, state: str) -> SlotData:
        if str(state).lower() in self.DISABLED_STATES:
            item = Item.from_display_name("Red Stained Glass Pane")
            slot_data = SlotData(
                item,
                damage=item.data,
                nbt=dumps(from_dict({"display": {"Name": f"§c§l{state.upper()}"}})),
            )
        else:
            item = Item.from_display_name("Lime Stained Glass Pane")
            slot_data = SlotData(
                item,
                damage=item.data,
                nbt=dumps(from_dict({"display": {"Name": f"§a§l{state.upper()}"}})),
            )
        return slot_data

    def get_formatted_items(self) -> list[dict]:
        """Return chest menu layout for settings page; centers everything."""
        items: list[dict] = []

        # Navigation buttons
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

        all_settings = self.subsetting_group.get_all_settings()
        all_groups = self.subsetting_group.get_all_groups()
        n_settings = len(all_settings)
        n_groups = len(all_groups)

        # Calculate slot allocation
        n_alloc_groups = math.ceil(n_groups / 2) * 2
        n_alloc_settings = n_settings * 2
        n_alloc_nav = 2
        n_alloc_padding = 6
        if n_settings and n_groups:
            n_alloc_padding += 2
        slots_needed = n_alloc_groups + n_alloc_settings + n_alloc_nav + n_alloc_padding

        if slots_needed > self.num_slots:
            raise OverflowError(
                f"Got {n_settings} settings and {n_groups} groups; "
                f"can't fit into {self.num_slots} slots! ({slots_needed} required)"
            )

        # Add settings
        for i, s in enumerate(all_settings):
            if n_groups == 0:
                slot = (6 - math.floor(n_settings / 2)) + i - 1
                if (n_settings % 2 == 0) and ((i / n_settings) >= 0.5):
                    slot += 1
            else:
                slot = 4 + (n_alloc_groups // 2) + i

            lore = fill(s.description, width=30).split("\n")
            lore = ["§7" + t for t in lore]
            lore.extend(["", "§8(Click to toggle)"])

            display_nbt: dict[str, Any] = {  # pyright: ignore[reportRedeclaration]
                "display": {"Name": f"§r§l{s.display_name}", "Lore": lore}
            }
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
                {
                    "slot": slot,
                    "slot_data": self.get_state_item(s.get()),
                    "callback": self.toggle_state_callback,
                }
            )

            if slot in self.menu_slots:
                raise IndexError(
                    f"Slot {slot} already allocated for '{self.menu_slots[slot]}'"
                )
            self.menu_slots[slot] = s.name
            self.menu_slots[slot + 9] = s.name

        # Add groups
        for i, g in enumerate(all_groups):
            if n_settings == 0:
                slot = i + 3 if i <= 5 else i + 12
            else:
                slot = math.floor(i / 2) + 3 if i % 2 == 0 else math.floor(i / 2) + 12

            lore = fill(g.description, width=30).split("\n")
            lore = ["§7" + t for t in lore]
            lore.extend(["", "§8(Click to open category)"])

            display_nbt: dict[str, Any] = {
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
                    f"Slot {slot} already allocated for '{self.menu_slots[slot]}'"
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
        setting_name = self.menu_slots.get(slot + 1)
        if not setting_name:
            raise KeyError(f"Slot {slot + 1} has no associated element")

        s_path = (
            f"{self.subsetting_path}.{setting_name}"
            if self.subsetting_path
            else setting_name
        )
        prev_state, next_state = self.settings.toggle_setting_by_path(s_path)
        self.clear()
        self.build()

        s_raw = self.settings.get_setting_by_path(s_path)
        msg = self.get_setting_toggle_msg(
            s_raw.display_name,
            prev_state,
            next_state,
            s_raw.states[prev_state],  # type: ignore
            s_raw.states[next_state],  # type: ignore
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
        group_name = self.menu_slots.get(slot + 1)
        if not group_name:
            raise KeyError(f"Slot {slot + 1} has no associated element")

        g_path = (
            f"{self.subsetting_path}.{group_name}"
            if self.subsetting_path
            else group_name
        )
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
            parts = self.subsetting_path.split(".")
            self.subsetting_path = ".".join(parts[:-1])
            self.clear()
            self.build()
