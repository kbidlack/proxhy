import asyncio
import re
import zlib
from abc import ABC
from collections import defaultdict
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional, Self

from petty.events import PacketListener, StreamDirection
from petty.net import ClientStream, ServerStream, State, StreamReader, StreamWriter
from petty.protocol.datatypes import Buffer, VarInt

if TYPE_CHECKING:
    from petty.events import EventListenerFunction, PacketListener

type PacketListenerList[T] = list[
    tuple[Callable[[Any, T], Coroutine[Any, Any, Any]], "PacketListener"]
]


class PacketNode(ABC):
    """
    Base class for anything that handles packets on one or more streams.

    Subclasses must define whichever of these attributes they use:
        downstream: ClientStream
        upstream: ServerStream
    """

    downstream: ClientStream
    upstream: ServerStream

    _packet_listeners: dict[
        StreamDirection,
        dict[tuple[int, State], PacketListenerList[Buffer]],
    ] = {"downstream": defaultdict(list), "upstream": defaultdict(list)}
    _event_listeners: dict[str, list["EventListenerFunction"]] = defaultdict(list)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        cls._packet_listeners = {
            "downstream": defaultdict(list),
            "upstream": defaultdict(list),
        }
        cls._event_listeners = defaultdict(list)

        listeners: list[tuple[Callable, PacketListener | str]] = []

        for base in reversed(cls.__mro__):
            for item in vars(base).values():
                meta = getattr(item, "_listener_meta", None)
                if meta is not None:
                    listeners.append((item, meta))

        for func, meta in listeners:
            if isinstance(meta, PacketListener):
                direction: StreamDirection = meta.source
                cls._packet_listeners[direction][meta.packet_id, meta.state].append(
                    (func, meta)
                )
            else:
                cls._event_listeners[meta].append(func)

    def _setup_node(self):
        self.state = State.HANDSHAKING
        self.closed = asyncio.Event()
        self._should_stop = False
        self._tasks: set[asyncio.Task] = set()
        self.handle_downstream_task: Optional[asyncio.Task] = None
        self.handle_upstream_task: Optional[asyncio.Task] = None

    @property
    def open(self) -> bool:
        return not self.closed.is_set()

    def initialize_plugins(self):
        for name in dir(self):
            if callable(func := getattr(self, name, None)) and name.startswith("_init"):
                func()

    def create_task(self, coro: Coroutine) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _handle_stream(
        self,
        stream: ClientStream | ServerStream,
        direction: StreamDirection,
        forward_to: Callable[[], ClientStream | ServerStream | None],
    ):
        data = b""
        while not self._should_stop and (
            packet_length := await VarInt.unpack_stream(stream)
        ):
            while len(data) < packet_length:
                data += await stream.read(packet_length - len(data))

            buff = Buffer(data)

            if stream.compression:
                data_length = buff.unpack(VarInt)
                if data_length >= stream.compression_threshold:
                    data = zlib.decompress(buff.read())
                    buff = Buffer(data)

            packet_id = buff.unpack(VarInt)
            packet_data = buff.read()

            results = self._packet_listeners[direction][(packet_id, self.state)]
            for handler, meta in results:
                if meta.blocking:
                    await handler(self, Buffer(packet_data))
                else:
                    self.create_task(handler(self, Buffer(packet_data)))

            sink = forward_to()
            if sink is not None and not any(r[1].consume for r in results):
                sink.send_packet(packet_id, packet_data)

            data = b""

            if self._should_stop:
                break

        if not self._should_stop:
            await self.close()

    async def handle_downstream(self):
        await self._handle_stream(
            self.downstream,
            "downstream",
            forward_to=lambda: getattr(self, "upstream", None),
        )

    async def handle_upstream(self):
        await self._handle_stream(
            self.upstream,
            "upstream",
            forward_to=lambda: getattr(self, "downstream", None),
        )

    async def emit(self, event: str, data: Any = None):
        results = []
        for e in self._event_listeners:
            if (match := re.fullmatch(e, event)) is not None:
                for handler in self._event_listeners[e]:
                    results.append(await handler(self, match, deepcopy(data)))
        return results

    async def close(self, reason="", force=False):
        if self.closed.is_set():
            return

        if force:
            try:
                await asyncio.wait_for(self.emit("close", reason), timeout=0.5)
            except asyncio.TimeoutError:
                pass
        else:
            await self.emit("close", reason)

        for task in (self.handle_downstream_task, self.handle_upstream_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        current = asyncio.current_task()
        tasks = {t for t in self._tasks if t is not current}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

        for attr in ("upstream", "downstream"):
            try:
                getattr(self, attr).close()
            except AttributeError:
                pass

        self.closed.set()


class Proxy(PacketNode):
    downstream: ClientStream
    upstream: ServerStream

    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        connect_host: tuple[str, int] = ("localhost", 25565),
        autostart: bool = True,
    ):
        self._setup_node()
        self._next: Optional[Self] = None
        self.CONNECT_HOST = connect_host
        self.downstream = ClientStream(reader, writer)
        self.initialize_plugins()

        if autostart:
            self.handle_downstream_task = asyncio.create_task(self.handle_downstream())

    async def run(self) -> Optional[Proxy]:
        self.handle_downstream_task = asyncio.create_task(self.handle_downstream())
        try:
            await self.handle_downstream_task
        except asyncio.CancelledError:
            pass
        return self._next

    async def transfer_to(self, new_proxy: Self) -> None:
        if self.closed.is_set():
            raise RuntimeError("Tried to transfer on a closed proxy")

        new_proxy.downstream.compression = self.downstream.compression
        new_proxy.downstream.compression_threshold = (
            self.downstream.compression_threshold
        )

        await self.emit("close", "transfer")

        try:
            self.upstream.close()
        except AttributeError:
            pass

        self._next = new_proxy
        self._should_stop = True
        self.closed.set()


class Server(PacketNode):
    """Outbound-only connection to a server"""

    upstream: ServerStream

    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        autostart: bool = True,
    ):
        self._setup_node()
        self.upstream = ServerStream(reader, writer)
        self.initialize_plugins()

        if autostart:
            self.handle_upstream_task = asyncio.create_task(self.handle_upstream())


class Client(PacketNode):
    """Inbound-only connection from a client"""

    downstream: ClientStream

    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        autostart: bool = True,
    ):
        self._setup_node()
        self.downstream = ClientStream(reader, writer)
        self.initialize_plugins()

        if autostart:
            self.handle_downstream_task = asyncio.create_task(self.handle_downstream())
