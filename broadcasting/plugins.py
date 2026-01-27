import asyncio
import json
import re
import uuid
from typing import Any, Callable, Coroutine, Literal, Optional
from unittest.mock import Mock

import pyroh

from core.events import listen_client as listen
from core.events import subscribe
from core.net import Server
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
    Short,
    Slot,
    SlotData,
    String,
    TextComponent,
    UnsignedByte,
    UnsignedShort,
    VarInt,
)
from proxhy.argtypes import ServerPlayer
from proxhy.command import Command, CommandGroup, command
from proxhy.errors import CommandException
from proxhy.gamestate import PlayerAbilityFlags
from proxhy.utils import _Client

from .plugin import BroadcastPeerPlugin


class BroadcastPeerCommandsPlugin(BroadcastPeerPlugin, CommandsPlugin):
    async def _run_command(self, message: str):
        segments = message.split()
        cmd_name = segments[0].removeprefix("/").removeprefix("/").casefold()

        command: Optional[Command | CommandGroup] = self.command_registry.get(cmd_name)

        if command:
            try:
                args = segments[1:]
                output: str | TextComponent = await command(self, args)
            except CommandException as err:
                if isinstance(err.message, TextComponent):
                    err.message.flatten()

                    for i, child in enumerate(err.message.get_children()):
                        if not child.data.get("color"):
                            err.message.replace_child(i, child.color("dark_red"))
                        if not child.data.get("bold"):
                            err.message.replace_child(i, child.bold(False))

                err.message = TextComponent(err.message)
                if not err.message.data.get("color"):
                    err.message.color("dark_red")

                err.message = err.message.bold(False)

                error_msg = TextComponent("∎ ").bold().color("blue").append(err.message)
                if error_msg.data.get("clickEvent") is None:
                    error_msg = error_msg.click_event("suggest_command", message)
                if error_msg.data.get("hoverEvent") is None:
                    error_msg = error_msg.hover_text(message)

                self.client.chat(error_msg)
            else:
                if output:
                    if segments[0].startswith("//"):  # send output of command
                        # remove chat formatting
                        output = re.sub(r"§.", "", str(output))
                        self.proxy.bc_chat(self.username, output)
                    else:
                        if isinstance(output, TextComponent):
                            if output.data.get("clickEvent") is None:
                                output = output.click_event("suggest_command", message)
                            if output.data.get("hoverEvent") is None:
                                output = output.hover_text(message)
                        self.client.chat(output)
        else:
            self.client.chat(
                TextComponent(f"Unknown command '{cmd_name}'")
                .color("red")
                .hover_text(TextComponent(message).color("yellow"))
                .click_event("suggest_command", message)
            )

    async def _tab_complete(self, text: str):
        precommand = None
        suggestions: list[str] = []

        # generate autocomplete suggestions
        if text.startswith("//"):
            precommand = text.split()[0].removeprefix("//").casefold()
            prefix = "//"
        elif text.startswith("/"):
            precommand = text.split()[0].removeprefix("/").casefold()
            prefix = "/"
        else:
            prefix = ""

        if precommand is not None:
            parts = text.split()

            if " " in text:
                # User has typed at least the command name and started typing args
                command = self.command_registry.get(precommand)

                if command:
                    # Determine what's been typed
                    # text = "/cmd arg1 arg2 part" -> args = ["arg1", "arg2"], partial = "part"
                    # text = "/cmd arg1 arg2 " -> args = ["arg1", "arg2"], partial = ""
                    if text.endswith(" "):
                        args = parts[1:]
                        partial = ""
                    else:
                        args = parts[1:-1]
                        partial = parts[-1] if len(parts) > 1 else ""

                    try:
                        suggestions = await command.get_suggestions(self, args, partial)
                    except Exception:
                        suggestions = []
            else:
                # Still typing command name
                all_commands = self.command_registry.all_commands()
                suggestions = [
                    f"{prefix}{cmd}"
                    for cmd in all_commands.keys()
                    if cmd.startswith(precommand.lower())
                ]

        self.client.send_packet(
            0x3A,
            VarInt.pack(len(suggestions)),
            *(String.pack(s) for s in suggestions),
        )


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

    async def _update_spec_task(self):
        while self.open:
            if self.spec_eid is not None:
                if self.spec_eid == self.proxy._transformer.player_eid:
                    pos = self.proxy.gamestate.position
                    rot = self.proxy.gamestate.rotation
                    self.client.send_packet(
                        *self.proxy.gamestate._build_player_inventory()
                    )
                    self.client.send_packet(
                        0x2F, Byte.pack(-1), Short.pack(-1), Slot.pack(SlotData())
                    )
                else:
                    entity = self.proxy.gamestate.get_entity(self.spec_eid)
                    if entity:
                        pos = entity.position
                        rot = entity.rotation
                        equip = entity.equipment
                        self._set_slot(36, equip.held)  # hotbar slot 0
                        self._set_slot(5, equip.helmet)
                        self._set_slot(6, equip.chestplate)
                        self._set_slot(7, equip.leggings)
                        self._set_slot(8, equip.boots)
                    else:
                        rot = None
                        pos = None

                if pos and rot:
                    self.client.send_packet(
                        0x08,
                        Double.pack(pos.x),
                        Double.pack(pos.y),
                        Double.pack(pos.z),
                        Float.pack(rot.yaw),
                        Float.pack(rot.pitch),
                        Byte.pack(0),
                    )
            await asyncio.sleep(1 / 20)  # every tick, ideally

    def _set_gamemode(self, gamemode: int) -> None:
        self.client.send_packet(0x2B, UnsignedByte.pack(3), Float.pack(float(gamemode)))

    def _send_abilities(self) -> None:
        abilities_flags = int(
            PlayerAbilityFlags.INVULNERABLE
            | (PlayerAbilityFlags.FLYING if not self.proxy.gamestate.on_ground else 0)
            | self.flight
        )
        self.client.send_packet(
            0x39,
            Byte.pack(abilities_flags)
            + Float.pack(self.proxy.gamestate.flying_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

    def _set_slot(self, slot: int, item: SlotData | None) -> None:
        self.client.send_packet(
            0x2F,
            Byte.pack(0),  # window ID 0 = player inventory
            Short.pack(slot),
            Slot.pack(item if item else SlotData()),
        )

    def _reset_spec(self):
        self.client.send_packet(0x43, VarInt.pack(self.eid))
        self.client.send_packet(
            0x30,
            UnsignedByte.pack(0),  # window ID
            Short.pack(45),  # slot count
            b"".join(Slot.pack(SlotData()) for _ in range(45)),
        )
        self.spec_eid = None
        self._set_gamemode(2)
        self._send_abilities()
        self._set_slot(36, None)

    @listen(0x02)
    async def _packet_use_entity(self, buff: Buffer):
        target = buff.unpack(VarInt)
        type_ = buff.unpack(VarInt)
        if type_ == 0:
            self._spectate(target)

    @command("spectate", "spec")
    async def _command_spectate(self, target: ServerPlayer | None = None) -> None:
        if target is None:
            if self.spec_eid is not None:
                return self._reset_spec()
            else:
                raise CommandException("Please provide a target player!")

        # check if it's the spectator themselves (reset spectate mode)
        if target.name.casefold() == self.username.casefold():
            if self.spec_eid is None:
                raise CommandException("You are not spectating anyone!")
            return self._reset_spec()

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

        self._spectate(eid)

    def _spectate(self, eid: int):
        self.spec_eid = eid
        self._set_gamemode(3)  # spectator mode
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

    @command("pos")
    async def _command_pos(self):
        self.client.chat(str(self.gamestate.position))

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

    @command("locraw")
    async def _command_locraw(self):
        # just do nothing
        # not really sure what we should be doing otherwise
        pass

    @command("tip")
    async def _command_tip(self):
        # see above
        pass


class BroadcastPeerLoginPlugin(BroadcastPeerPlugin):
    flight: Literal[0, PlayerAbilityFlags.ALLOW_FLYING]
    flying: Literal[0, PlayerAbilityFlags.FLYING]
    _update_spec_task: Callable[[], Coroutine[Any, Any, None]]

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
            self.uuid = str(uuid.UUID(await c._get_uuid(self.username)))
            self.skin_properties = await c.get_skin_properties(self.uuid)

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
            + Float.pack(self.proxy.gamestate.flying_speed)
            + Float.pack(self.proxy.gamestate.field_of_view_modifier),
        )

        await self.client.drain()

        # now add to clients list - sync is complete, safe to send packets
        self.proxy.clients.append(self)  # type: ignore[arg-type]

        self.spectate_teleport_task = asyncio.create_task(self._update_spec_task())

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
