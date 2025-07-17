import asyncio
import random
import uuid
from typing import TYPE_CHECKING, Callable
from unittest.mock import Mock

import hypixel
from msmcauth.errors import InvalidCredentials, MsMcAuthException, NotPremium

from .. import auth
from ..command import command
from ..datatypes import (
    Boolean,
    Buffer,
    Byte,
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
from ..errors import CommandException
from ..net import Server
from ..proxhy import Proxhy, State
from ..proxy import listen_client, listen_server
from ._methods import method


class Login(Proxhy):
    if TYPE_CHECKING:
        from .statcheck import StatCheck

        log_bedwars_stats: Callable = StatCheck.log_bedwars_stats

    @listen_server(0x02, State.LOGIN, blocking=True, override=True)
    async def packet_login_success(self, buff: Buffer):
        self.state = State.PLAY
        self.logged_in = True

        self.hypixel_client = hypixel.Client(self.hypixel_api_key)

        await self.log_bedwars_stats("login")

        self.client.send_packet(0x02, buff.read())

    @listen_client(0x00, State.LOGIN)
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

    @method
    async def login_keep_alive(self):
        while True:
            await asyncio.sleep(10)
            if self.state == State.PLAY and self.client.open:
                self.client.send_packet(0x00, VarInt(random.randint(0, 256)))
            else:
                await self.close()
                break

    @method
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
