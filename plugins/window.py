from __future__ import annotations

import asyncio
import inspect
import random
from copy import deepcopy
from functools import wraps
from typing import Awaitable, Callable, Literal, Optional, SupportsIndex, overload

from core.events import listen_client
from core.plugin import Plugin
from protocol.datatypes import (
    Buffer,
    Byte,
    Chat,
    Int,
    Short,
    Slot,
    SlotData,
    String,
    UnsignedByte,
)


class WindowPlugin(Plugin):
    def _init_window(self):
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
