import asyncio
import inspect
from types import NoneType, NotImplementedType
from typing import (
    Callable,
)

from core.events import listen_client
from protocol.datatypes import (
    Buffer,
    Byte,
    Short,
    Slot,
    SlotData,
    UnsignedByte,
)
from proxhy.plugin import ProxhyPlugin

from ._window import Window, get_trigger


class WindowPluginState:
    windows: dict[int, "Window"]


class WindowPlugin(ProxhyPlugin):
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
            callback = self.windows[window_id].data[slot][1]
            if not isinstance(callback, (NotImplementedType, NoneType)):
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
                self.client.send_packet(*self.gamestate._build_player_inventory())
                self.client.send_packet(
                    0x2F, Byte.pack(-1), Short.pack(-1), Slot.pack(SlotData())
                )
        else:
            self.server.send_packet(0x0E, buff.getvalue())


__all__ = (
    # ./_window.py
    "Window",
    "WindowPlugin",
    # .
    "get_trigger",
)
