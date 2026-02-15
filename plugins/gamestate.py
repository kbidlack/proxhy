import time
from typing import Hashable

from core.events import listen_client, subscribe
from protocol.datatypes import Buffer, VarInt
from proxhy.gamestate import Entity, GameState
from proxhy.plugin import ProxhyPlugin


class ExpiringSet[T: Hashable]:
    def __init__(self, ttl: float):
        self.ttl = ttl
        self._data: dict[T, float] = {}

    def add(self, value: T):
        now = time.monotonic()
        self._data[value] = now + self.ttl

    def __contains__(self, value: int) -> bool:
        self._cleanup()
        return value in self._data

    def _cleanup(self):
        now = time.monotonic()
        expired = [k for k, t in self._data.items() if t <= now]
        for k in expired:
            del self._data[k]

    def values(self):
        self._cleanup()
        return set(self._data)

    def __iter__(self):
        return iter(self._data)


class GameStatePluginState:
    gamestate: GameState
    in_combat_with: ExpiringSet[int]  # set[eid]
    ein_combat_with: list[Entity]


class GameStatePlugin(ProxhyPlugin):
    def _init_0_gamestate(self):  # since other plugins require we put 0
        self.gamestate = GameState()
        self.in_combat_with = ExpiringSet(ttl=5)
        self.create_task(self._update_clientbound())

    @subscribe("login_success")
    async def _gamestate_event_login_success(self, _match, _data):
        self.create_task(self._update_serverbound())

    async def _update_clientbound(self):
        while self.open:
            id, *data = await self.client.pqueue.get()
            self.gamestate.update(id, b"".join(data))
            await self.emit(
                "cb_gamestate_update", (id, *data)
            )  # TODO: avoid unpacking? by passing tuple[bytes] everywhere

    async def _update_serverbound(self):
        while self.open:
            id, *data = await self.server.pqueue.get()
            self.gamestate.update_serverbound(id, b"".join(data))
            await self.emit("sb_gamestate_update", (id, *data))

    @listen_client(0x02, blocking=True)
    async def _packet_use_entity(self, buff: Buffer):
        self.server.send_packet(0x02, buff.getvalue())

        target = buff.unpack(VarInt)
        type_ = buff.unpack(VarInt)
        if type_ == 1:
            self.in_combat_with.add(target)

    @property
    def ein_combat_with(self) -> list[Entity]:
        entities = [self.gamestate.get_entity(e) for e in self.in_combat_with.values()]

        return [e for e in entities if e is not None]
