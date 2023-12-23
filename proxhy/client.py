import asyncio
import zlib
from asyncio import StreamReader, StreamWriter
from enum import Enum

from datatypes import BuffIO, VarInt
from encryption import Stream

client_listeners = {}
server_listeners = {}


class State(Enum):
    HANDSHAKING = 0
    STATUS = 1
    LOGIN = 2
    PLAY = 3


def listen_client(packet_id: int, state: State = State.PLAY, blocking=False):
    def wrapper(func):
        client_listeners.update({(packet_id, state): (func, blocking)})

        async def inner(*args, **kwargs):
            return await func(*args, **kwargs)

        return inner

    return wrapper


def listen_server(packet_id: int, state: State = State.PLAY, blocking=False):
    def wrapper(func):
        server_listeners.update({(packet_id, state): (func, blocking)})

        async def inner(*args, **kwargs):
            return await func(*args, **kwargs)

        return inner

    return wrapper


class Client:
    """represents a connection to a client and corresponding connection to server"""

    def __init__(
        self, reader: StreamReader, writer: StreamWriter, access_token: str, uuid: str
    ):
        self.client_stream = Stream(reader, writer)
        self.access_token = access_token
        self.uuid = uuid

        self.state = State.HANDSHAKING
        self.compression = False
        self.server_stream: Stream | None = None

        asyncio.create_task(self.handle_client())

    def send_packet(self, stream: Stream, id: int, *data: bytes) -> None:
        packet = VarInt.pack(id) + b"".join(data)
        packet_length = VarInt.pack(len(packet))

        if self.compression and stream is self.server_stream:
            if len(packet) >= self.compression_threshold:
                compressed_packet = zlib.compress(packet)
                data_length = packet_length
                packet = data_length + compressed_packet
                packet_length = VarInt.pack(len(packet))
            else:
                packet = VarInt.pack(0) + VarInt.pack(id) + b"".join(data)
                packet_length = VarInt.pack(len(packet))

        stream.write(packet_length + packet)

    async def handle_client(self):
        while packet_length := await VarInt.unpack_stream(self.client_stream):
            if data := await self.client_stream.read(packet_length):
                buff = BuffIO(data)
                packet_id: int = buff.unpack(VarInt)

                # print(f"Client: {packet_id=}, {buff.getvalue()=}, {self.state=}")

                # call packet handler
                result = client_listeners.get((packet_id, self.state))
                if result:
                    handler, blocking = result
                    if blocking:
                        await handler(self, BuffIO(buff.read()))
                    else:
                        asyncio.create_task(handler(self, BuffIO(buff.read())))
                else:
                    self.send_packet(self.server_stream, packet_id, buff.read())
        await self.close()

    async def handle_server(self):
        data = b""
        while packet_length := await VarInt.unpack_stream(self.server_stream):
            while len(data) < packet_length:
                newdata = await self.server_stream.read(packet_length - len(data))
                data += newdata

            buff = BuffIO(data)
            if self.compression:
                data_length: int = buff.unpack(VarInt)
                if data_length >= self.compression_threshold:
                    # print(buff.getvalue())
                    data = zlib.decompress(buff.read())
                    buff = BuffIO(data)

            packet_id: int = buff.unpack(VarInt)
            # print(f"Server: {packet_id=}, {buff.getvalue()=}, {self.state=}")

            # call packet handler
            result = server_listeners.get((packet_id, self.state))
            if result:
                handler, blocking = result
                if blocking:
                    await handler(self, BuffIO(buff.read()))
                else:
                    asyncio.create_task(handler(self, BuffIO(buff.read())))
            else:
                self.send_packet(self.client_stream, packet_id, buff.read())

            data = b""

        await self.close()
