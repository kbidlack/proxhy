import asyncio
import re
import zlib
from asyncio import StreamReader, StreamWriter
from collections import defaultdict
from typing import Any, Callable, Coroutine, Literal

from protocol.datatypes import Buffer, VarInt

from .events import PacketListener
from .net import (
    Client,
    Server,
    State,
)

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
    ):
        self.client = Client(reader, writer)

        self.state = State.HANDSHAKING
        self.open = True

        self.CONNECT_HOST = connect_host

        self.initialize_plugins()

        asyncio.create_task(self.handle_client())

    def initialize_plugins(self):
        for name in dir(self):
            # e.g. _init_statcheck for statcheck plugin
            if callable(func := getattr(self, name)) and name.startswith("_init"):
                func()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        items = {}
        for base in reversed(cls.__mro__):
            items.update(vars(base))

        listeners: list[tuple[Callable, PacketListener | str]] = [
            (item, meta)
            for (_, item) in items.items()
            if (meta := getattr(item, "_listener_meta", None)) is not None
        ]

        for func, meta in filter(None, listeners):
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

    async def handle_client(self):
        while packet_length := await VarInt.unpack_stream(self.client):
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
                    try:
                        self.server.send_packet(packet_id, packet_data)
                    except Exception:
                        print(packet_id, self.state)
                        print(self._packet_listeners)

        await self.close()

    async def handle_server(self):
        data = b""
        while packet_length := await VarInt.unpack_stream(self.server):
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

        await self.close()

    async def emit(self, event: str, data: Any = None):
        results = []

        for e in self._event_listeners:
            if re.fullmatch(e, event):
                for handler in self._event_listeners[e]:
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
