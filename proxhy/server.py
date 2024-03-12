# server; right now mostly for spectating feature
from __future__ import annotations

import asyncio
import json
import random
import uuid
import zlib
from asyncio import StreamReader, StreamWriter
from enum import Enum
from secrets import token_bytes

import aiohttp
from datatypes import (
    Boolean,
    Buffer,
    Byte,
    ByteArray,
    Chat,
    Double,
    Float,
    Int,
    Long,
    Position,
    String,
    UnsignedByte,
    UnsignedShort,
    VarInt,
)
from encryption import (
    Stream,
    generate_rsa_keypair,
    generate_verification_hash,
    pkcs1_v15_padded_rsa_decrypt,
)
from models import Pos

listeners = {}


class State(Enum):
    HANDSHAKING = 0
    STATUS = 1
    LOGIN = 2
    PLAY = 3


def listen(packet_id: int, state: State = State.PLAY, blocking=False):
    def wrapper(func):
        listeners.update({(packet_id, state): (func, blocking)})

        async def inner(*args, **kwargs):
            return await func(*args, **kwargs)

        return inner

    return wrapper


class Client:
    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        server: Server,
    ):
        self.stream = Stream(reader, writer)
        self.server = server
        self.address = writer.get_extra_info("peername")

        self.state = State.HANDSHAKING
        self.username = ""

        self.compression = False
        self.compression_threshold = -1

    def send_packet(self, id: int, *data: bytes) -> None:
        packet = VarInt.pack(id) + b"".join(data)
        packet_length = VarInt.pack(len(packet))
        if self.compression:
            if len(packet) >= self.compression_threshold:
                compressed_packet = zlib.compress(packet)
                data_length = packet_length
                packet = data_length + compressed_packet
                packet_length = VarInt.pack(len(packet))
            else:
                packet = VarInt.pack(0) + VarInt.pack(id) + b"".join(data)
                packet_length = VarInt.pack(len(packet))

        self.stream.write(packet_length + packet)

    async def close(self):
        self.stream.close()

    async def handle(self):
        while packet_length := await VarInt.unpack_stream(self.stream):
            if data := await self.stream.read(packet_length):
                buff = Buffer(data)
                packet_id = buff.unpack(VarInt)

                # call packet handler
                if result := listeners.get((packet_id, self.state)):
                    handler, blocking = result
                    if blocking:
                        await handler(self, Buffer(buff.read()))
                    else:
                        asyncio.create_task(handler(self, Buffer(buff.read())))
                # else:
                #     self.send_packet(self.server_stream, packet_id, buff.read())
        await self.close()

    @listen(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self, _):
        online = len([c for c in self.server.clients if c.state == State.PLAY])
        server_list_ping = {
            "version": {"name": "1.8.9", "protocol": 47},
            "players": {
                "max": 3,
                "online": online,
            },
            "description": {"text": "Spectate"},
        }
        self.send_packet(0x00, String.pack(json.dumps(server_list_ping)))

    @listen(0x01, State.STATUS, blocking=True)
    async def packet_ping_request(self, buff: Buffer):
        payload = buff.unpack(Long)
        self.send_packet(0x01, Long.pack(payload))
        # close connection
        await self.close()

    @listen(0x00, State.LOGIN, blocking=True)
    async def packet_login_start(self, buff: Buffer):
        self.username = buff.unpack(String)

    @listen(0x00, State.HANDSHAKING, blocking=True)
    async def packet_handshake(self, buff: Buffer):
        # encryption request
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)
        if self.state == State.LOGIN:  # and self.address[0] != "127.0.0.1":
            self.private_key, self.public_key = generate_rsa_keypair()
            self.verify_token = token_bytes(4)

            # encryption request
            self.send_packet(
                0x01,
                String.pack(""),
                ByteArray.pack(self.public_key),
                ByteArray.pack(self.verify_token),
            )
        elif self.state == State.LOGIN and self.address[0] == "127.0.0.1":
            self.uuid = uuid.uuid4()
            await self.join()

    @listen(0x01, State.LOGIN, blocking=True)
    async def packet_encryption_response(self, buff: Buffer):
        # login success
        self.shared_secret = pkcs1_v15_padded_rsa_decrypt(
            self.private_key, buff.unpack(ByteArray)
        )
        verify_token = pkcs1_v15_padded_rsa_decrypt(
            self.private_key, buff.unpack(ByteArray)
        )

        if verify_token != self.verify_token:
            return await self.close()

        verification_hash = generate_verification_hash(
            b"", self.shared_secret, self.public_key
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://sessionserver.mojang.com/session/minecraft/hasJoined?"
                f"username={self.username}&serverId={verification_hash}"
            ) as resp:
                if resp.status not in {200, 204}:
                    return await self.close()

                j = await resp.json()

        self.uuid = uuid.UUID(j["id"])
        self.username = j["name"]

        self.stream.key = self.shared_secret
        await self.join()

    async def join(self):
        self.state = State.PLAY
        self.server.clients.append(self)

        self.send_packet(0x02, String.pack(str(self.uuid)), String.pack(self.username))

        possible_entity_ids = set(
            range(0, 1000) - {c.entity_id for c in self.server.clients}
        )  # avoid duplicate entity ids
        self.entity_id = random.choice(list(possible_entity_ids))

        # TODO get game state from proxy
        self.send_packet(
            0x01,
            Int.pack(self.entity_id),
            UnsignedByte.pack(3),  # gamemode
            Byte.pack(b"\x01"),  # dimension
            UnsignedByte.pack(0),  # difficulty
            UnsignedByte.pack(10),  # max players
            String.pack("default"),  # level type
            Boolean.pack(True),  # reduced debug info
        )
        self.send_packet(0x05, Position.pack(Pos(0, 0, 0)))
        self.send_packet(
            0x08,
            Double.pack(0),  # x
            Double.pack(0),  # y
            Double.pack(0),  # z
            Float.pack(0),  # yaw
            Float.pack(0),  # pitch
            Byte.pack(b"\x00"),  # flags
        )
        self.send_packet(
            0x02, Chat.pack("Please wait for a new join packet to be sent!"), b"\x00"
        )


class Server:
    def __init__(self):
        self.all_clients: list[Client] = []
        self.clients: list[Client] = []  # clients in play state

    def announce(self, id: int, *data: bytes) -> None:
        for client in self.clients:
            client.send_packet(id, *data)

    def announce_all(self, id: int, *data: bytes) -> None:
        for client in self.all_clients:
            client.send_packet(id, *data)

    async def handle_client(self, reader: StreamReader, writer: StreamWriter):
        self.all_clients.append(client := Client(reader, writer, self))
        asyncio.create_task(client.handle())


async def main():
    server = Server()
    server = await asyncio.start_server(server.handle_client, "localhost", 25565)
    print("Started server!")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        import sys

        sys.exit()
