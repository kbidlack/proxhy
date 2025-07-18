from __future__ import annotations

import random
from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING, Optional

from .datatypes import Byte, Chat, Int, Short, Slot, SlotData, String, UnsignedByte

if TYPE_CHECKING:
    from .proxhy import Proxhy


@dataclass
class Team:
    name: str
    display_name: str
    prefix: str
    suffix: str
    friendly_fire: int
    name_tag_visibility: str
    color: int
    players: set[str]


class Teams(list[Team]):
    def get(self, key) -> Team:
        return next(team for team in self if team.name == key)

    def delete(self, key):
        team = self.get(key)
        if team:
            self.remove(team)


@dataclass
class Game:
    server: str = ""
    gametype: str = ""
    mode: str = ""
    map: str = ""
    lobbyname: str = ""

    def __setattr__(self, name: str, value) -> None:
        if isinstance(value, str):
            super().__setattr__(name.casefold(), value.casefold())
        else:
            super().__setattr__(name, value)

    def update(self, data: dict):
        # reset
        self.server = ""
        self.gametype = ""
        self.mode = ""
        self.map = ""
        self.lobbyname = ""

        for key, value in data.items():
            setattr(self, key, value)


@dataclass
class Nick:
    name: str
    uuid: str = field(init=False)


def ensure_open(open=True):
    def decorator(func):
        @wraps(func)
        def wrapper(self: Window, *args, **kwargs):
            if self._open == open:
                return func(self, *args, **kwargs)
            return lambda: None

        return wrapper

    return decorator


class Window:
    def __init__(
        self,
        proxhy: Proxhy,
        window_title: str = "Chest",
        window_type: str = "minecraft:chest",
        num_slots: int = 27,
        entity_id: Optional[int] = None,
    ):
        self.proxhy = proxhy
        self.window_title = window_title
        self.window_type = window_type
        self.num_slots = num_slots
        self.entity_id = entity_id

        # initialize with empty slots
        self.data = [SlotData() for _ in range(num_slots)]

        self.window_id = random.randint(101, 127)  # (notchian) server uses 1-100

        # TODO: if we have too many windows there are collisions? but no way...
        proxhy.windows.update({self.window_id: self})

        self._open = False

    def clone(self) -> Window:
        return deepcopy(self)

    def set_slot(self, slot: int, slot_data: SlotData):
        """Set a slot in the window."""
        if slot < 0 or slot >= self.num_slots:
            raise IndexError(
                f"Slot index {slot} out of range for window with {self.num_slots} slots."
            )

        self.data[slot] = slot_data

        if self._open:
            self.proxhy.client.send_packet(
                0x2F, Byte.pack(self.window_id), Short.pack(slot), Slot.pack(slot_data)
            )

    @ensure_open(open=False)
    def open(self):
        self._open = True

        self.proxhy.client.send_packet(
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
        self.proxhy.client.send_packet(0x2E, UnsignedByte.pack(self.window_id))
        del self.proxhy.windows[self.window_id]

    @ensure_open()
    def update(self):
        self.proxhy.client.send_packet(
            0x30,
            UnsignedByte.pack(self.window_id),
            Short.pack(self.num_slots),
            b"".join(Slot.pack(sd) for sd in self.data),
        )
