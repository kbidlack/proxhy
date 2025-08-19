from __future__ import annotations

import asyncio
import inspect
import math
import random
from copy import deepcopy
from functools import wraps
from textwrap import fill
from typing import Any, Awaitable, Callable, Literal, Optional, SupportsIndex, overload

from core.events import listen_client
from core.plugin import Plugin
from protocol.datatypes import (
    Buffer,
    Byte,
    Chat,
    Int,
    Item,
    Short,
    Slot,
    SlotData,
    String,
    TextComponent,
    UnsignedByte,
)
from protocol.nbt import dumps, from_dict
from proxhy.settings import Settings


class WindowPlugin(Plugin):
    def _init_window(self):
        self.settings = Settings()
        self.windows: dict[int, Window] = {}

    @listen_client(0x0D)
    async def packet_close_window(self, buff: Buffer):
        window_id = buff.unpack(UnsignedByte)
        if window_id in self.windows:
            self.windows[window_id].close()
        else:
            self.server.send_packet(0x0D, buff.getvalue())

    @listen_client(0x0E)
    async def packet_click_window(self, buff: Buffer):
        window_id = buff.unpack(UnsignedByte)
        slot = buff.unpack(Short)
        button = buff.unpack(Byte)
        action_num = buff.unpack(Short)
        mode = buff.unpack(Byte)
        clicked_item = buff.unpack(Slot)

        if (
            window_id in self.windows
            and not slot == -999
            and self.windows[window_id]._open
        ):
            if self.windows[window_id].data[slot][1]:  # callback
                callback = self.windows[window_id].data[slot][1]
                if inspect.iscoroutinefunction(callback):
                    asyncio.create_task(
                        callback(
                            self.windows[window_id],
                            slot,
                            button,
                            action_num,
                            mode,
                            clicked_item,
                        )
                    )
                elif isinstance(callback, Callable):
                    callback(
                        self.windows[window_id],
                        slot,
                        button,
                        action_num,
                        mode,
                        clicked_item,
                    )
            if self.windows[window_id].data[slot][2]:  # if locked
                self.windows[window_id].update()
                self.client.send_packet(
                    0x2F, Byte.pack(-1), Short.pack(-1), Slot.pack(SlotData())
                )
        else:
            self.server.send_packet(0x0E, buff.getvalue())


def ensure_open(open=True):
    def decorator(func):
        @wraps(func)
        def wrapper(self: Window, *args, **kwargs):
            if self._open == open:
                return func(self, *args, **kwargs)
            return lambda: None

        return wrapper

    return decorator


type SlotType = tuple[SlotData, Optional[Callable | Awaitable], bool]


class Slots(list[SlotType]):
    @overload
    def __getitem__(self, s: SupportsIndex) -> SlotType: ...

    @overload
    def __getitem__(self, s: slice) -> list[SlotType]: ...

    def __getitem__(self, s: SupportsIndex | slice) -> SlotType | list[SlotType]:
        if isinstance(s, int):
            if s == -999 or s >= len(self):
                return (SlotData(), None, False)
            return super().__getitem__(s)
        else:
            return super().__getitem__(s)


class Window:
    def __init__(
        self,
        proxy: Plugin,
        window_title: str = "Chest",
        window_type: str = "minecraft:chest",
        num_slots: int = 27,
        entity_id: Optional[int] = None,
    ):
        self.proxy: WindowPlugin = proxy  # type: ignore
        self.window_title = window_title
        self.window_type = window_type
        self.num_slots = num_slots
        self.entity_id = entity_id

        # initialize with empty slots
        self.data = Slots([(SlotData(), None, False) for _ in range(num_slots)])

        self.callbacks: dict[str, Callable | Awaitable] = {}

        self._open = False

    def clone(self) -> Window:
        return deepcopy(self)

    def set_slot(
        self,
        slot: int,
        slot_data: SlotData,
        callback: Optional[Callable | Awaitable] = None,
        locked=True,
    ):
        """Set a slot in the window."""
        if slot < 0 or slot >= self.num_slots:
            raise IndexError(
                f"Slot index {slot} out of range for window with {self.num_slots} slots."
            )

        self.data[slot] = (slot_data, callback, locked)

        if self._open:
            self.proxy.client.send_packet(
                0x2F, Byte.pack(self.window_id), Short.pack(slot), Slot.pack(slot_data)
            )

    @ensure_open(open=False)
    def open(self):
        self.window_id = random.randint(101, 127)  # (notchian) server uses 1-100
        while self.window_id in self.proxy.windows:
            self.window_id = random.randint(101, 127)  # ensure unique window_id

        # TODO: if we have too many windows there are collisions? but no way...
        self.proxy.windows.update({self.window_id: self})
        self._open = True

        self.proxy.client.send_packet(
            0x2D,
            UnsignedByte.pack(self.window_id),
            String.pack(self.window_type),
            Chat.pack(self.window_title),
            UnsignedByte.pack(self.num_slots),
            Int.pack(self.entity_id) if self.entity_id is not None else b"",
        )
        self.update()

    @ensure_open()
    def close(self):
        self._open = False
        self.proxy.client.send_packet(0x2E, UnsignedByte.pack(self.window_id))
        del self.proxy.windows[self.window_id]

    @ensure_open()
    def update(self):
        self.proxy.client.send_packet(
            0x30,
            UnsignedByte.pack(self.window_id),
            Short.pack(self.num_slots),
            b"".join(Slot.pack(sd[0]) for sd in self.data),
        )


class SettingsMenu(Window):
    def __init__(
        self,
        proxy: Plugin,
        num_slots: int = 18,
        subsetting_path: str = "bedwars.tablist",
    ):
        if num_slots % 9 != 0:
            raise ValueError(
                f"Expected multiple of 9 for num_slots; got {num_slots} instead."
            )
        super().__init__(proxy, "Settings", "minecraft:chest", num_slots)
        self.num_slots = num_slots
        self.proxy: WindowPlugin = proxy  # type: ignore
        self.settings = self.proxy.settings
        self.subsetting_path = subsetting_path
        self.subsettings: dict = self.settings.get_setting_by_path(subsetting_path)
        self.DISABLED_STATES = {"off", "none", "disabled"}

        self.setting_slots = dict()
        self.window_items = []

        self.build()

    def build(self):
        self.settings = (
            self.proxy.settings
        )  # re-initialize settings so this can rebuild when settings update
        self.window_items = self.get_formatted_items()
        for i in self.window_items:
            slot, slot_data, callback = i.values()
            self.set_slot(slot - 1, slot_data, callback=callback)

    def clear(self):
        self.setting_slots.clear()
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
        items.append(
            {
                "slot": self.num_slots - 8,
                "slot_data": SlotData(
                    Item.from_name("minecraft:feather"),
                    nbt=dumps(from_dict({"display": {"Name": "§rBack"}})),
                ),
                "callback": None,
            }
        )
        items.append(
            {
                "slot": self.num_slots,
                "slot_data": SlotData(
                    Item.from_name("minecraft:arrow"),
                    nbt=dumps(from_dict({"display": {"Name": "§rNext"}})),
                ),
                "callback": None,
            }
        )

        n_settings = sum(
            [
                1
                for s in self.subsettings.values()
                if (isinstance(s, dict) and "states" in s)
            ]
        )
        n_groups = sum(
            [
                1
                for s in self.subsettings.values()
                if (isinstance(s, dict) and "states" not in s)
            ]
        )

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
        if n_settings % 2 == 0:
            is_even = True
        else:
            is_even = False
        print(f"is_even: {is_even}")

        # align settings to center (slot 5 in the middle)
        # if is_even, put a gap in the middle for symmetry

        # make a list of the actual settings, excluding group metadata like description & item
        subsettings_non_metadata = []
        for s in self.subsettings.values():
            if not isinstance(s, dict):  # catch description/other metadata
                continue
            subsettings_non_metadata.append(s)

        for i, s in enumerate(subsettings_non_metadata):
            slot = (6 - math.floor(n_settings / 2)) + i - 1
            if is_even and ((i / n_settings) >= 0.5):  # past midpoint & even
                slot += 1

            lore = fill(s["description"], width=30).split("\n")
            lore = ["§7" + t for t in lore]
            lore.extend(["", "§8(Click to toggle)"])

            display_nbt: dict[str, Any] = {  # display item
                "display": {"Name": f"§r§l{s['display_name']}", "Lore": lore}
            }

            # add glint if setting is enabled
            if s["state"].lower() not in self.DISABLED_STATES:
                display_nbt["ench"] = []

            items.append(
                {
                    "slot": slot + 9,
                    "slot_data": SlotData(
                        Item.from_name(s["item"]), nbt=dumps(from_dict(display_nbt))
                    ),
                    "callback": self.toggle_state_callback,
                }
            )

            items.append(
                {  # state display glass pane, above display item
                    "slot": slot,
                    "slot_data": self.get_state_item(s["state"]),
                    "callback": self.toggle_state_callback,
                }
            )

            # save what setting is associated with this slot
            self.setting_slots[slot] = list(self.subsettings)[i]
            self.setting_slots[slot + 9] = list(self.subsettings)[i]

        return items

    def toggle_state_callback(
        self,
        window: Window,
        slot: int,
        button: int,
        action_num: int,
        mode: int,
        clicked_item: SlotData,
    ):
        try:
            setting: str = self.setting_slots[slot + 1]
        except KeyError:
            raise KeyError(
                f"Slot {slot + 1} has no associated setting.\nSettings: {self.setting_slots}"
            )
        s_path: str = self.subsetting_path + "." + setting
        prev_state, next_state = self.settings.toggle_setting_by_path(s_path)
        self.clear()
        self.build()

        s_raw = self.settings.get_setting_by_path(s_path)
        s_display = s_raw["display_name"]
        prev_color = s_raw["states"][prev_state]
        next_color = s_raw["states"][next_state]
        msg = self.get_setting_toggle_msg(
            s_display, prev_state, next_state, prev_color, next_color
        )

        self.proxy.client.chat(msg)


# Mode | Button | Slot   | Trigger
# -----|--------|--------|------------------------------------------------------------
# 0    | 0      | Normal | Left mouse click
# 0    | 1      | Normal | Right mouse click
# 1    | 0      | Normal | Shift + left mouse click
# 1    | 1      | Normal | Shift + right mouse click (identical behavior)
# 2    | 0      | Normal | Number key 1
# 2    | 1      | Normal | Number key 2
# 2    | 2      | Normal | Number key 3
# ...  | ...    | ...    | ...
# 2    | 8      | Normal | Number key 9
# 3    | 2      | Normal | Middle click
# 4    | 0      | Normal*| Drop key (Q) (* Clicked item is different, see above)
# 4    | 1      | Normal*| Ctrl + Drop key (Ctrl-Q) (drops full stack)
# 4    | 0      | -999   | Left click outside inventory holding nothing (no-op)
# 4    | 1      | -999   | Right click outside inventory holding nothing (no-op)
# 5    | 0      | -999   | Starting left mouse drag (or middle mouse)
# 5    | 4      | -999   | Starting right mouse drag
# 5    | 1      | Normal | Add slot for left-mouse drag
# 5    | 5      | Normal | Add slot for right-mouse drag
# 5    | 2      | -999   | Ending left mouse drag
# 5    | 6      | -999   | Ending right mouse drag
# 6    | 0      | Normal | Double click

Triggers = Literal[
    "left_click",
    "right_click",
    "shift_left_click",
    "shift_right_click",
    "number_key_1",
    "number_key_2",
    "number_key_3",
    "number_key_4",
    "number_key_5",
    "number_key_6",
    "number_key_7",
    "number_key_8",
    "number_key_9",
    "middle_click",
    "drop_key",
    "ctrl_drop_key",
    "outside_left_click",
    "outside_right_click",
    "start_left_mouse_drag",
    "start_right_mouse_drag",
    "add_slot_left_mouse_drag",
    "add_slot_right_mouse_drag",
    "end_left_mouse_drag",
    "end_right_mouse_drag",
    "double_click",
]

TRIGGERS: dict[tuple[int, int, Literal[-999] | None], Triggers] = {
    (0, 0, None): "left_click",
    (0, 1, None): "right_click",
    (1, 0, None): "shift_left_click",
    (1, 1, None): "shift_right_click",
    (2, 0, None): "number_key_1",
    (2, 1, None): "number_key_2",
    (2, 2, None): "number_key_3",
    (2, 3, None): "number_key_4",
    (2, 4, None): "number_key_5",
    (2, 5, None): "number_key_6",
    (2, 6, None): "number_key_7",
    (2, 7, None): "number_key_8",
    (2, 8, None): "number_key_9",
    (3, 0, None): "middle_click",
    (4, 0, None): "drop_key",
    (4, 1, None): "ctrl_drop_key",
    (4, 0, -999): "outside_left_click",
    (4, 1, -999): "outside_right_click",
    (5, 0, -999): "start_left_mouse_drag",
    (5, 4, -999): "start_right_mouse_drag",
    (5, 1, None): "add_slot_left_mouse_drag",
    (5, 5, None): "add_slot_right_mouse_drag",
    (5, 2, -999): "end_left_mouse_drag",
    (5, 6, -999): "end_right_mouse_drag",
    (6, 0, None): "double_click",
}


def get_trigger(mode: int, button: int, slot: int) -> Triggers | None:
    if slot != -999:
        return TRIGGERS.get((mode, button, None), None)
    else:
        return TRIGGERS.get((mode, button, -999), None)
