import time
from typing import TYPE_CHECKING, Hashable

from petty.events import listen_client, subscribe

# from petty.events import listen_server
from petty.protocol.datatypes import Buffer, VarInt

from gamestate.state import Entity, GameState

if TYPE_CHECKING:
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


class GameStatePlugin:
    gamestate: GameState

    def _init_0_gamestate(self: ProxhyPlugin):  # since other plugins require we put 0
        self.gamestate = GameState()
        self.in_combat_with = ExpiringSet(ttl=5)

        _original_send_packet = self.downstream.send_packet

        def _hooked_cb_send_packet(packet_id: int, *data: bytes) -> None:
            self._handle_clientbound_packet(packet_id, Buffer(b"".join(data)))
            _original_send_packet(packet_id, *data)

        self.downstream.send_packet = _hooked_cb_send_packet  # type: ignore

    @subscribe("login_success")
    async def _gamestate_event_login_success(self: ProxhyPlugin, _, _data):
        _original_send_packet = self.upstream.send_packet

        def _hooked_sb_send_packet(packet_id: int, *data: bytes) -> None:
            self._handle_serverbound_packet(packet_id, Buffer(b"".join(data)))
            _original_send_packet(packet_id, *data)

        self.upstream.send_packet = _hooked_sb_send_packet  # type: ignore

    def _handle_clientbound_packet(self: ProxhyPlugin, packet_id: int, buff: Buffer):
        self.gamestate.update_clientbound(packet_id, buff.getvalue())
        self.create_task(self.emit("cb_gamestate_update", (packet_id, buff.getvalue())))

    def _handle_serverbound_packet(self: ProxhyPlugin, packet_id: int, buff: Buffer):
        self.gamestate.update_serverbound(packet_id, buff.getvalue())
        self.create_task(self.emit("sb_gamestate_update", (packet_id, buff.getvalue())))

    @listen_client(0x02, blocking=True)
    async def _packet_use_entity(self: ProxhyPlugin, buff: Buffer):
        self.upstream.send_packet(0x02, buff.getvalue())

        target = buff.unpack(VarInt)
        type_ = buff.unpack(VarInt)
        if type_ == 1:
            self.in_combat_with.add(target)

    @property
    def ein_combat_with(self: ProxhyPlugin) -> list[Entity]:
        entities = [self.gamestate.get_entity(e) for e in self.in_combat_with.values()]
        return [e for e in entities if e is not None]


# # construct cb listeners
# for packet_id in range(0x49 + 1):

#     def _make_cb_handler(packet_id: int):
#         async def _handler(self: ProxhyPlugin, buff: Buffer):
#             self._handle_clientbound_packet(packet_id, buff)

#         return _handler

#     setattr(
#         GameStatePlugin,
#         f"_handle_cb_{packet_id}",
#         listen_server(packet_id, blocking=True, consume=False)(
#             _make_cb_handler(packet_id)
#         ),
#     )

# # construct sb listeners
# for packet_id in range(0x19 + 1):

#     def _make_sb_handler(packet_id: int):
#         async def _handler(self: ProxhyPlugin, buff: Buffer):
#             self._handle_serverbound_packet(packet_id, buff)

#         return _handler

#     setattr(
#         GameStatePlugin,
#         f"_handle_sb_{packet_id}",
#         listen_client(packet_id, blocking=True, consume=False)(
#             _make_sb_handler(packet_id)
#         ),
#     )
