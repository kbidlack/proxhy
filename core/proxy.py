import asyncio
import re
import zlib  # pyright: ignore[reportShadowedImports]
from collections import defaultdict
from typing import Any, Callable, Coroutine, Literal, Optional

from protocol.datatypes import Buffer, VarInt

from .events import PacketListener
from .net import Client, Server, State, StreamReader, StreamWriter

type ListenerList[T] = list[tuple[Callable[[Any, T], Coroutine[Any, Any, Any]], bool]]


class Proxy:
    server: Server

    _packet_listeners: dict[
        Literal["client", "server"],
        dict[tuple[int, State], ListenerList[Buffer]],
    ] = {"client": defaultdict(list), "server": defaultdict(list)}
    _event_listeners: dict[str, list[Callable[[Any, Any], Coroutine]]] = defaultdict(
        list
    )

    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        connect_host: tuple[str, int, str, int] = (
            "mc.hypixel.net",
            25565,
            "mc.hypixel.net",
            25565,
        ),
        autostart: bool = True,
    ):
        self.client = Client(reader, writer)

        self.state = State.HANDSHAKING
        self.open = True
        self.closed = asyncio.Event()

        self.CONNECT_HOST = connect_host

        # transfer support
        self._next_proxy: Optional[Proxy] = None
        self._should_stop = False

        self.initialize_plugins()

        if autostart:
            self.handle_client_task = asyncio.create_task(self.handle_client())

    def initialize_plugins(self):
        for name in dir(self):
            # e.g. _init_statcheck for statcheck plugin
            if callable(func := getattr(self, name)) and name.startswith("_init"):
                func()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # create new dictionaries for each subclass so that
        # packet listeners are not duplicated across subclasses
        cls._packet_listeners = {
            "client": defaultdict(list),
            "server": defaultdict(list),
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
                if meta.override:
                    cls._packet_listeners[meta.source][
                        meta.packet_id, meta.state
                    ].clear()
                cls._packet_listeners[meta.source][meta.packet_id, meta.state].append(
                    (func, meta.blocking)
                )
            else:
                cls._event_listeners[meta].append(func)

    async def run(self) -> Optional["Proxy"]:
        """
        Run the proxy until it closes or transfers to another proxy
        """
        await self.handle_client()
        return self._next_proxy

    async def transfer_to(self, new_proxy: "Proxy") -> None:
        """
        Transfer the client connection to a new proxy, the new proxy
        should be created with autostart=False.
        """
        if not self.open:
            raise RuntimeError("Tried to transfer on a closed proxy")

        # copy compression settings from old client to new client
        new_proxy.client.compression = self.client.compression
        new_proxy.client.compression_threshold = self.client.compression_threshold

        await self.emit("close", "transfer")

        self.open = False

        try:
            self.server.close()
        except AttributeError:
            pass

        self._next_proxy = new_proxy
        self._should_stop = True

        self.closed.set()

    async def handle_client(self):
        while not self._should_stop and (
            packet_length := await VarInt.unpack_stream(self.client)
        ):
            if data := await self.client.read(packet_length):
                buff = Buffer(data)

                packet_id = buff.unpack(VarInt)
                packet_data = buff.read()

                # call packet handler
                results = self._packet_listeners["client"][(packet_id, self.state)]
                for handler, blocking in results:
                    if blocking:
                        await handler(self, Buffer(packet_data))
                    else:
                        asyncio.create_task(handler(self, Buffer(packet_data)))
                if not results:
                    self.server.send_packet(packet_id, packet_data)

                # check if we should stop after processing this packet
                if self._should_stop:
                    break

        # only close if we're not transferring
        if not self._should_stop:
            await self.close()

    async def handle_server(self):
        data = b""
        while not self._should_stop and (
            packet_length := await VarInt.unpack_stream(self.server)
        ):
            while len(data) < packet_length:
                newdata = await self.server.read(packet_length - len(data))
                data += newdata

            buff = Buffer(data)
            if self.server.compression:
                data_length = buff.unpack(VarInt)
                if data_length >= self.server.compression_threshold:
                    data = zlib.decompress(buff.read())
                    buff = Buffer(data)

            packet_id = buff.unpack(VarInt)
            packet_data = buff.read()

            # call packet handler
            results = self._packet_listeners["server"][(packet_id, self.state)]
            for handler, blocking in results:
                if blocking:
                    await handler(self, Buffer(packet_data))
                else:
                    asyncio.create_task(handler(self, Buffer(packet_data)))
            if not results:
                self.client.send_packet(packet_id, packet_data)

            data = b""

            # check if we should stop after processing this packet
            if self._should_stop:
                break

        # only close if we're not transferring
        if not self._should_stop:
            await self.close()

    async def emit(self, event: str, data: Any = None):
        results = []

        for e in self._event_listeners:
            if re.fullmatch(e, event):
                for handler in self._event_listeners[e]:
                    if isinstance(data, Buffer):
                        # emit reuses data across handlers
                        # but we don't want buffers to be messed up
                        # by one handler, and then sent to another
                        data = data.clone()
                    results.append(await handler(self, data))

        return results

    async def close(self, reason=""):
        if not self.open:
            return

        await self.emit("close", reason)

        self.open = False

        try:
            self.server.close()
        except AttributeError:
            pass

        self.client.close()

        self.closed.set()
