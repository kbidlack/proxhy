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

from .client import Proxy
from .datatypes import (
    # UUID,
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
from .encryption import (
    Stream,
    generate_rsa_keypair,
    generate_verification_hash,
    pkcs1_v15_padded_rsa_decrypt,
)
from .models import Pos

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

        self.getting_data = False

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

    async def close(self, reason: str = ""):
        if self.stream.open:
            if not reason:
                self.send_packet(0x40, Chat.pack("§4Broadcast server closed!"))
            else:
                self.send_packet(0x40, Chat.pack(reason))
            self.stream.close()
        elif self.username:
            self.server.chat(f"§b{self.username} §4left the broadcast!")

        try:
            self.server.clients.remove(self)
        except ValueError:
            pass

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
        self.stream.close()
        await self.close()

    @listen(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self, _):
        online = len([c for c in self.server.clients if c.state == State.PLAY])
        server_list_ping = {
            "version": {"name": "1.8.9", "protocol": 47},
            "players": {
                "max": 3,  # TODO enforce max players
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

    @listen(0x00, State.LOGIN)
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
        # TODO compression
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
        self.send_packet(0x02, String.pack(str(self.uuid)), String.pack(self.username))

        self.server.chat(
            f"§b{self.username} §9({self.address[0]}) §ejoined the broadcast!"
        )

        possible_entity_ids = set(range(0, 1000)) - {
            c.entity_id for c in self.server.clients
        }  # avoid duplicate entity ids
        self.entity_id: int = random.choice(list(possible_entity_ids))

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
        self.send_packet(0x02, Chat.pack_msg("Welcome to the broadcast!"))

        self.state = State.PLAY
        self.server.clients.append(self)
        asyncio.create_task(self.keep_alive())

    async def keep_alive(self):
        while True:
            await asyncio.sleep(10)
            if (
                self.state == State.PLAY
                and self.stream.open
                and self in self.server.clients
            ):
                self.send_packet(0x00, VarInt.pack(random.randint(0, 256)))
            else:
                break

    @listen(0x01, State.PLAY)
    async def packet_chat_message(self, buff: Buffer):
        message = buff.unpack(String)
        self.server.chat(f"§3[§5BROADCAST§3] §b{self.username}: §e{message}")

    @listen(0x15, State.PLAY)
    async def packet_client_settings(self, buff: Buffer):
        _ = buff.unpack(String)  # locale
        _ = buff.unpack(Byte)  # view distance
        chat_mode = buff.unpack(Byte)[0]
        chat_mode  # TODO respect chat mode

    # @listen(0x18, State.PLAY)
    # async def packet_spectate(self, buff: Buffer):
    #     target = buff.unpack(UUID)
    #     for client in self.server.clients:
    #         if client.uuid == target:
    #             # TODO
    #             self.server.proxy.send_packet(
    #                 self.server.proxy.client_stream,
    #                 0x18,
    #                 Int.pack(client.entity_id),
    #             )
    #             break


class Server:
    def __init__(self, proxy: Proxy):
        self.all_clients: list[Client] = []
        self.clients: list[Client] = []  # clients in play state

        self.proxy = proxy

    def announce(self, id: int, *data: bytes) -> None:
        for client in self.clients:
            client.send_packet(id, *data)

    def chat(self, message: str) -> None:
        msg = Chat.pack_msg(message)
        self.announce(0x02, msg)
        self.proxy.send_packet(self.proxy.client_stream, 0x02, msg)

    # def announce_all(self, id: int, *data: bytes) -> None:
    #     for client in self.all_clients:
    #         client.send_packet(id, *data)

    async def handle_client(self, reader: StreamReader, writer: StreamWriter):
        self.all_clients.append(client := Client(reader, writer, self))
        asyncio.create_task(client.handle())

    async def close(self, reason: str = ""):
        for client in self.all_clients:
            await client.close(reason)

        self.aserver.close()
        await self.aserver.wait_closed()

    async def serve_forever(self, port: int = 25565):
        self.aserver = await asyncio.start_server(self.handle_client, "localhost", port)
        async with self.aserver:
            await self.aserver.serve_forever()


async def main():
    server = Server()
    await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        import sys

        sys.exit()
