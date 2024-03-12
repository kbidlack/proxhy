import asyncio
import json
import zlib
from asyncio import StreamReader, StreamWriter
from enum import Enum
from secrets import token_bytes

import aiohttp

from .datatypes import Buffer, ByteArray, Long, String, UnsignedShort, VarInt
from .encryption import Stream, generate_verification_hash, pkcs1_v15_padded_rsa_encrypt

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


class Proxy:
    """
    represents a proxied connection to a client and corresponding connection to server
    """

    server_list_ping = {  # placeholder
        "version": {"name": "1.8.9", "protocol": 47},
        "players": {"max": 0, "online": 0},
        "description": {"text": "No MOTD set!"},
    }

    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
    ):
        self.client_stream = Stream(reader, writer)

        self.state = State.HANDSHAKING
        self.compression = False
        self.server_stream: Stream | None = None

        self.CONNECT_HOST = ("", 0)

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

    async def client_packet(self, *_):
        pass

    async def server_packet(self, *_):
        pass

    async def handle_client(self):
        while packet_length := await VarInt.unpack_stream(self.client_stream):
            if data := await self.client_stream.read(packet_length):
                buff = Buffer(data)
                # print(f"Client: {packet_id=}, {buff.getvalue()=}, {self.state=}")

                packet_id = buff.unpack(VarInt)
                packet_data = buff.read()

                # extra packet handling
                await self.client_packet(packet_id, Buffer(packet_data))

                # call packet handler
                result = client_listeners.get((packet_id, self.state))
                if result:
                    handler, blocking = result
                    if blocking:
                        await handler(self, Buffer(packet_data))
                    else:
                        asyncio.create_task(handler(self, Buffer(packet_data)))
                else:
                    self.send_packet(self.server_stream, packet_id, packet_data)
        await self.close()

    async def handle_server(self):
        data = b""
        while packet_length := await VarInt.unpack_stream(self.server_stream):
            while len(data) < packet_length:
                newdata = await self.server_stream.read(packet_length - len(data))
                data += newdata

            buff = Buffer(data)
            if self.compression:
                data_length = buff.unpack(VarInt)
                if data_length >= self.compression_threshold:
                    # print(buff.getvalue())
                    data = zlib.decompress(buff.read())
                    buff = Buffer(data)

            packet_id = buff.unpack(VarInt)
            packet_data = buff.read()
            # print(f"Server: {hex(packet_id)=}, {self.state=}")

            # extra packet handling
            await self.server_packet(packet_id, Buffer(packet_data))

            # call packet handler
            result = server_listeners.get((packet_id, self.state))
            if result:
                handler, blocking = result
                if blocking:
                    await handler(self, Buffer(packet_data))
                else:
                    asyncio.create_task(handler(self, Buffer(packet_data)))
            else:
                self.send_packet(self.client_stream, packet_id, packet_data)

            data = b""

        await self.close()

    async def close(self):
        if self.server_stream:
            self.server_stream.close()
        self.client_stream.close()

        del self  # idk if this does anything or not
        # on second thought probably not but whatever

    @listen_client(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self, _):
        self.send_packet(
            self.client_stream, 0x00, String.pack(json.dumps(self.server_list_ping))
        )

    @listen_client(0x01, State.STATUS, blocking=True)
    async def packet_ping_request(self, buff: Buffer):
        payload = buff.unpack(Long)
        self.send_packet(self.client_stream, 0x01, Long.pack(payload))
        # close connection
        await self.close()

    @listen_client(0x00, State.HANDSHAKING, blocking=True)
    async def packet_handshake(self, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)
        if self.state == State.LOGIN:
            reader, writer = await asyncio.open_connection(
                self.CONNECT_HOST[0], self.CONNECT_HOST[1]
            )
            self.server_stream = Stream(reader, writer)
            asyncio.create_task(self.handle_server())

            self.send_packet(
                self.server_stream,
                0x00,
                VarInt.pack(47),
                String.pack(self.CONNECT_HOST[0]),
                UnsignedShort.pack(self.CONNECT_HOST[1]),
                VarInt.pack(State.LOGIN.value),
            )

    @listen_server(0x03, State.LOGIN, blocking=True)
    async def packet_set_compression(self, buff: Buffer):
        self.compression_threshold = buff.unpack(VarInt)
        self.compression = False if self.compression_threshold == -1 else True

    @listen_server(0x01, State.LOGIN, blocking=True)
    async def packet_encryption_request(self, buff: Buffer):
        server_id = buff.unpack(String).encode("utf-8")
        public_key = buff.unpack(ByteArray)
        verify_token = buff.unpack(ByteArray)

        # generate shared secret
        secret = token_bytes(16)
        # client assumes access_token and uuid have been set
        payload = {
            "accessToken": self.access_token,
            "selectedProfile": self.uuid,
            "serverId": generate_verification_hash(server_id, secret, public_key),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://sessionserver.mojang.com/session/minecraft/join",
                json=payload,
                ssl=False,
            ) as response:
                if not response.status == 204:
                    raise Exception(
                        f"Login failed: {response.status} {await response.json()}"
                    )

        encrypted_secret = pkcs1_v15_padded_rsa_encrypt(public_key, secret)
        encrypted_verify_token = pkcs1_v15_padded_rsa_encrypt(public_key, verify_token)

        self.send_packet(
            self.server_stream,
            0x01,
            ByteArray.pack(encrypted_secret),
            ByteArray.pack(encrypted_verify_token),
        )

        # enable encryption
        self.server_stream.key = secret
        self.server_stream.key = secret

    @listen_server(0x02, State.LOGIN, blocking=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.send_packet(self.client_stream, 0x02, buff.read())
