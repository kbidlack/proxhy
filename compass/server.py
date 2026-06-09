import asyncio
import os
import random
from asyncio import StreamReader, StreamWriter

import httpx
import pyroh

from petty.endpoints import Client
from petty.events import listen_client as listen
from petty.net import State
from petty.protocol import Byte
from petty.protocol.crypt import (
    generate_rsa_keypair,
    generate_verification_hash,
    pkcs1_v15_padded_rsa_decrypt,
)
from petty.protocol.datatypes import Boolean, Buffer, ByteArray, Chat, String, VarInt

DER_PRIVATE_KEY, DER_PUBLIC_KEY = generate_rsa_keypair()

SESSION_SERVER_URL = "https://sessionserver.mojang.com/session/minecraft/hasJoined"


class CompassServer:
    verified_clients: dict[str, ConnectedClient]

    def __init__(self):
        self.clients: set[ConnectedClient] = set()
        # username: ConnectedClient instance
        self.verified_clients = dict()

    async def run_endpoint(self, endpoint: pyroh.Endpoint):
        async with endpoint:
            server = endpoint.start_server(self.handle_connection)
            await server.serve_forever()

    async def handle_connection(self, conn: pyroh.Connection):
        reader, writer = await conn.accept_bi()
        self.clients.add(ConnectedClient(conn, reader, writer, self))


class ConnectedClient(Client):
    compass_server: CompassServer
    conn: pyroh.Connection

    discoverable: bool
    whitelist_enabled: bool
    whitelist: set[str]

    def __init__(
        self,
        conn: pyroh.Connection,
        reader: StreamReader,
        writer: StreamWriter,
        server: CompassServer,
    ):
        super().__init__(reader, writer, autostart=True)

        self.compass_server = server
        self.state = State.LOGIN

        self.conn = conn
        self.ticket = ""

        self._username: str | None = None  # before verifying
        self._verify_token: bytes | None = None

        self.c_keep_alive_q = asyncio.Queue()
        self.s_keep_alive_q = asyncio.Queue()

        self.verified = False

        self.discoverable = True
        self.whitelist_enabled = False
        self.whitelist = set()

    async def disconnect(self, reason: str) -> None:
        packet_id = 0x00 if self.state == State.LOGIN else 0x40
        self.downstream.send_packet(packet_id, Chat.pack(reason))

    @listen(0x00, State.LOGIN, blocking=True)
    async def _packet_login_start(self, buff: Buffer) -> None:
        self._username = buff.unpack(String)

        self._verify_token = os.urandom(4)

        self.downstream.send_packet(
            0x01,
            String.pack(""),
            ByteArray.pack(DER_PUBLIC_KEY),
            ByteArray.pack(self._verify_token),
        )

    @listen(0x01, State.LOGIN, blocking=True)
    async def _packet_encryption_response(self, buff: Buffer) -> None:
        encrypted_shared_secret = buff.unpack(ByteArray)
        encrypted_verify_token = buff.unpack(ByteArray)

        shared_secret = pkcs1_v15_padded_rsa_decrypt(
            DER_PRIVATE_KEY, encrypted_shared_secret
        )
        decrypted_token = pkcs1_v15_padded_rsa_decrypt(
            DER_PRIVATE_KEY, encrypted_verify_token
        )

        if decrypted_token != self._verify_token:
            await self.disconnect("Encryption failure: verify token mismatch.")
            return

        server_hash = generate_verification_hash(
            b"",  # empty server_id (1.7+)
            shared_secret,
            DER_PUBLIC_KEY,
        )

        params = {"username": self._username, "serverId": server_hash}
        async with httpx.AsyncClient() as client:
            resp = await client.get(SESSION_SERVER_URL, params=params)
            if resp.status_code != 200:
                return await self.close("Failed to verify your session with Mojang!")

            profile = resp.json()

        self.downstream.key = shared_secret

        # format uuid with dashes
        raw_id: str = profile["id"]
        formatted_uuid = f"{raw_id[0:8]}-{raw_id[8:12]}-{raw_id[12:16]}-{raw_id[16:20]}-{raw_id[20:]}"
        self.uuid = formatted_uuid

        self.downstream.send_packet(
            0x02,
            String.pack(formatted_uuid),
            String.pack(profile["name"]),
        )

        self.verified = True
        if self._username is not None:
            self.compass_server.verified_clients[self._username] = self

        self.state = State.PLAY
        self.create_task(self.keep_alive())

    @listen(0x17)
    async def _packet_plugin_message(self, buff: Buffer):
        channel = buff.unpack(String)

        if not channel.startswith("COMPASS"):
            return
        else:
            request_id = buff.unpack(Byte)

        if channel == "COMPASS|STATE":
            e: Exception | None = None
            try:
                self.discoverable = buff.unpack(Boolean)
                num_whitelist = buff.unpack(Byte)
                self.whitelist = {buff.unpack(String) for _ in range(num_whitelist)}

                success = True
            except Exception as error:
                success = False
                e = error

            self.downstream.send_packet(
                0x3F,
                String.pack("COMPASS|RESPONSE"),
                Byte.pack(request_id),
                Boolean.pack(success),
                String.pack(
                    "Successfully updated state"
                    if success
                    else f"Failed to update state: {e}"
                ),
            )
        elif channel == "COMPASS|REQUEST":
            username = buff.unpack(String)
            client = self.compass_server.verified_clients.get(username)

            def _reject_request():
                self.downstream.send_packet(
                    0x3F,
                    String.pack("COMPASS|RESPONSE"),
                    Byte.pack(request_id),
                    Boolean.pack(False),  # request did not succeed
                    String.pack(f"{username} is not available!"),
                )

            if client is None:
                return _reject_request()
            if not client.discoverable:
                return _reject_request()
            if client.whitelist and self._username not in client.whitelist:
                return _reject_request()
            self.downstream.send_packet(
                0x3F,
                String.pack("COMPASS|RESPONSE"),
                Byte.pack(request_id),
                Boolean.pack(True),
                String.pack(client.ticket),
            )
        elif channel == "COMPASS|VERIFY":
            username = buff.unpack(String)
            node_id = buff.unpack(String)

            client = self.compass_server.verified_clients.get(username)

            if client is not None and client.conn.remote_node_id == node_id:
                self.downstream.send_packet(
                    0x3F,
                    String.pack("COMPASS|RESPONSE"),
                    Byte.pack(request_id),
                    Boolean.pack(True),
                    String.pack(client.uuid),
                )
            else:
                self.downstream.send_packet(
                    0x3F,
                    String.pack("COMPASS|RESPONSE"),
                    Byte.pack(request_id),
                    Boolean.pack(False),
                    String.pack(""),
                )

    @listen(0x00)
    async def _packet_keep_alive(self, buff: Buffer):
        keep_alive_num = buff.unpack(VarInt)
        self.ticket = buff.unpack(String)
        await self.c_keep_alive_q.put(keep_alive_num)

    async def _handle_stream(self, *args, **kwargs):
        try:
            await super()._handle_stream(*args, **kwargs)
        except Exception:
            await self.close("Stream failed.")

    async def keep_alive(self):
        while not self.closed.is_set():
            try:
                async with asyncio.timeout(10):
                    await self.s_keep_alive_q.put(
                        ka_num := random.randint(-(1 << 31), (1 << 31) - 1)
                    )
                    self.downstream.send_packet(0x00, VarInt.pack(ka_num))
                    c_ka_num = await self.c_keep_alive_q.get()
                    if c_ka_num != ka_num:
                        return await self.close("Incorrect keep alive packet!")
            except TimeoutError:
                return await self.close("Timed out.")

            await asyncio.sleep(5)

    async def close(self, reason="", force=False):
        if reason:
            packet_id = 0x00 if self.state == State.LOGIN else 0x40
            self.downstream.send_packet(packet_id, Chat.pack(reason))
        await super().close(reason, force=force)
        self.compass_server.clients.discard(self)
        if (
            self._username is not None
            and self._username in self.compass_server.verified_clients
        ):
            del self.compass_server.verified_clients[self._username]
