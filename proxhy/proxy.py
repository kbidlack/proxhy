import asyncio
import json
import zlib
from asyncio import StreamReader, StreamWriter
from enum import Enum
from secrets import token_bytes

import aiohttp

from .datatypes import Buffer, ByteArray, String, UnsignedShort, VarInt
from .net import (
    Client,
    Server,
    generate_verification_hash,
    pkcs1_v15_padded_rsa_encrypt,
)

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

    server_stream: Server

    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
    ):
        self.client = Client(reader, writer)

        self.state = State.HANDSHAKING
        self.open = True

        self.CONNECT_HOST = ("", 0)

        self.username = ""

        self.access_token = ""
        self.uuid = ""

        asyncio.create_task(self.handle_client())

    async def handle_client(self):
        while packet_length := await VarInt.unpack_stream(self.client):
            if data := await self.client.read(packet_length):
                buff = Buffer(data)

                packet_id = buff.unpack(VarInt)
                packet_data = buff.read()

                # print(f"Client: {packet_id=}, {buff.getvalue()=}, {self.state=}")

                # call packet handler
                result = client_listeners.get((packet_id, self.state))
                if result:
                    handler, blocking = result
                    if blocking:
                        await handler(self, Buffer(packet_data))
                    else:
                        asyncio.create_task(handler(self, Buffer(packet_data)))
                else:
                    self.server.send_packet(packet_id, packet_data)

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
                    # print(buff.getvalue())
                    data = zlib.decompress(buff.read())
                    buff = Buffer(data)

            packet_id = buff.unpack(VarInt)
            packet_data = buff.read()
            # print(f"Server: {hex(packet_id)=}, {self.state=}")

            # call packet handler
            result = server_listeners.get((packet_id, self.state))
            if result:
                handler, blocking = result
                if blocking:
                    await handler(self, Buffer(packet_data))
                else:
                    asyncio.create_task(handler(self, Buffer(packet_data)))
            else:
                self.client.send_packet(packet_id, packet_data)

            data = b""

        await self.close()

    async def close(self):
        if not self.open:
            return

        self.open = False
        try:
            self.server.close()
        except AttributeError:
            pass
        self.client.close()

    @listen_client(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self, _):
        self.client.send_packet(0x00, String(json.dumps(self.server_list_ping)))

    @listen_client(0x01, State.STATUS, blocking=True)
    async def packet_ping_request(self, buff: Buffer):
        self.client.send_packet(0x01, buff.getvalue())
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
            self.server = Server(reader, writer)

            asyncio.create_task(self.handle_server())

            self.server.send_packet(
                0x00,
                VarInt(47),
                String(self.CONNECT_HOST[0]),
                UnsignedShort(self.CONNECT_HOST[1]),
                VarInt(State.LOGIN.value),
            )

    @listen_server(0x03, State.LOGIN, blocking=True)
    async def packet_set_compression(self, buff: Buffer):
        self.server.compression_threshold = buff.unpack(VarInt)
        self.server.compression = (
            False if self.server.compression_threshold == -1 else True
        )

    @listen_server(0x01, State.LOGIN, blocking=True)
    async def packet_encryption_request(self, buff: Buffer):
        server_id = buff.unpack(String).encode("utf-8")
        public_key = buff.unpack(ByteArray)
        verify_token = buff.unpack(ByteArray)

        # generate shared secret
        secret = token_bytes(16)

        if not (self.access_token or self.uuid):
            raise ValueError("Access token or UUID not set")

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

        self.server.send_packet(
            0x01,
            ByteArray(encrypted_secret),
            ByteArray(encrypted_verify_token),
        )

        # enable encryption
        self.server.key = secret
        self.server.key = secret

    @listen_server(0x02, State.LOGIN, blocking=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.client.send_packet(0x02, buff.read())
