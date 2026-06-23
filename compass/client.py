import asyncio
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass

import httpx
import pyroh

from petty.endpoints import Server
from petty.events import listen_server as listen
from petty.net import State
from petty.protocol.crypt import (
    generate_verification_hash,
    pkcs1_v15_padded_rsa_encrypt,
)
from petty.protocol.datatypes import Buffer, ByteArray, String, VarInt

from .errors import RequestFailure

logger = logging.getLogger(__name__)

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
    data: dict


class CompassClient(Server):
    _registered: asyncio.Event
    endpoint: pyroh.Endpoint | None

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

        self._shared_secret: bytes | None = None
        self._registered = asyncio.Event()

        self.discoverable: bool = True
        self.whitelist: set[str] = set()

        self.responses: AsyncDict[dict] = AsyncDict()
        self.notifications: asyncio.Queue[dict] = asyncio.Queue()
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

        self._shared_secret = os.urandom(16)

        server_hash = generate_verification_hash(
            _server_id.encode("ascii"),
            self._shared_secret,
            der_public_key,
        )

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

        encrypted_shared_secret = pkcs1_v15_padded_rsa_encrypt(
            der_public_key, self._shared_secret
        )
        encrypted_verify_token = pkcs1_v15_padded_rsa_encrypt(
            der_public_key, verify_token
        )

        self.upstream.send_packet(
            0x01,
            ByteArray.pack(encrypted_shared_secret),
            ByteArray.pack(encrypted_verify_token),
        )

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

        if channel == "COMPASS":
            raw = buff.unpack(String)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError, ValueError:
                logger.warning(
                    f"compass sent malformed JSON on COMPASS channel: {raw!r}"
                )
                await self.close("Malformed JSON from compass.")
                return

            if not isinstance(msg, dict):
                logger.warning(f"compass sent non-dict on COMPASS channel: {msg!r}")
                await self.close("Malformed JSON from compass.")
                return

            if "response_id" in msg:
                self.responses.set(msg["response_id"], msg.get("data", {}))
            else:
                logger.warning(
                    f"compass sent unexpected message on COMPASS channel: {msg!r}"
                )

        elif channel == "COMPASS|NOTIFICATION":
            raw = buff.unpack(String)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError, ValueError:
                logger.warning(
                    f"compass sent malformed JSON on COMPASS|NOTIFICATION: {raw!r}"
                )
                await self.close("Malformed JSON from compass.")
                return

            if not isinstance(msg, dict):
                logger.warning(
                    f"compass sent non-dict on COMPASS|NOTIFICATION: {msg!r}"
                )
                await self.close("Malformed JSON from compass.")
                return

            await self.notifications.put(msg)

    @listen(0x00)
    async def _packet_keep_alive(self, buff: Buffer):
        ka_num = buff.unpack(VarInt)
        await self.keep_alive_q.put(ka_num)

    async def _keep_alive(self):
        if self.endpoint is None:
            return

        while not self.closed.is_set():
            try:
                async with asyncio.timeout(10):
                    num = await self.keep_alive_q.get()
                    self.upstream.send_packet(
                        0x00, VarInt.pack(num), String.pack(self.endpoint.ticket or "")
                    )
            except TimeoutError:
                return await self.close("Timed out.")

    async def close(self, reason="", force=False):
        """Close the compass client.
        After this, a fresh compass client should be created.
        (Do not attempt to reopen this one)"""
        self._registered.clear()
        await super().close(reason, force=force)

    def _send_json(self, payload: dict) -> None:
        """Send a JSON payload to compass over the COMPASS plugin channel."""
        self.upstream.send_packet(
            0x17,
            String.pack("COMPASS"),
            String.pack(json.dumps(payload)),
        )

    async def _action(self, action: str, data: dict, *, timeout: float = 5.0) -> dict:
        """Send a JSON action to compass and wait for the keyed response."""
        if not self.registered:
            raise RequestFailure("Compass client is not registered!")

        request_id = next(self.request_counter)
        self._send_json({"request_id": request_id, "action": action, "data": data})

        try:
            async with asyncio.timeout(timeout):
                return await self.responses.get(request_id)
        except TimeoutError:
            raise RequestFailure(
                f"Timed out waiting for compass response to {action!r}"
            )

    async def respond(self, response_id: int, data: dict) -> None:
        """Send a response to an inbound compass notification (fire-and-forget)."""
        if not self.registered:
            raise RequestFailure("Compass client is not registered!")
        self._send_json({"response_id": response_id, "data": data})

    async def broadcast_outbound_request(self, player: str) -> dict:
        """Request to join player's broadcast. Waits up to 65s for their response."""
        return await self._action(
            "broadcast.outbound_request", {"player": player}, timeout=65.0
        )

    async def broadcast_outbound_invite(self, player: str) -> dict:
        """Invite player to join your broadcast. Waits up to 65s for their response."""
        return await self._action(
            "broadcast.outbound_invite", {"player": player}, timeout=65.0
        )

    async def update_settings(
        self, discoverable: bool | None, whitelist: set[str] | None
    ) -> Response:
        if discoverable is not None:
            self.discoverable = discoverable
        if whitelist is not None:
            self.whitelist = whitelist

        data = await self._action(
            "settings.update",
            {
                "discoverable": self.discoverable,
                "whitelist": list(self.whitelist),
            },
        )
        return Response(success=bool(data.get("response")), data=data)
