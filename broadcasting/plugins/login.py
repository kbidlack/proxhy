import asyncio
import json
import uuid
from unittest.mock import Mock

import pyroh

from broadcasting.plugin import BroadcastPeerPlugin
from core.events import listen_client as listen
from core.net import Server
from core.proxy import State
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
from proxhy.gamestate import PlayerAbilityFlags
from proxhy.utils import _Client


class BroadcastPeerLoginPluginState:
    writer: pyroh.StreamWriter
    username: str


class BroadcastPeerLoginPlugin(BroadcastPeerPlugin):
    def _init_login(self):
        self.server = Server(reader=Mock(), writer=Mock())

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
            self.flying = PlayerAbilityFlags.FLYING
            # INVULNERABLE | FLYING | ALLOW_FLYING
            abilities_flags = int(
                PlayerAbilityFlags.INVULNERABLE | self.flying | self.flight
            )
        else:
            self.flying = 0
            # INVULNERABLE | ALLOW_FLYING
            abilities_flags = int(PlayerAbilityFlags.INVULNERABLE | self.flight)

        self.client.send_packet(
            0x39,
            Byte.pack(abilities_flags)
            + Float.pack(self.flight_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

        await self.client.drain()

    @listen(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        self.username = buff.unpack(String)
        if self.username in self.proxy.broadcast_requests:
            # might not be if joining by ID
            self.proxy.broadcast_requests.remove(self.username)

        self.proxy.client.chat(
            TextComponent(self.username)
            .color("aqua")
            .appends(TextComponent("is joining the broadcast...").color("yellow"))
        )
        self.proxy._play_sound("random.click")

        # send login success packet
        # TODO: support server support. this + login encryption will come back then
        # self.client.send_packet(
        #     0x02, String.pack(self.uuid), String.pack(self.username)
        # )
        await self.emit("login_success")

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

        async with _Client() as c:
            try:
                async with asyncio.timeout(2):
                    self.uuid = str(uuid.UUID(await c._get_uuid(self.username)))
                    self.skin_properties = await c.get_skin_properties(self.uuid)
            except asyncio.TimeoutError:
                self.proxy.client.chat(
                    TextComponent("Failed to fetch uuid for")
                    .color("red")
                    .appends(TextComponent(self.username).color("aqua"))
                )
                self.uuid = str(uuid.uuid4())
                self.skin_properties = None

        self.state = State.PLAY

        # set compression
        # we are using 'broken' 0x46 packet because why not and because I can
        # I guess I could use a plugin channel but that's like so much effort
        # TODO: this needs logic for non proxhy broadcastees, in which compression
        # should be set with the login packet (0x03)
        self.client.compression_threshold = 256
        self.client.send_packet(0x46, VarInt.pack(self.client.compression_threshold))
        await self.client.drain()
        self.client.compression = True

        properties_data = b""
        if self.skin_properties:
            properties_data = VarInt.pack(len(self.skin_properties))
            for prop in self.skin_properties:
                properties_data += String.pack(prop.get("name", ""))
                properties_data += String.pack(prop.get("value", ""))
                has_sig = prop.get("signature") is not None
                properties_data += Boolean.pack(has_sig)
                if has_sig:
                    properties_data += String.pack(prop["signature"])
        else:
            properties_data = VarInt.pack(0)

        for packet_id, packet_data in packets[1:]:
            self.client.send_packet(packet_id, packet_data)

        # respawn back to actual dimension
        self.client.send_packet(
            0x07,
            Int(current_dim),
            UnsignedByte.pack(self.proxy.gamestate.difficulty.value),
            UnsignedByte.pack(2),  # gamemode: adventure
            String.pack(self.proxy.gamestate.level_type),
        )

        # Resend player list, entity spawns, metadata, and equipment after respawn
        for packet_id, packet_data in packets[1:]:
            if packet_id in (0x38, 0x0C, 0x0E, 0x0F, 0x1C, 0x04, 0x19, 0x3E):
                # 0x38 = Player List Item
                # 0x0C = Spawn Player
                # 0x0E = Spawn Object
                # 0x0F = Spawn Mob
                # 0x1C = Entity Metadata
                # 0x19 = Entity Head Look
                # 0x04 = Entity Equipment
                # 0x3E = Teams (for NPC nametag prefixes/suffixes)
                self.client.send_packet(packet_id, packet_data)

        self.client.send_packet(
            0x38,
            VarInt.pack(0),  # action: add player
            VarInt.pack(1),  # number of players
            UUID.pack(uuid.UUID(self.uuid)),
            String.pack(self.username),
            properties_data,
            VarInt.pack(2),  # gamemode: adventure
            VarInt.pack(0),  # ping
            Boolean.pack(False),  # no display name for self
        )

        self.proxy._spawn_player_for_client(self)  # type: ignore[arg-type]

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
        abilities_flags = int(PlayerAbilityFlags.INVULNERABLE | self.flight)
        self.client.send_packet(
            0x39,
            Byte.pack(abilities_flags)
            + Float.pack(self.flight_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

        await self.client.drain()

        # Schedule delayed NPC removal from tab list to allow skin loading
        asyncio.create_task(self._delayed_npc_removal())

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
            String.pack(self.username),
            properties_data,
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

    async def _delayed_npc_removal(self) -> None:
        """Remove NPCs from tab list after a delay to allow skin loading."""
        await asyncio.sleep(1.5)
        self.client.send_packet(*self.proxy.gamestate._build_npc_removal_packet())
