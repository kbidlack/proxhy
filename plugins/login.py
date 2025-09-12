import asyncio
import base64
import json
import random
import uuid
from pathlib import Path
from secrets import token_bytes
from typing import Literal, Optional
from unittest.mock import Mock

import aiohttp
import hypixel

import auth
from auth.errors import AuthException, InvalidCredentials, NotPremium
from core.cache import Cache
from core.events import listen_client, listen_server
from core.net import Server, State
from core.plugin import Plugin
from plugins.command import command
from protocol.crypt import generate_verification_hash, pkcs1_v15_padded_rsa_encrypt
from protocol.datatypes import (
    Boolean,
    Buffer,
    Byte,
    ByteArray,
    Chat,
    Double,
    Float,
    Int,
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
        self.regenerating_credentials = False

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
        self.keep_alive_task = None

    @listen_server(0x02, State.LOGIN, blocking=True, override=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.logged_in = True

        if not self.logging_in:
            self.client.send_packet(0x02, buff.read())

        await self.emit("login_success")

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, buff: Buffer):
        self.client.unpause()

        if self.logging_in:
            self.logging_in = False

            _ = buff.unpack(Int)  # entity id
            gamemode = buff.unpack(UnsignedByte)
            dimension = buff.unpack(Byte)
            difficulty = buff.unpack(UnsignedByte)
            _ = buff.unpack(UnsignedByte)  # max players
            level_type = buff.unpack(String)

            self.client.send_packet(
                0x07,
                Int(dimension),  # dimension
                UnsignedByte.pack(difficulty),  # difficulty
                UnsignedByte.pack(gamemode),  # gamemode
                String.pack(level_type),  # level type
            )
        else:
            self.client.send_packet(0x01, buff.getvalue())

    @listen_client(0x00, State.LOGIN, blocking=True, override=True)
    async def packet_login_start(self, buff: Buffer):
        self.username = buff.unpack(String)

        if not auth.user_exists(self.username):
            return await self.login()

        if auth.token_needs_refresh(self.username):
            return await self.login(reason="regen")
        reader, writer = await asyncio.open_connection(
            self.CONNECT_HOST[0], self.CONNECT_HOST[1]
        )
        self.server = Server(reader, writer)
        asyncio.create_task(self.handle_server())

        if self.keep_alive_task:
            self.keep_alive_task.cancel()

        self.client.pause(discard=True)

        self.server.send_packet(
            0x00,
            VarInt(47),
            String(self.CONNECT_HOST[2]),
            UnsignedShort(self.CONNECT_HOST[3]),
            VarInt(State.LOGIN.value),
        )

        if self.CONNECT_HOST[0] not in {"localhost", "127.0.0.1", "::1"}:
            self.access_token, self.username, self.uuid = await auth.load_auth_info(
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
        if (not self.logging_in) or self.regenerating_credentials:
            raise CommandException("You can't use that right now!")

        login_msg = TextComponent("Logging in...").color("gold")
        self.client.chat(login_msg)

        try:
            access_token, username, uuid = await auth.login(email, password)
        except InvalidCredentials:
            raise CommandException("Login failed; invalid credentials!")
        except NotPremium:
            raise CommandException("This account is not premium!")
        except AuthException as e:
            raise CommandException(
                f"An unknown error occurred while logging in! Try again? {e}"
            )

        if username != self.username:
            raise CommandException(
                f"Wrong account! Logged into {username}; expected {self.username}"
            )

        self.access_token = access_token
        self.uuid = uuid

        success_msg = TextComponent(
            f"Logged in! Redirecting to {self.CONNECT_HOST[0]}..."
        ).color("green")
        self.client.chat(success_msg)
        self.state = State.LOGIN

        await self.packet_login_start(Buffer(String.pack(self.username)))

    async def login_keep_alive(self):
        while True:
            await asyncio.sleep(10)
            if self.state == State.PLAY and self.client.open and self.logging_in:
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

    async def login(self, reason: Literal["logging_in", "regen"] = "logging_in"):
        # immediately send login start to enter login server
        self.state = State.PLAY
        self.logging_in = True

        # fake server stream
        self.server = Mock()

        async with (c := hypixel.Client()):
            uuid_ = await c._get_uuid(self.username)

        self.client.send_packet(
            0x02, String(str(uuid.UUID(uuid_))), String(self.username)
        )

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

        self.client.send_packet(
            0x08, Double(0), Double(0), Double(0), Float(0), Float(0), Byte(b"\x00")
        )

        self.keep_alive_task = asyncio.create_task(self.login_keep_alive())

        if reason == "logging_in":
            self.client.chat("You have not logged into Proxhy with this account yet!")
            self.client.chat("Use /login <email> <password> to log in.")
        else:
            self.regenerating_credentials = True
            self.client.set_title(
                title=TextComponent("Please Wait").color("red"),
                subtitle=TextComponent("You will be redirected to")
                .color("white")
                .appends(TextComponent(self.CONNECT_HOST[0]).color("gold"))
                .appends(TextComponent("soon!").color("white")),
                duration=200,
            )
            try:
                self.access_token, self.username, self.uuid = await auth.load_auth_info(
                    self.username
                )
            except Exception as e:
                return self.client.send_packet(
                    0x40,
                    Chat.pack(
                        TextComponent(
                            f"Failed to regenerate credentials ):\n {type(e).__name__}: {e}"
                        ).color("red")
                    ),
                )

            success_msg = (
                TextComponent("Credentials regenerated successfully! Redirecting to")
                .color("green")
                .appends(TextComponent(self.CONNECT_HOST[0]).color("gold"))
            )
            self.client.reset_title()
            self.client.chat(success_msg)
            self.state = State.LOGIN

            await self.packet_login_start(Buffer(String.pack(self.username)))

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

    async def _session_encrypt(self, server_id: bytes, public_key: bytes) -> bytes:
        # generate shared secret
        secret = token_bytes(16)

        if not (self.access_token or self.uuid):
            self.access_token, self.username, self.uuid = await auth.load_auth_info(
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
