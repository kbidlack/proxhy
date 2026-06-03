import asyncio
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import httpx
import pyroh

from petty.endpoints import Server
from petty.events import listen_server as listen
from petty.net import State
from petty.protocol.crypt import (
    generate_verification_hash,
    pkcs1_v15_padded_rsa_encrypt,
)
from petty.protocol.datatypes import Boolean, Buffer, Byte, ByteArray, String, VarInt

from .errors import RequestFailure

SESSION_SERVER_JOIN_URL = "https://sessionserver.mojang.com/session/minecraft/join"


class ByteCounter:
    MIN = -128
    MAX = 127
    MOD = 256

    def __init__(self, value=0):
        self.value = value % self.MOD

    def __iter__(self):
        return self

    def __next__(self):
        unsigned = (self.value + 128) % self.MOD
        unsigned = (unsigned + 1) % self.MOD
        self.value = unsigned - 128
        return self.value


class AsyncDict[T]:
    _values: dict[str, T]

    def __init__(self):
        self._values = {}
        self._waiters = defaultdict(list)

    def set(self, key, value: T):
        self._values[key] = value
        for fut in self._waiters.pop(key, []):
            if not fut.done():
                fut.set_result(value)

    async def get(self, key) -> T:
        if key in self._values:
            return self._values[key]

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._waiters[key].append(fut)
        return await fut


@dataclass
class Response:
    success: bool
    details: str


class CompassClient(Server):
    _registered: asyncio.Event
    endpoint: Optional[pyroh.Endpoint]

    def __init__(
        self,
        broker_url: str,
        username: str,
        uuid: str,
        access_token: str,
    ):
        self.state = State.LOGIN

        self.username = username
        self.access_token = access_token
        self.uuid = uuid  # without dashes

        self.broker_url = broker_url

        self._shared_secret: Optional[bytes] = None
        self._registered = asyncio.Event()

        self.discoverable: bool = True
        self.whitelist: set[str] = set()

        self.responses: AsyncDict[Response] = AsyncDict()
        self.keep_alive_q = asyncio.Queue()

        self.request_counter = ByteCounter()

        self._setup_node()

    @property
    def registered(self) -> bool:
        return self._registered.is_set()

    async def register(self, endpoint: pyroh.Endpoint):
        self.endpoint = endpoint

        async with asyncio.timeout(5):
            async with httpx.AsyncClient() as client:
                ticket = (await client.get(self.broker_url)).content.decode("utf-8")
            conn = await self.endpoint.connect(ticket, alpn=b"compass/1")
            reader, writer = await conn.open_bi()

        super().__init__(reader, writer)
        self.state = State.LOGIN

        self.create_task(self._keep_alive())

        self.upstream.send_packet(
            0x00,
            String.pack(self.username),
        )

        await self._registered.wait()

    @listen(0x01, State.LOGIN, blocking=True)
    async def _packet_encryption_request(self, buff: Buffer) -> None:
        _server_id = buff.unpack(String)
        der_public_key = buff.unpack(ByteArray)
        verify_token = buff.unpack(ByteArray)

        # Generate a random 16-byte shared secret.
        self._shared_secret = os.urandom(16)

        # Compute the server hash for Mojang auth.
        server_hash = generate_verification_hash(
            _server_id.encode("ascii"),
            self._shared_secret,
            der_public_key,
        )

        # Notify Mojang that we're joining this server.
        payload = {
            "accessToken": self.access_token,
            "selectedProfile": self.uuid,
            "serverId": server_hash,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(SESSION_SERVER_JOIN_URL, json=payload)

            if resp.status_code != 204:
                await self.close("Failed to authenticate with Mojang.")
                return

        # Encrypt shared secret and verify token with the server's public key.
        encrypted_shared_secret = pkcs1_v15_padded_rsa_encrypt(
            der_public_key, self._shared_secret
        )
        encrypted_verify_token = pkcs1_v15_padded_rsa_encrypt(
            der_public_key, verify_token
        )

        # Send Encryption Response (C→S  0x01).

        self.upstream.send_packet(
            0x01,
            ByteArray.pack(encrypted_shared_secret),
            ByteArray.pack(encrypted_verify_token),
        )

        # Enable AES/CFB8 encryption — everything from here on is encrypted.

        self.upstream.key = self._shared_secret

    @listen(0x02, State.LOGIN, blocking=True)
    async def _packet_login_success(self, buff: Buffer) -> None:
        _uuid = buff.unpack(String)
        _username = buff.unpack(String)

        self.state = State.PLAY

        self._registered.set()

    @listen(0x3F)
    async def _packet_plugin_message(self, buff: Buffer):
        channel = buff.unpack(String)
        if not channel.startswith("COMPASS"):
            return
        else:
            request_id = buff.unpack(Byte)

        if channel == "COMPASS|RESPONSE":
            success = buff.unpack(Boolean)
            details = buff.unpack(String)

            self.responses.set(request_id, Response(success, details))

    @listen(0x00)
    async def _packet_keep_alive(self, buff: Buffer):
        ka_num = buff.unpack(VarInt)

        await self.keep_alive_q.put(ka_num)

    async def _keep_alive(self):
        if self.endpoint is None:
            return  # TODO: log?

        while not self.closed.is_set():
            try:
                async with asyncio.timeout(10):
                    num = await self.keep_alive_q.get()

                    self.upstream.send_packet(
                        0x00, VarInt.pack(num), String.pack(self.endpoint.ticket or "")
                    )
            except asyncio.TimeoutError:
                return await self.close("Timed out.")

    async def close(self, reason="", force=False):
        """Close the compass client.
        After this, a fresh compass client should be created.
        (Do not attempt to reopen this one)"""
        self._registered.clear()
        await super().close(reason, force=force)

    async def _message(self, channel: str, *data: bytes) -> Response:
        # raises TimeoutError or RequestFailure
        if not self.registered:
            raise RequestFailure("Compass client is not registered!")

        self.upstream.send_packet(
            0x17,
            String.pack(channel),
            Byte.pack(request_id := next(self.request_counter)),
            *data,
        )

        async with asyncio.timeout(2):
            return await self.responses.get(request_id)

    async def request(self, username: str) -> Response:
        return await self._message("COMPASS|REQUEST", String.pack(username))

    async def verify(self, username: str, node_id: str) -> Response:
        return await self._message(
            "COMPASS|VERIFY", String.pack(username), String.pack(node_id)
        )

    async def update_settings(
        self, discoverable: Optional[bool], whitelist: Optional[set[str]]
    ) -> Response:
        if discoverable is not None:
            self.discoverable = discoverable
        if whitelist:
            self.whitelist = whitelist

        return await self._message(
            "COMPASS|STATE",
            Boolean.pack(self.discoverable),
            Byte.pack(len(self.whitelist)),
            *(String.pack(player) for player in self.whitelist),
        )
