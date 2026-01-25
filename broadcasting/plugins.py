import asyncio
import json
import uuid
from typing import Literal, Optional
from unittest.mock import Mock

import hypixel
import pyroh

from core.events import listen_client as listen
from core.events import subscribe
from core.proxy import State
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
from proxhy.argtypes import ServerPlayer
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.gamestate import PlayerAbilityFlags

from .plugin import BroadcastPeerPlugin


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
        self.flight: Literal[0, PlayerAbilityFlags.ALLOW_FLYING] = (
            PlayerAbilityFlags.ALLOW_FLYING
        )  # alternatively 0 if off
        self.flying: Literal[0, PlayerAbilityFlags.FLYING]

    @subscribe("chat:client:.*")
    async def _broadcast_peer_base_event_chat_client_any(self, buff: Buffer):
        msg = buff.unpack(String)
        if msg.startswith("/"):
            return  # command plugin

        self.proxy.bc_chat(self.username, msg)

    @subscribe("close")
    async def _broadcast_peer_base_event_close(self, _):
        # remove this client
        if self in self.proxy.clients:
            self.proxy.clients.remove(self)  # pyright: ignore[reportArgumentType]

        try:
            self.writer.close()
            await asyncio.wait_for(self.writer.wait_closed(), timeout=0.5)
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

        # Play UI click sound at low pitch for leave
        self.proxy._play_sound("random.click", pitch=40)

        self.proxy.client.send_packet(
            0x38,
            VarInt.pack(4),  # action: remove player
            VarInt.pack(1),  # number of players
            UUID.pack(uuid.UUID(self.uuid)),
        )

    @listen(0x0B)
    async def packet_entity_action(self, buff: Buffer):
        if eid := buff.unpack(VarInt) != self.eid:
            print(
                f"0x0B: Sent EID and self EID mismatch? {eid} / {self.eid}"
            )  # TODO: log this
            return

        action_id = buff.unpack(VarInt)
        if action_id == 0 and self.spec_eid is not None:
            await self._command_spectate(None)

    @command("spectate", "spec")
    async def _command_spectate(self, target: ServerPlayer | None = None) -> None:
        if target is None:
            if self.spec_eid is not None:
                self.client.send_packet(0x43, VarInt.pack(self.eid))
                self.spec_eid = None
                return
            else:
                raise CommandException("Please provide a target player!")

        # check if it's the spectator themselves (reset spectate mode)
        if target.name.casefold() == self.username.casefold():
            if self.spec_eid is None:
                raise CommandException("You are not spectating anyone!")
            self.client.send_packet(0x43, VarInt.pack(self.eid))
            self.spec_eid = None
            return

        # check if it's the broadcasting player (compare by username since UUIDs
        # may differ between auth and server in offline/local mode)
        if target.name.casefold() == self.proxy.username.casefold():
            # use transformer's player_eid, not gamestate's - the transformer
            # spawns the owner with a different entity ID for spectators
            eid = self.proxy._transformer.player_eid
        else:
            # another player -- check that they're spawned nearby
            if target.uuid is None:
                raise CommandException(f"Player '{target.name}' is not nearby!")
            player = self.proxy.gamestate.get_player_by_uuid(target.uuid)
            if not player:
                raise CommandException(f"Player '{target.name}' is not nearby!")
            eid = player.entity_id

        self.spec_eid = eid
        self.client.send_packet(0x43, VarInt.pack(eid))

    @command("tp", "teleport")
    async def _command_tp(
        self,
        target: ServerPlayer | float,
        y: float | None = None,
        z: float | None = None,
    ) -> TextComponent:
        if isinstance(target, ServerPlayer):
            # compare by username since UUIDs may differ in offline/local mode
            if target.name.casefold() == self.proxy.username.casefold():
                pos = self.proxy.gamestate.position
            else:
                # another player, check that they're spawned nearby
                if target.uuid is None:
                    raise CommandException(
                        TextComponent("Player '")
                        .append(TextComponent(target.name).color("gold"))
                        .append("' is not nearby!")
                    )
                entity = self.proxy.gamestate.get_player_by_uuid(target.uuid)
                if not entity:
                    raise CommandException(
                        TextComponent("Player '")
                        .append(TextComponent(target.name).color("gold"))
                        .append("' is not nearby!")
                    )
                pos = entity.position

            self.client.send_packet(
                0x08,
                Double.pack(pos.x),
                Double.pack(pos.y),
                Double.pack(pos.z),
                Float.pack(self.proxy.gamestate.rotation.yaw),
                Float.pack(self.proxy.gamestate.rotation.pitch),
                Byte.pack(0),  # flags: all absolute
            )
            return (
                TextComponent("Teleported to ")
                .color("green")
                .append(TextComponent(target.name).color("aqua"))
            )

        # target is a float (x coordinate)
        x = target
        if y is None or z is None:
            raise CommandException(
                "Position teleport requires x, y, and z coordinates!"
            )
        self.client.send_packet(
            0x08,
            Double.pack(x),
            Double.pack(y),
            Double.pack(z),
            Float.pack(self.proxy.gamestate.rotation.yaw),
            Float.pack(self.proxy.gamestate.rotation.pitch),
            Byte.pack(0),  # flags: all absolute
        )
        return (
            TextComponent("Teleported to ")
            .color("green")
            .append(TextComponent(f"{x:.1f}, {y:.1f}, {z:.1f}").color("gold"))
        )

    @command("fly")
    async def _command_fly(self):
        if self.flight == PlayerAbilityFlags.ALLOW_FLYING:
            self.flight = 0
            self.flying = 0
        else:  # self.flight == 0
            self.flight = PlayerAbilityFlags.ALLOW_FLYING

        self.client.send_packet(
            0x39,
            Byte.pack(PlayerAbilityFlags.INVULNERABLE | self.flying | self.flight)
            + Float.pack(self.proxy.gamestate.flying_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

        return TextComponent(f"Turned flight {'on' if self.flight else 'off'}!").color(
            "green"
        )


class BroadcastPeerLoginPlugin(BroadcastPeerPlugin):
    flight: Literal[0, PlayerAbilityFlags.ALLOW_FLYING]
    flying: Literal[0, PlayerAbilityFlags.FLYING]

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
            + Float.pack(self.proxy.gamestate.flying_speed)
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
        abilities_flags = int(PlayerAbilityFlags.INVULNERABLE | self.flight)
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
