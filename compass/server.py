import asyncio
import hashlib
import json
import os
import random
import uuid
from asyncio import StreamReader, StreamWriter

import httpx
import pyroh

from petty.endpoints import Client
from petty.events import listen_client as listen
from petty.net import State
from petty.protocol.crypt import (
    generate_rsa_keypair,
    generate_verification_hash,
    pkcs1_v15_padded_rsa_decrypt,
)
from petty.protocol.datatypes import Buffer, ByteArray, Chat, String, VarInt

DER_PRIVATE_KEY, DER_PUBLIC_KEY = generate_rsa_keypair()

SESSION_SERVER_URL = "https://sessionserver.mojang.com/session/minecraft/hasJoined"


def _offline_uuid(username: str) -> str:
    # Matches Java's UUID.nameUUIDFromBytes(("OfflinePlayer:" + name).getBytes("UTF-8"))
    md5 = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode()).digest())
    md5[6] = md5[6] & 0x0F | 0x30
    md5[8] = md5[8] & 0x3F | 0x80
    return str(uuid.UUID(bytes=bytes(md5)))


class CompassServer:
    verified_clients: dict[str, ConnectedClient]

    def __init__(self, no_auth: bool = False):
        self.no_auth = no_auth
        self.clients: set[ConnectedClient] = set()
        # username: ConnectedClient instance
        self.verified_clients = dict()

    async def run_endpoint(self, endpoint: pyroh.Endpoint):
        async with endpoint:
            server = endpoint.start_server(self.handle_connection)
            await server.serve_forever()

    async def handle_connection(self, conn: pyroh.Connection):
        reader, writer = await conn.accept_bi()
        self.clients.add(ConnectedClient(conn, reader, writer, self, self.no_auth))


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
        no_auth: bool = False,
    ):
        super().__init__(reader, writer, autostart=True)

        self.compass_server = server
        self.no_auth = no_auth
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

        self.pending_responses: dict[int, asyncio.Future] = {}

    async def disconnect(self, reason: str) -> None:
        packet_id = 0x00 if self.state == State.LOGIN else 0x40
        self.downstream.send_packet(packet_id, Chat.pack(reason))

    @listen(0x00, State.LOGIN, blocking=True)
    async def _packet_login_start(self, buff: Buffer) -> None:
        self._username = buff.unpack(String)

        if self.no_auth:
            self.uuid = _offline_uuid(self._username)
            self.downstream.send_packet(
                0x02,
                String.pack(self.uuid),
                String.pack(self._username),
            )
            self.verified = True
            self.compass_server.verified_clients[self._username] = self
            self.state = State.PLAY
            self.create_task(self.keep_alive())
            return

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

    def _send_json(self, channel: str, payload: dict) -> None:
        self.downstream.send_packet(
            0x3F,
            String.pack(channel),
            String.pack(json.dumps(payload)),
        )

    async def _ask(self, action: str, data: dict, timeout=60.0) -> dict[str, int | str]:
        req_id = random.randint(0, 2147483647)
        self._send_json(
            "COMPASS|NOTIFICATION",
            {
                "request_id": req_id,
                "action": action,
                "data": data,
            },
        )
        fut = asyncio.get_running_loop().create_future()
        self.pending_responses[req_id] = fut
        try:
            async with asyncio.timeout(timeout):
                return await fut
        except TimeoutError:
            return {"response": 0}
        finally:
            self.pending_responses.pop(req_id, None)

    @listen(0x17)
    async def _packet_plugin_message(self, buff: Buffer):
        channel = buff.unpack(String)

        if channel != "COMPASS":
            return

        raw = buff.unpack(String)
        try:
            msg = json.loads(raw)
        except Exception:
            return

        if "response_id" in msg:
            response_id = msg["response_id"]
            if response_id in self.pending_responses:
                self.pending_responses[response_id].set_result(msg.get("data", {}))
            return

        request_id = msg.get("request_id")
        action = msg.get("action")
        data = msg.get("data", {})

        if request_id is None or action is None:
            return

        if action == "settings.update":
            self.discoverable = data.get("discoverable", True)
            self.whitelist = set(data.get("whitelist", []))
            self._send_json(
                "COMPASS", {"response_id": request_id, "data": {"response": 1}}
            )

        elif action in ("broadcast.outbound_request", "broadcast.outbound_invite"):
            target_player = data.get("player")
            if target_player not in self.compass_server.verified_clients:
                self._send_json(
                    "COMPASS", {"response_id": request_id, "data": {"response": 0}}
                )
                return

            target_client = self.compass_server.verified_clients[target_player]

            if not target_client.discoverable or (
                target_client.whitelist
                and self._username not in target_client.whitelist
            ):
                self._send_json(
                    "COMPASS", {"response_id": request_id, "data": {"response": 0}}
                )
                return

            inbound_action = (
                "broadcast.inbound_request"
                if action == "broadcast.outbound_request"
                else "broadcast.inbound_invite"
            )

            response_data = await target_client._ask(
                inbound_action,
                {
                    "player": self._username,
                    "node_id": self.conn.remote_node_id,
                },
            )

            if response_data.get("response") == 1:
                response_data["ticket"] = target_client.ticket

            self._send_json(
                "COMPASS", {"response_id": request_id, "data": response_data}
            )

    @listen(0x00)
    async def _packet_keep_alive(self, buff: Buffer):
        keep_alive_num = buff.unpack(VarInt)

        try:
            ticket = buff.unpack(String)
            node_id = pyroh.EndpointAddr.from_ticket(ticket).id
        except ValueError:
            return await self.close()  # TODO: log
        else:
            if node_id != self.conn.remote_node_id:
                return await self.close()  # TODO: log

            self.ticket = ticket

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
