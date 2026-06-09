import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from petty.protocol.datatypes import Buffer

from .net import State

if TYPE_CHECKING:
    from petty.endpoints import Proxy

    T = TypeVar("T", bound=Proxy)


type ListenerFunction[T] = Callable[[T, Buffer], Awaitable[Any]]
type DecoratorType[T] = Callable[[ListenerFunction[T]], ListenerFunction[T]]
type EventListenerFunction = Callable[[Any, re.Match[str], Any], Awaitable[Any]]
type EventDecoratorType = Callable[[EventListenerFunction], EventListenerFunction]

type StreamDirection = Literal["downstream", "upstream"]


@dataclass
class PacketListener:
    source: StreamDirection
    packet_id: int
    state: State = State.PLAY
    blocking: bool = False
    consume: bool = True


def listen_client(
    packet_id: int, state: State = State.PLAY, blocking=False, consume=True
) -> DecoratorType[T]:
    return _listen("downstream", packet_id, state, blocking, consume)


def listen_server(
    packet_id: int, state: State = State.PLAY, blocking=False, consume=True
) -> DecoratorType[T]:
    return _listen("upstream", packet_id, state, blocking, consume)


def _listen(
    source: StreamDirection,
    packet_id: int,
    state: State = State.PLAY,
    blocking=False,
    consume=True,
) -> DecoratorType[T]:
    def wrapper(func: ListenerFunction[T]) -> ListenerFunction[T]:
        listener_meta = PacketListener(source, packet_id, state, blocking, consume)
        func._listener_meta = listener_meta  # type: ignore[attr-defined]

        return func

    return wrapper


def subscribe(event: str) -> EventDecoratorType:
    def wrapper(func: EventListenerFunction) -> EventListenerFunction:
        func._listener_meta = event  # type: ignore[attr-defined]

        return func

    return wrapper
