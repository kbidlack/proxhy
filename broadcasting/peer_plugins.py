import asyncio
import json
import uuid
from typing import TYPE_CHECKING, Optional
from unittest.mock import Mock

import hypixel
import pyroh

from core.events import listen_client as listen
from core.events import subscribe
from core.plugin import Plugin
from core.proxy import Proxy, State
from plugins.chat import ChatPlugin
from plugins.commands import CommandsPlugin
from protocol.datatypes import (
    Buffer,
    Byte,
    Double,
    Float,
    Int,
    String,
    TextComponent,
    UnsignedByte,
    UnsignedShort,
    VarInt,
)
from proxhy.command import command
from proxhy.errors import CommandException

if TYPE_CHECKING:
    from proxhy.proxhy import Proxhy


class BroadcastPeerPlugin(Plugin):
    proxy: Proxhy
    eid: int


class BroadcastPeerCommandsPlugin(CommandsPlugin):
    @listen(0x14)
    async def packet_tab_complete(self, buff: Buffer):
        # reuse packet tab complete logic, but fake server response
        await super().packet_tab_complete(buff)
        # VarInt(0) => server response of 0 sugggestions
        # tells parent plugin to send it's only suggestions
        await super().packet_server_tab_complete(Buffer(VarInt(0)))


class BroadcastPeerBasePlugin(BroadcastPeerPlugin):
    username: str
    writer: pyroh.StreamWriter
    # base functionality

    def _init_base(self):
        self.spec_eid: Optional[int] = None

    @subscribe("chat:client:.*")
    async def on_any_client_chat(self, buff: Buffer):
        msg = buff.unpack(String)
        if msg.startswith("/"):
            return  # command plugin

        self.proxy.bc_chat(self.username, msg)

    @subscribe("close")
    async def _close_broadcast_peer(self, _):
        # remove this client
        if self in self.proxy.clients:
            self.proxy.clients.remove(self)  # pyright: ignore[reportArgumentType]

        try:
            await asyncio.wait_for(self.writer.aclose(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        try:
            self.username
        except AttributeError:
            # username not set; handshake only?
            return

        self.proxy.client.chat(
            TextComponent(self.username)
            .color("aqua")
            .appends(TextComponent("left the broadcast!").color("red"))
        )

    @command("spec")
    async def spectate(self, target: str = ""):
        if not target:
            if self.spec_eid:
                return self.client.send_packet(0x43, VarInt.pack(self.eid))
            else:
                raise CommandException("Please provide a target player!")

        player_uuid = next(
            (
                uuid
                for (uuid, pi) in self.proxy.gamestate.player_list.items()
                if pi.name.lower() == target.lower()
            ),
            "",
        )

        if not player_uuid:
            self.client.chat(
                TextComponent(f"Player '{target}' not found!").color("red")
            )
            return

        # check if it's the broadcasting player
        if player_uuid == self.proxy.uuid:
            eid = self.proxy.gamestate.player_entity_id
        else:
            # another player -- check that they're spawned nearby
            player = self.proxy.gamestate.get_player_by_uuid(player_uuid)
            if not player:
                self.client.chat(
                    TextComponent(f"Player '{target}' is not nearby!").color("red")
                )
                return
            eid = player.entity_id

        self.spec_eid = eid
        self.client.send_packet(0x43, VarInt.pack(eid))


class BroadcastPeerLoginPlugin(BroadcastPeerPlugin):
    def _init_login(self):
        self.server = Mock()  # HACK

        self.server_list_ping = {
            "version": {"name": "1.8.9", "protocol": 47},
            "players": {
                "max": 10,
                "online": 0,
            },
            "description": {"text": f"Join the broadcast on {self.CONNECT_HOST[0]}!"},
        }

    @listen(0x00, State.HANDSHAKING, blocking=True, override=True)
    async def packet_handshake(self, buff: Buffer):
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        self.state = State(next_state)

    @listen(0x00, State.STATUS, blocking=True)
    async def packet_status_request(self, _):
        self.server_list_ping["players"]["online"] = len(
            [c for c in self.proxy.clients if hasattr(c, "username")]
        )
        self.server_list_ping["description"]["text"] = (
            f"Join {self.proxy.username}'s broadcast on {self.CONNECT_HOST[0]}!"
            # since we get self.proxy after plugin init function runs
        )

        self.client.send_packet(0x00, String(json.dumps(self.server_list_ping)))

    @listen(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        self.username = buff.unpack(String)

        # send login success packet
        # TODO: support server support. this + login encryption will come back then
        # self.client.send_packet(
        #     0x02, String.pack(self.uuid), String.pack(self.username)
        # )

        # send respawn to a different dimension first,
        # then join, then respawn back. this forces the client to properly
        # clear its state and reinitialize. idk why man. its stupid
        current_dim = self.proxy.gamestate.dimension.value
        # use end as fake dimension if in overworld/nether, otherwise use overworld
        # so we always switch to a different dimension
        # ts so complicated bruh
        fake_dim = 1 if current_dim in (0, -1) else 0

        self.client.send_packet(
            0x07,  # respawn
            Int(fake_dim),
            UnsignedByte.pack(self.proxy.gamestate.difficulty.value),
            UnsignedByte.pack(3),  # gamemode: spectator
            String.pack(self.proxy.gamestate.level_type),
        )

        # includes join game
        packets = self.proxy.gamestate.sync_spectator(self.eid)
        self.client.send_packet(*packets[0])  # join game
        await self.client.drain()

        async with hypixel.Client() as c:
            self.uuid = str(uuid.UUID(await c._get_uuid(self.username)))

        self.state = State.PLAY

        for packet_id, packet_data in packets[1:]:
            self.client.send_packet(packet_id, packet_data)

        self.proxy._spawn_player_for_client(self)  # type: ignore[arg-type]

        # respawn back to actual dimension
        self.client.send_packet(
            0x07,
            Int(current_dim),
            UnsignedByte.pack(self.proxy.gamestate.difficulty.value),
            UnsignedByte.pack(3),  # gamemode: spectator
            String.pack(self.proxy.gamestate.level_type),
        )

        # send player pos and look again after respawn to set correct pos
        # ig respawn can reset player's position
        pos = self.proxy.gamestate.position
        rot = self.proxy.gamestate.rotation
        self.client.send_packet(
            0x08,
            Double.pack(pos.x),
            Double.pack(pos.y),
            Double.pack(pos.z),
            Float.pack(rot.yaw),
            Float.pack(rot.pitch),
            Byte.pack(0),  # flags: all absolute
        )

        await self.client.drain()

        # now add to clients list - sync is complete, safe to send packets
        self.proxy.clients.append(self)  # type: ignore[arg-type]

        self.proxy.client.chat(
            TextComponent(self.username)
            .color("aqua")
            .appends(TextComponent("joined the broadcast!").color("green"))
        )


# "proxy" for any connected broadcast clients
# we are just reusing proxy code and then omitting the server
# to be able to take advantage of all the prebuilt plugins
# and packet handling stuff from proxy, just for a client connection
broadcast_peer_plugins: tuple[type, ...] = (
    ChatPlugin,
    BroadcastPeerLoginPlugin,
    BroadcastPeerBasePlugin,
    BroadcastPeerCommandsPlugin,
)

BroadcastPeerProxy = type("BroadcastPeerProxy", (*broadcast_peer_plugins, Proxy), {})
