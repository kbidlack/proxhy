import asyncio
import base64
import json
from pathlib import Path
from secrets import token_bytes

import aiohttp
from client import Client, State, listen_client, listen_server
from datatypes import Buffer, ByteArray, Long, String, UnsignedShort, VarInt
from encryption import Stream, generate_verification_hash, pkcs1_v15_padded_rsa_encrypt


class ProxyClient(Client):
    # load favicon
    # https://github.com/barneygale/quarry/blob/master/quarry/net/server.py/#L356-L357
    favicon_path = Path(__file__).parent.resolve() / "assets" / "favicon.png"
    with open(favicon_path, "rb") as file:
        b64_favicon = base64.encodebytes(file.read()).decode("ascii").replace("\n", "")

    @listen_client(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self, _):
        self.server_list_ping = {
            "version": {"name": "1.8.9", "protocol": 47},
            "players": {
                "max": 1,
                "online": 0,
            },
            "description": {"text": "Proxhy"},
            "favicon": f"data:image/png;base64,{self.b64_favicon}",
        }

        self.send_packet(
            self.client_stream, 0x00, String.pack(json.dumps(self.server_list_ping))
        )

    @listen_client(0x00, State.HANDSHAKING, blocking=True)
    async def packet_handshake(self, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        assert buff.unpack(VarInt) == 47  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)
        if self.state == State.LOGIN:
            reader, writer = await asyncio.open_connection("mc.hypixel.net", 25565)
            self.server_stream = Stream(reader, writer)
            asyncio.create_task(self.handle_server())

            self.send_packet(
                self.server_stream,
                0x00,
                VarInt.pack(47),
                String.pack("mc.hypixel.net"),
                UnsignedShort.pack(25565),
                VarInt.pack(State.LOGIN.value),
            )

    @listen_client(0x01, State.STATUS, blocking=True)
    async def packet_ping_request(self, buff: Buffer):
        payload = buff.unpack(Long)
        self.send_packet(self.client_stream, 0x01, Long.pack(payload))
        # close connection
        await self.close()

    @listen_client(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        while not self.server_stream:
            await asyncio.sleep(0.01)

        self.username = buff.unpack(String)
        self.send_packet(self.server_stream, 0x00, String.pack(self.username))

    @listen_server(0x01, State.LOGIN, blocking=True)
    async def packet_encryption_request(self, buff: Buffer):
        server_id = buff.unpack(String).encode("utf-8")
        public_key = buff.unpack(ByteArray)
        verify_token = buff.unpack(ByteArray)

        # generate shared secret
        secret = token_bytes(16)
        payload = {
            "accessToken": self.access_token,
            "selectedProfile": self.uuid,
            "serverId": generate_verification_hash(server_id, secret, public_key),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://sessionserver.mojang.com/session/minecraft/join", json=payload
            ) as response:
                if not response.status == 204:
                    raise Exception(
                        f"Login failed: {response.status} {response.json()}"
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

    @listen_server(0x02, State.LOGIN, blocking=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.send_packet(self.client_stream, 0x02, buff.read())

    @listen_server(0x03, State.LOGIN, blocking=True)
    async def packet_set_compression(self, buff: Buffer):
        self.compression_threshold = buff.unpack(VarInt)
        self.compression = False if self.compression_threshold == -1 else True

    async def close(self):
        if self.server_stream:
            self.server_stream.close()
        self.client_stream.close()

        del self  # idk if this does anything or not
        # on second thought probably not but whatever
