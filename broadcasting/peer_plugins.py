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
    UUID,
    Boolean,
    Buffer,
    Byte,
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
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.gamestate import PlayerAbilityFlags

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

    def _init_broadcast_peer(self):
        self.uuid = ""
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

        self.proxy.client.send_packet(
            0x38,
            VarInt.pack(4),  # action: remove player
            VarInt.pack(1),  # number of players
            UUID.pack(uuid.UUID(self.uuid)),
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

    @listen(0x13)
    async def packet_serverbound_player_abilities(self, buff: Buffer):
        flags = PlayerAbilityFlags(buff.unpack(Byte))

        # if server/player is flying, include flying in outgoing packet
        # otherwise leave it unset so broadcast clients can return to grounded state
        if flags & PlayerAbilityFlags.FLYING:  # flying
            # INVULNERABLE | FLYING | ALLOW_FLYING
            abilities_flags = int(
                PlayerAbilityFlags.INVULNERABLE
                | PlayerAbilityFlags.FLYING
                | PlayerAbilityFlags.ALLOW_FLYING
            )
        else:
            # INVULNERABLE | ALLOW_FLYING
            abilities_flags = int(
                PlayerAbilityFlags.INVULNERABLE | PlayerAbilityFlags.ALLOW_FLYING
            )

        self.client.send_packet(
            0x39,
            Byte.pack(abilities_flags)
            + Float.pack(self.proxy.gamestate.flying_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

        await self.client.drain()

    @listen(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        self.username = buff.unpack(String)
        self.proxy.broadcast_requests.remove(self.username)

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

        players_before = self.proxy.gamestate.player_list.copy()

        # snapshot entity ids for the players currently known
        # we capture these BEFORE any operations that might remove players so we
        # can still reference their entity IDs even if they're removed later
        player_entity_ids_before: dict[str, int] = {}
        for puuid in players_before.keys():
            try:
                normalized = str(uuid.UUID(puuid))
            except Exception:
                normalized = puuid

            player = self.proxy.gamestate.get_player_by_uuid(normalized)
            if not player:
                player = self.proxy.gamestate.get_player_by_uuid(puuid)
            if player:
                player_entity_ids_before[normalized] = player.entity_id
                player_entity_ids_before[puuid] = player.entity_id

        self.client.send_packet(
            0x07,  # respawn
            Int(fake_dim),
            UnsignedByte.pack(self.proxy.gamestate.difficulty.value),
            UnsignedByte.pack(2),  # gamemode: adventure
            String.pack(self.proxy.gamestate.level_type),
        )

        # includes join game
        packets = self.proxy.gamestate.sync_broadcast_spectator(self.eid)
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
            UnsignedByte.pack(2),  # gamemode: adventure
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

        # resend player abilities (allow flying in adventure mode) so respawn doesn't clear them
        abilities_flags = int(
            PlayerAbilityFlags.INVULNERABLE | PlayerAbilityFlags.ALLOW_FLYING
        )
        self.client.send_packet(
            0x39,
            Byte.pack(abilities_flags)
            + Float.pack(self.proxy.gamestate.flying_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

        await self.client.drain()

        # now add to clients list - sync is complete, safe to send packets
        self.proxy.clients.append(self)  # type: ignore[arg-type]

        self.proxy.client.chat(
            TextComponent(self.username)
            .color("aqua")
            .appends(TextComponent("joined the broadcast!").color("green"))
        )
        display_name = (
            TextComponent("[")
            .color("dark_gray")
            .append(TextComponent("BROADCAST").color("red"))
            .append(TextComponent("]").color("dark_gray"))
            .appends(TextComponent(f"{self.username}").color("aqua"))
        )
        self.proxy.client.send_packet(
            0x38,
            VarInt.pack(0),  # action: add player
            VarInt.pack(1),  # number of players
            UUID.pack(uuid.UUID(self.uuid)),
            String.pack(self.username),  # player name with prefix
            VarInt.pack(0),  # properties count
            VarInt.pack(2),  # gamemode: adventure
            VarInt.pack(0),  # ping
            Boolean.pack(True),  # has display name
            Chat.pack(display_name),
        )

        players_after = self.proxy.gamestate.player_list.copy()
        player_diff = players_before.keys() - players_after.keys()

        self.proxy.client.send_packet(
            0x38,
            VarInt.pack(4),  # remove
            VarInt.pack(len(player_diff)),
            *(UUID.pack(uuid.UUID(u)) for u in player_diff),
        )

        entity_ids: list[int] = []
        for u in player_diff:
            try:
                normalized = str(uuid.UUID(u))
            except Exception:
                normalized = u

            eid = player_entity_ids_before.get(normalized)
            if eid is None:
                eid = player_entity_ids_before.get(u)
            if eid is not None:
                entity_ids.append(eid)

        if entity_ids:
            data = VarInt.pack(len(entity_ids)) + b"".join(
                VarInt.pack(eid) for eid in entity_ids
            )
            self.proxy.client.send_packet(0x13, data)


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
