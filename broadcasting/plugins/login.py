import asyncio
import uuid
from unittest.mock import Mock

import orjson
import pyroh

from broadcasting.plugin import BroadcastPeerPlugin
from core.events import listen_client as listen
from core.events import subscribe
from core.net import Server
from core.proxy import State
from gamestate.state import PlayerAbilityFlags
from protocol.datatypes import (
    UUID,
    Boolean,
    Buffer,
    Byte,
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
from proxhy.utils import APIClient, offline_uuid, uuid_version


class BroadcastPeerLoginPluginState:
    writer: pyroh.StreamWriter
    username: str
    compression_ready: asyncio.Event


class BroadcastPeerLoginPlugin(BroadcastPeerPlugin):
    def _init_login(self):
        self.server = Server(reader=Mock(), writer=Mock())
        self.compression_ready = asyncio.Event()

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

        self.client.send_packet(
            0x00, String.pack(orjson.dumps(self.server_list_ping).decode())
        )

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

    @listen(0x46, blocking=True)
    async def _packet_compression_ack(self, _: Buffer):
        self.compression_ready.set()

    @listen(0x00, State.LOGIN)
    async def packet_login_start(self, buff: Buffer):
        self.state = State.PLAY
        self.username = buff.unpack(String)

        self.uuid = str(offline_uuid(self.username))
        self.skin_properties = None
        profile_ready = asyncio.Event()

        async def fetch_profile():
            try:
                async with APIClient() as c:
                    async with asyncio.timeout(2):
                        self.uuid = str(uuid.UUID(await c._get_uuid(self.username)))
                        self.skin_properties = await c.get_skin_properties(self.uuid)
            except asyncio.TimeoutError:
                self.proxy.client.chat(
                    TextComponent("Failed to fetch uuid for")
                    .color("dark_red")
                    .appends(TextComponent(self.username).color("gold"))
                )
            finally:
                profile_ready.set()

        if uuid_version(self.proxy.gamestate.player_uuid) == 3:
            profile_ready.set()
        else:
            asyncio.create_task(fetch_profile())

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
            Int.pack(fake_dim),
            UnsignedByte.pack(self.proxy.gamestate.difficulty.value),
            UnsignedByte.pack(2),  # gamemode: adventure
            String.pack(self.proxy.gamestate.level_type),
        )

        # includes join game
        packets = self.proxy.gamestate.sync_broadcast_spectator(self.eid)
        self.client.send_packet(*packets[0])  # join game

        # respawn back to actual dimension
        self.client.send_packet(
            0x07,
            Int.pack(current_dim),
            UnsignedByte.pack(self.proxy.gamestate.difficulty.value),
            UnsignedByte.pack(2),  # gamemode: adventure
            String.pack(self.proxy.gamestate.level_type),
        )

        # send player pos and look after respawn to set correct pos
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

        # set compression
        # we are using 'broken' 0x46 packet because why not and because I can
        # I guess I could use a plugin channel but that's like so much effort
        # TODO: this needs logic for non proxhy broadcastees, in which compression
        # should be set with the login packet (0x03)
        self.client.compression_threshold = 256
        # cb is set, sb is ack
        self.client.send_packet(0x46, VarInt.pack(self.client.compression_threshold))
        await self.compression_ready.wait()
        self.client.compression = True

        for packet_id, packet_data in packets[1:]:
            self.client.send_packet(packet_id, packet_data)

        # now add to clients list - sync is complete, safe to send packets
        self.proxy.clients.append(self)  # type: ignore[arg-type]

        self.proxy.client.chat(
            TextComponent(self.username)
            .color("aqua")
            .appends(TextComponent("joined the broadcast!").color("green"))
        )

        self.client.send_packet(
            0x3F, String.pack("PROXHY|Events"), String.pack("login_success")
        )

        await self.emit("login_success")
        # resend player abilities (allow flying in adventure mode) so respawn doesn't clear them
        # needs to be after login success to get flight_speed
        abilities_flags = int(PlayerAbilityFlags.INVULNERABLE | self.flight)
        self.client.send_packet(
            0x39,
            Byte.pack(abilities_flags)
            + Float.pack(self.flight_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

        await self.client.drain()

        await profile_ready.wait()
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

        display_name = (
            TextComponent("[")
            .color("dark_gray")
            .append(TextComponent("BROADCAST").color("red"))
            .append(TextComponent("]").color("dark_gray"))
            .appends(TextComponent(f"{self.username}").color("aqua"))
        )
        self.client.send_packet(
            0x38,
            VarInt.pack(0),  # action: add player
            VarInt.pack(1),  # number of players
            UUID.pack(uuid.UUID(self.uuid)),
            String.pack(self.username),
            properties_data,
            VarInt.pack(2),  # gamemode: adventure
            VarInt.pack(0),  # ping
            Boolean.pack(True),  # no display name for self
            Chat.pack(display_name),
        )

        self.proxy._spawn_player_for_client(self)  # type: ignore[arg-type]

    async def _delayed_npc_removal(self) -> None:
        """Remove NPCs from tab list after a delay to allow skin loading."""
        await asyncio.sleep(1.5)
        self.client.send_packet(*self.proxy.gamestate._build_npc_removal_packet())

    @subscribe("login_success")
    async def _broadcast_peer_start_armor_stand_task(self, _match, _data):
        self.create_task(self._resend_armor_stands_peer())

    async def _resend_armor_stands_peer(self):
        await asyncio.sleep(1.0)
        while self.open and self.client.open:
            for entity in list(self.proxy.gamestate.entities.values()):
                if entity.entity_type != 78:
                    continue

                eid = entity.entity_id
                # destroy first
                self.client.send_packet(0x13, VarInt.pack(1) + VarInt.pack(eid))
                packet_id, packet_data = self.proxy.gamestate._build_spawn_object(
                    entity
                )
                self.client.send_packet(packet_id, packet_data)
                if entity.metadata:
                    self.client.send_packet(
                        0x1C,
                        VarInt.pack(eid)
                        + self.proxy.gamestate._pack_metadata(entity.metadata),
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
                        self.client.send_packet(
                            0x04,
                            VarInt.pack(eid) + Short.pack(slot_id) + Slot.pack(item),
                        )
            await asyncio.sleep(5.0)
