import asyncio
import base64
import random
import uuid
from importlib.metadata import version
from importlib.resources import files
from secrets import token_bytes
from typing import TYPE_CHECKING, Literal, Optional
from unittest.mock import Mock

import httpx
import hypixel
import orjson
from petty.events import listen_client, listen_server, subscribe
from petty.net import ServerStream, State
from petty.protocol.crypt import (
    generate_verification_hash,
    pkcs1_v15_padded_rsa_encrypt,
)
from petty.protocol.datatypes import (
    Boolean,
    Buffer,
    Byte,
    ByteArray,
    Chat,
    Double,
    Float,
    Int,
    Short,
    Slot,
    String,
    TextComponent,
    UnsignedByte,
    UnsignedShort,
    VarInt,
)

import auth
from auth.errors import AuthException
from proxhy import utils
from proxhy.utils import Cache

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin


class LoginPlugin:
    logged_in: bool
    logging_in: bool
    regenerating_credentials: bool
    device_code_task: Optional[asyncio.Task]
    server_list_ping: dict
    access_token: str
    username: str
    uuid: uuid.UUID
    secret: bytes
    secret_task: Optional[asyncio.Task]
    keep_alive_task: Optional[asyncio.Task]
    transferring_to_server: bool

    def _init_login(self: ProxhyPlugin):
        self.logged_in = False
        self.logging_in = False
        self.regenerating_credentials = False
        self.device_code_task = None
        self.transferring_to_server = False

        # load favicon
        # https://github.com/barneygale/quarry/blob/master/quarry/net/server.py/#L356-L357
        favicon_path = files("assets").joinpath("favicon.png")
        with favicon_path.open("rb") as file:
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
        self.secret: bytes = b""

        self.secret_task: Optional[asyncio.Task] = None
        self.keep_alive_task = None

    @listen_server(0x02, State.LOGIN, blocking=True)
    async def packet_login_success(self: ProxhyPlugin, buff: Buffer):
        self.state = State.PLAY
        self.logged_in = True
        self.transferring_to_server = False

        # parse and store uuid from login success packet
        # for localhost/offline mode when uuid isnt set during auth
        uuid_str = buff.unpack(String)
        username = buff.unpack(String)
        try:
            if not self.uuid:
                self.uuid = uuid.UUID(uuid_str)
        except AttributeError:
            self.uuid = uuid.UUID(uuid_str)

        if not self.logging_in:
            self.downstream.send_packet(
                0x02, String.pack(uuid_str), String.pack(username)
            )

        await self.emit("login_success")

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self: ProxhyPlugin, buff: Buffer):
        self.downstream.unpause()

        if self.logging_in:
            self.logging_in = False

            # removes weird bugs when you join
            self.downstream.send_packet(
                0x07,
                Int.pack(-1),  # dimension: nether
                UnsignedByte.pack(0),  # difficulty: peaceful
                UnsignedByte.pack(3),  # gamemode: spectator
                String.pack("default"),  # level type
            )
            self.downstream.send_packet(0x01, buff.getvalue())

            _ = buff.unpack(Int)  # entity id
            gamemode = buff.unpack(UnsignedByte)
            dimension = buff.unpack(Byte)
            difficulty = buff.unpack(UnsignedByte)
            _ = buff.unpack(UnsignedByte)  # max players
            level_type = buff.unpack(String)

            self.downstream.send_packet(
                0x07,
                Int.pack(dimension),  # dimension
                UnsignedByte.pack(difficulty),  # difficulty
                UnsignedByte.pack(gamemode),  # gamemode
                String.pack(level_type),  # level type
            )

        else:
            self.downstream.send_packet(0x01, buff.getvalue())

    async def _resend_armor_stands(self: ProxhyPlugin):
        await asyncio.sleep(1.0)
        while self.open and self.downstream.open:
            for entity in list(self.gamestate.entities.values()):
                if entity.entity_type != 78:
                    continue

                eid = entity.entity_id
                # destroy first
                self.downstream.send_packet(0x13, VarInt.pack(1) + VarInt.pack(eid))
                packet_id, packet_data = self.gamestate._build_spawn_object(entity)
                self.downstream.send_packet(packet_id, packet_data)
                if entity.metadata:
                    self.downstream.send_packet(
                        0x1C,
                        VarInt.pack(eid)
                        + self.gamestate._pack_metadata(entity.metadata),
                    )
                equip = entity.equipment
                for slot_id, item in [
                    (0, equip.held),
                    (1, equip.boots),
                    (2, equip.leggings),
                    (3, equip.chestplate),
                    (4, equip.helmet),
                ]:
                    if item.item:
                        self.downstream.send_packet(
                            0x04,
                            VarInt.pack(eid) + Short.pack(slot_id) + Slot.pack(item),
                        )
            await asyncio.sleep(5.0)

    @listen_client(0x00, State.LOGIN, blocking=True)
    async def packet_login_start(self: ProxhyPlugin, buff: Buffer):
        self.username = buff.unpack(String)

        if not auth.user_exists(self.username):
            return await self.login()

        if auth.token_needs_refresh(self.username):
            return await self.login(reason="regen")

        try:
            reader, writer = await asyncio.open_connection(
                self.CONNECT_HOST[0], self.CONNECT_HOST[1]
            )
        except ConnectionRefusedError:
            if self.transferring_to_server:
                packet_id = 0x40  # client is on play state
                self.transferring_to_server = False
            else:
                packet_id = 0x00
            self.downstream.send_packet(
                packet_id,
                Chat.pack(
                    TextComponent(
                        f"Failed to connect to {self.CONNECT_HOST[0]}:{self.CONNECT_HOST[1]}"
                    ).color("red")
                ),
            )
            return await self.close()

        self.upstream = ServerStream(reader, writer)
        self.handle_upstream_task = asyncio.create_task(self.handle_upstream())

        if self.keep_alive_task:
            self.keep_alive_task.cancel()

        self.downstream.pause(discard=True)

        self.upstream.send_packet(
            0x00,
            VarInt.pack(47),
            String.pack(self.FAKE_CONNECT_HOST[0]),
            UnsignedShort.pack(self.FAKE_CONNECT_HOST[1]),
            VarInt.pack(State.LOGIN.value),
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
                    self.secret_task = self.create_task(
                        self._session_encrypt(server_id, public_key)
                    )

        self.upstream.send_packet(0x00, String.pack(self.username))

    async def _start_device_code_flow(self: ProxhyPlugin):
        try:
            device = await auth.request_device_code()

            self.downstream.chat(
                TextComponent("To log in, visit")
                .color("gold")
                .appends(
                    TextComponent(device["verification_uri"])
                    .color("aqua")
                    .click_event("open_url", device["verification_uri"])
                    .hover_text(TextComponent("Open in browser").color("yellow"))
                )
                .appends("and enter code")
                .appends(
                    TextComponent(device["user_code"])
                    .color("green")
                    .bold()
                    .click_event("suggest_command", device["user_code"])
                    .hover_text(
                        TextComponent("Copy")
                        .color("yellow")
                        .appends(
                            TextComponent(device["user_code"]).color("green").bold()
                        )
                    )
                )
            )

            def on_pending():
                pass

            try:
                access_token, username, uuid_ = await auth.complete_device_code_login(
                    device["device_code"],
                    interval=device.get("interval", 5),
                    expires_in=device.get("expires_in", 900),
                    on_pending=on_pending,
                )
            except auth.AuthException as e:
                if e.code == "XSTS-2148916233":
                    self.downstream.send_packet(
                        0x40,
                        Chat.pack(
                            TextComponent(
                                "This Microsoft account does not have a linked Minecraft account!"
                            ).color("red")
                        ),
                    )
                else:
                    self.downstream.send_packet(
                        0x40,
                        Chat.pack(
                            TextComponent("An unknown error occurred:")
                            .color("red")
                            .appends(TextComponent(str(e)))
                        ),
                    )
                return

            if username != self.username:
                self.downstream.send_packet(
                    0x40,
                    Chat.pack(
                        TextComponent("Wrong account! Logged into")
                        .color("red")
                        .appends(TextComponent(username).color("aqua"))
                        .append("; expected")
                        .appends(TextComponent(self.username).color("aqua"))
                    ),
                )
                return

            self.access_token = access_token
            self.uuid = uuid.UUID(uuid_)

            success_msg = TextComponent(
                f"Logged in! Redirecting to {self.CONNECT_HOST[0]}..."
            ).color("green")
            self.downstream.chat(success_msg)
            self.state = State.LOGIN
            self.transferring_to_server = True

            await self.packet_login_start(Buffer(String.pack(self.username)))

        except AuthException as e:
            self.downstream.chat(
                TextComponent(f"Authentication failed: {e}").color("red")
            )

    async def login_keep_alive(self: ProxhyPlugin):
        while True:
            await asyncio.sleep(10)
            if self.state == State.PLAY and self.downstream.open and self.logging_in:
                self.downstream.send_packet(0x00, VarInt.pack(random.randint(0, 256)))
            else:
                await self.close()
                break

    @listen_client(0x00, State.HANDSHAKING, blocking=True)
    async def packet_handshake(self: ProxhyPlugin, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)

    async def login(
        self: ProxhyPlugin, reason: Literal["logging_in", "regen"] = "logging_in"
    ):
        # immediately send login start to enter login server
        self.state = State.PLAY
        self.logging_in = True

        # fake server stream
        self.upstream = Mock()

        try:
            _, _, uuid_ = await auth.load_auth_info(
                self.username, refresh_if_expired=False
            )
        except RuntimeError:
            try:
                async with hypixel.Client(timeout=5) as c:
                    uuid_ = await c.get_uuid(self.username)
            except Exception as e:
                self.downstream.send_packet(
                    0x40,
                    Chat.pack(
                        TextComponent(f"Failed to fetch your UUID! ({e!r})").color(
                            "dark_red"
                        )
                    ),
                )
                await self.close()

        self.downstream.send_packet(
            0x02, String.pack(str(uuid_)), String.pack(self.username)
        )

        self.downstream.send_packet(
            0x01,
            Int.pack(0),
            UnsignedByte.pack(3),
            Byte.pack(b"\x01"),
            UnsignedByte.pack(0),
            UnsignedByte.pack(1),
            String.pack("default"),
            Boolean.pack(True),
        )

        self.downstream.send_packet(
            0x08,
            Double.pack(0),
            Double.pack(0),
            Double.pack(0),
            Float.pack(0),
            Float.pack(0),
            Byte.pack(b"\x00"),
        )

        self.keep_alive_task = self.create_task(self.login_keep_alive())

        if reason == "logging_in":
            self.downstream.chat(
                "You have not logged into Proxhy with this account yet!"
            )
            self.device_code_task = self.create_task(self._start_device_code_flow())
        else:
            self.regenerating_credentials = True
            self.downstream.set_title(
                title=TextComponent("Please Wait").color("red"),
                subtitle=TextComponent("You will be redirected to")
                .color("white")
                .appends(TextComponent(self.CONNECT_HOST[0]).color("gold"))
                .appends(TextComponent("soon!").color("white")),
                duration=200,
            )
            self.downstream.chat(
                TextComponent("Regenerating credentials; you will be redirected to")
                .color("yellow")
                .appends(TextComponent(self.CONNECT_HOST[0]).color("green"))
                .appends(TextComponent("soon!").color("yellow"))
            )
            try:
                self.access_token, self.username, self.uuid = await auth.load_auth_info(
                    self.username
                )
            except Exception as e:
                return self.downstream.send_packet(
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
            self.downstream.reset_title()
            self.downstream.chat(success_msg)
            self.state = State.LOGIN

            await self.packet_login_start(Buffer(String.pack(self.username)))

    @listen_client(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self: ProxhyPlugin, _):
        self.downstream.send_packet(
            0x00, String.pack(orjson.dumps(self.server_list_ping).decode())
        )

    @listen_client(0x01, State.STATUS, blocking=True)
    async def packet_ping_request(self: ProxhyPlugin, buff: Buffer):
        self.downstream.send_packet(0x01, buff.getvalue())
        # close connection
        await self.close()

    @listen_server(0x03, State.LOGIN, blocking=True)
    async def packet_set_compression(self: ProxhyPlugin, buff: Buffer):
        self.upstream.compression_threshold = buff.unpack(VarInt)
        self.upstream.compression = (
            False if self.upstream.compression_threshold == -1 else True
        )

    @listen_server(0x01, State.LOGIN, blocking=True)
    async def packet_encryption_request(self: ProxhyPlugin, buff: Buffer):
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

        self.upstream.send_packet(
            0x01,
            ByteArray.pack(encrypted_secret),
            ByteArray.pack(encrypted_verify_token),
        )

        # enable encryption
        self.upstream.key = self.secret

    async def _session_encrypt(
        self: ProxhyPlugin, server_id: bytes, public_key: bytes
    ) -> bytes:
        # generate shared secret
        secret = token_bytes(16)

        has_uuid = True
        try:
            self.uuid
        except AttributeError:
            has_uuid = False

        if not (self.access_token or has_uuid):
            self.access_token, self.username, self.uuid = await auth.load_auth_info(
                self.username
            )

        payload = {
            "accessToken": self.access_token,
            "selectedProfile": str(self.uuid),
            "serverId": generate_verification_hash(server_id, secret, public_key),
        }
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                "https://sessionserver.mojang.com/session/minecraft/join",
                json=payload,
            )
            if response.status_code != 204:
                # TODO: log
                raise Exception(
                    f"Login failed: {response.status_code} {response.json()}"
                )

        return secret

    @subscribe("login_success")
    async def _login_start_armor_stand_task(self: ProxhyPlugin, _match, _data):
        self.create_task(self._resend_armor_stands())

    @subscribe("login_success")
    async def _broadcast_event_login_success(self: ProxhyPlugin, _match, _data):
        if self.dev_mode:
            self.downstream.chat(
                TextComponent("==> Dev Mode Activated <==").color("green").bold()
            )

            return

        if self.settings.update_check.get() == "ON":
            self.create_task(self._check_for_update())

    async def _check_for_update(self: ProxhyPlugin):
        async with httpx.AsyncClient() as aclient:
            current = utils.zero_pad_calver(version("proxhy"))
            latest = (
                (
                    await aclient.get(
                        "https://api.github.com/repos/kbidlack/proxhy/releases/latest"
                    )
                )
                .json()
                .get("name")
            )

        base_url = "https://github.com/kbidlack/proxhy/releases/tag/v{}"
        current_url = base_url.format(current)
        latest_url = base_url.format(latest)

        if latest and current != latest:
            self.downstream.chat(
                TextComponent("A new version of Proxhy is available!")
                .appends(TextComponent("(").color("gray"))
                .append(
                    TextComponent(current)
                    .hover_text(
                        TextComponent(f"Click to view v{current} on GitHub").color(
                            "yellow"
                        )
                    )
                    .click_event("open_url", current_url)
                    .color("white")
                )
                .append(TextComponent(" → ").color("gray"))
                .append(
                    TextComponent(latest)
                    .hover_text(
                        TextComponent(f"Click to view v{latest} on GitHub").color(
                            "yellow"
                        )
                    )
                    .click_event("open_url", latest_url)
                    .color("green")
                )
                .append(TextComponent(")").color("gray"))
            )
            self.downstream.chat(
                TextComponent("- See the")
                .color("gray")
                .appends(
                    TextComponent("README")
                    .click_event(
                        "open_url",
                        "https://github.com/kbidlack/proxhy?tab=readme-ov-file#upgrading",
                    )
                    .hover_text(
                        TextComponent("Open the README on GitHub").color("yellow")
                    )
                    .bold()
                )
                .appends("for how to update Proxhy.")
            )
