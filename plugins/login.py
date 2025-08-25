import asyncio
import base64
import json
import random
import uuid
from pathlib import Path
from secrets import token_bytes
from typing import Optional
from unittest.mock import Mock

import aiohttp
from msmcauth.errors import InvalidCredentials, MsMcAuthException, NotPremium

from core.cache import Cache
from core.events import listen_client, listen_server
from core.net import Server, State
from core.plugin import Plugin
from plugins.command import command
from protocol import auth
from protocol.crypt import generate_verification_hash, pkcs1_v15_padded_rsa_encrypt
from protocol.datatypes import (
    Boolean,
    Buffer,
    Byte,
    ByteArray,
    Double,
    Float,
    Int,
    Pos,
    Position,
    String,
    TextComponent,
    UnsignedByte,
    UnsignedShort,
    VarInt,
)
from proxhy.errors import CommandException


class LoginPlugin(Plugin):
    def _init_login(self):
        self.logged_in = False
        self.logging_in = False

        # load favicon
        # https://github.com/barneygale/quarry/blob/master/quarry/net/server.py/#L356-L357
        favicon_path = Path(__file__).parent.parent / "assets" / "favicon.png"
        with open(favicon_path, "rb") as file:
            b64_favicon = (
                base64.encodebytes(file.read()).decode("ascii").replace("\n", "")
            )

        self.server_list_ping = {
            "version": {"name": "1.8.9", "protocol": 47},
            "players": {
                "max": 1,
                "online": 0,
            },
            "description": {"text": "why hello there"},
            "favicon": f"data:image/png;base64,{b64_favicon}",
        }

        self.access_token = ""
        self.uuid = ""
        self.secret: bytes = b""

        self.secret_task: Optional[asyncio.Task] = None

    @listen_server(0x02, State.LOGIN, blocking=True, override=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.logged_in = True

        self.client.send_packet(0x02, buff.read())
        await self.emit("login_success")

    @listen_client(0x00, State.LOGIN, blocking=True, override=True)
    async def packet_login_start(self, buff: Buffer):
        self.username = buff.unpack(String)

        if not auth.user_exists(self.username):
            return await self.login()

        reader, writer = await asyncio.open_connection(
            self.CONNECT_HOST[0], self.CONNECT_HOST[1]
        )
        self.server = Server(reader, writer)
        asyncio.create_task(self.handle_server())

        self.server.send_packet(
            0x00,
            VarInt(47),
            String(self.CONNECT_HOST[2]),
            UnsignedShort(self.CONNECT_HOST[3]),
            VarInt(State.LOGIN.value),
        )

        if self.CONNECT_HOST[0] not in {"localhost", "127.0.0.1", "::1"}:
            self.access_token, self.username, self.uuid = auth.load_auth_info(
                self.username
            )

            async with Cache() as cache:
                if self.CONNECT_HOST in cache:
                    # if we have cached details for this server
                    # immediately start the login encryption process
                    server_id, public_key = cache[self.CONNECT_HOST]
                    self.secret_task = asyncio.create_task(
                        self._session_encrypt(server_id, public_key)
                    )

        self.server.send_packet(0x00, String(self.username))

    @command("login")
    async def login_command(self, email, password):
        login_msg = TextComponent("Logging in...").color("gold")
        self.client.chat(login_msg)
        if not self.logging_in:
            raise CommandException("You can't use that right now!")

        try:
            access_token, username, uuid = auth.login(email, password)
        except InvalidCredentials:
            raise CommandException("Login failed; invalid credentials!")
        except NotPremium:
            raise CommandException("This account is not premium!")
        except MsMcAuthException:
            raise CommandException(
                "An unknown error occurred while logging in! Try again?"
            )

        if username != self.username:
            raise CommandException(
                f"Wrong account! Logged into {username}; expected {self.username}"
            )

        self.access_token = access_token
        self.uuid = uuid

        success_msg = TextComponent("Logged in; rejoin proxhy to play!").color("green")
        self.client.chat(success_msg)

    async def login_keep_alive(self):
        while True:
            await asyncio.sleep(10)
            if self.state == State.PLAY and self.client.open:
                self.client.send_packet(0x00, VarInt(random.randint(0, 256)))
            else:
                await self.close()
                break

    @listen_client(0x00, State.HANDSHAKING, blocking=True, override=True)
    async def packet_handshake(self, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)

    async def login(self):
        # immediately send login start to enter login server
        self.state = State.PLAY
        self.logging_in = True

        # fake server stream
        self.server = Mock()
        self.client.send_packet(0x02, String(str(uuid.uuid4())), String(self.username))

        self.client.send_packet(
            0x01,
            Int(0),
            UnsignedByte(3),
            Byte(b"\x01"),
            UnsignedByte(0),
            UnsignedByte(1),
            String("default"),
            Boolean(True),
        )

        self.client.send_packet(0x05, Position(Pos(0, 0, 0)))
        self.client.send_packet(
            0x08, Double(0), Double(0), Double(0), Float(0), Float(0), Byte(b"\x00")
        )

        asyncio.create_task(self.login_keep_alive())

        self.client.chat("You have not logged into Proxhy with this account yet!")
        self.client.chat("Use /login <email> <password> to log in.")

    @listen_client(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self, _):
        self.client.send_packet(0x00, String(json.dumps(self.server_list_ping)))

    @listen_client(0x01, State.STATUS, blocking=True)
    async def packet_ping_request(self, buff: Buffer):
        self.client.send_packet(0x01, buff.getvalue())
        # close connection
        await self.close()

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

        if self.secret_task:
            self.secret = await self.secret_task

        # admittedly after creating this I realize that hypixel
        # changes the server id (or public key?) on every login
        # so it doesn't do much, but I'm leaving it because I kinda
        # spent a while (not really) making this work and also
        # it works on other servers which technically doesn't matter, but still...
        async with Cache() as cache:
            if self.CONNECT_HOST not in cache or cache[self.CONNECT_HOST] != (
                server_id,
                public_key,
            ):
                # if server_id/public_key are not cached
                # OR if the cache is incorrect
                cache[self.CONNECT_HOST] = (server_id, public_key)
                self.secret = await self._session_encrypt(server_id, public_key)

        # here, self.secret SHOULD be set from either packet_login_start (cached)
        # or above conditions

        if not self.secret:
            # but for whatever reason if we still do not have the secret
            self.secret = await self._session_encrypt(server_id, public_key)

        verify_token = buff.unpack(ByteArray)

        encrypted_secret = pkcs1_v15_padded_rsa_encrypt(public_key, self.secret)
        encrypted_verify_token = pkcs1_v15_padded_rsa_encrypt(public_key, verify_token)

        self.server.send_packet(
            0x01,
            ByteArray(encrypted_secret),
            ByteArray(encrypted_verify_token),
        )

        # enable encryption
        self.server.key = self.secret
        self.server.key = self.secret

    async def _session_encrypt(self, server_id: bytes, public_key: bytes) -> bytes:
        # generate shared secret
        secret = token_bytes(16)

        if not (self.access_token or self.uuid):
            self.access_token, self.username, self.uuid = auth.load_auth_info(
                self.username
            )

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

        return secret
