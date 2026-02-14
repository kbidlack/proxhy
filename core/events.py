import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, TypeVar

from protocol.datatypes import Buffer

from .net import State

if TYPE_CHECKING:
    from .plugin import Plugin
    from .proxy import Proxy

T = TypeVar("T", bound="Plugin | Proxy")

type ListenerFunction[T] = Callable[[T, Buffer], Awaitable[Any]]
type DecoratorType[T] = Callable[[ListenerFunction[T]], ListenerFunction[T]]
type EventListenerFunction = Callable[[Any, re.Match[str], Any], Awaitable[Any]]
type EventDecoratorType = Callable[[EventListenerFunction], EventListenerFunction]


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
) -> DecoratorType[T]:
    return _listen("client", packet_id, state, blocking, override)


def listen_server(
    packet_id: int,
    state: State = State.PLAY,
    blocking=False,
    override=False,
) -> DecoratorType[T]:
    return _listen("server", packet_id, state, blocking, override)


def _listen(
    source: Literal["client", "server"],
    packet_id: int,
    state: State = State.PLAY,
    blocking=False,
    override=False,
) -> DecoratorType[T]:
    def wrapper(func: ListenerFunction[T]) -> ListenerFunction[T]:
        listener_meta = PacketListener(source, packet_id, state, blocking, override)
        setattr(func, "_listener_meta", listener_meta)

        return func

    return wrapper


def subscribe(event: str) -> EventDecoratorType:
    def wrapper(func: EventListenerFunction) -> EventListenerFunction:
        setattr(func, "_listener_meta", event)

        return func

    return wrapper
