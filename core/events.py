from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from protocol.datatypes import Buffer

from .net import State


@dataclass
class PacketListener:
    source: Literal["client", "server"]
    packet_id: int
    state: State = State.PLAY
    blocking: bool = False
    override: bool = False


def listen_client(
    packet_id: int,
    state: State = State.PLAY,
    blocking=False,
    override=False,
):
    return _listen("client", packet_id, state, blocking, override)


def listen_server(
    packet_id: int,
    state: State = State.PLAY,
    blocking=False,
    override=False,
):
    return _listen("server", packet_id, state, blocking, override)


def _listen(
    source: Literal["client", "server"],
    packet_id: int,
    state: State = State.PLAY,
    blocking=False,
    override=False,
):
    def wrapper(func: Callable[[Any, Buffer], Awaitable[Any]]):
        listener_meta = PacketListener(source, packet_id, state, blocking, override)
        setattr(func, "_listener_meta", listener_meta)

        return func

    return wrapper


def subscribe(event: str):
    def wrapper(func: Callable[[Any, Any], Awaitable[Any]]):
        setattr(func, "_listener_meta", event)

        return func

    return wrapper
