import asyncio
import random
import uuid as uuid_mod
from asyncio import StreamReader, StreamWriter
from typing import Literal, Optional

from core.events import subscribe
from core.net import State
from core.plugin import Plugin
from core.proxy import Proxy
from plugins.chat import ChatPlugin
from protocol.datatypes import (
    Angle,
    Chat,
    Int,
    Short,
    Slot,
    TextComponent,
    VarInt,
)
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.gamestate import GameState

from .plugins import BasePlugin, BCCommandsPlugin, LoginPlugin
from .transform import (
    PlayerTransformer,
    build_player_list_add_packet,
    build_spawn_player_packet,
)

# "proxy" for any connected broadcast clients
# we are just reusing proxy code and then omitting the server
# to be able to take advantage of all the prebuilt plugins
# and packet handling stuff from proxy, just for a client connection
plugin_list: tuple[type, ...] = (
    ChatPlugin,
    LoginPlugin,
    BasePlugin,
    BCCommandsPlugin,
)
# this is named plugin_list because my type checker is complaining
# that it clashes with from .plugins import ... above -_-

type BC_ACTION = Literal["start", "stop", "status", "chat"]


class BaseClient:
    eid: int
    proxy: "BroadcastPlugin"


ClientProxy = type("ClientProxy", (*plugin_list, Proxy, BaseClient), {})


class BroadcastPlugin(Plugin):
    username: str
    uuid: str

    def _init_broadcasting(self):
        self.broadcast_server: Optional[asyncio.Server] = None
        self.clients: list[ClientProxy] = []

        self.gamestate = GameState()
        self.gamestate_task = asyncio.create_task(self._update_gamestate())
        self.serverbound_task: Optional[asyncio.Task] = None

        # Initialize the transformer with callback functions
        self._transformer = PlayerTransformer(
            gamestate=self.gamestate,
            announce_func=self._announce_to_all,
            announce_player_func=self._announce_player_entity,
        )

    @property
    def broadcasting(self):
        return self.broadcast_server is not None

    @command("bc")
    async def broadcast(self, action: BC_ACTION, *args):
        self._verify_broadcast_action(action, *args)

        if action == "start":
            await self._start_broadcasting()
        elif action == "stop":
            await self._stop_broadcasting()
        elif action == "status":
            self.client.chat(
                TextComponent(
                    f"You are currently{' ' if self.broadcasting else ' not '} broadcasting!"
                ).color("green")
            )
        elif action == "chat":
            self.bc_chat(self.username, " ".join(args))

    async def _start_broadcasting(self):
        # Initialize transformer with current player state
        self._transformer.init_from_gamestate(self.uuid)

        # Start listening to serverbound packets for player movement/actions
        if self.serverbound_task is None or self.serverbound_task.done():
            self.serverbound_task = asyncio.create_task(self._update_serverbound())

        self.broadcast_server = await asyncio.start_server(
            self._handle_bc_client, "localhost", 41222
        )
        self.client.chat(
            TextComponent("Started broadcasting on localhost:41222").color("green")
        )

    async def _stop_broadcasting(self, reason: str = "The broadcast was stopped!"):
        for client in self.clients:
            client.client.send_packet(
                0x40,
                Chat.pack(TextComponent(reason).color("red")),
            )

        if self.broadcast_server:
            self.broadcast_server.close()
            await self.broadcast_server.wait_closed()

        self.broadcast_server = None
        self._transformer.reset()

        if self.serverbound_task and not self.serverbound_task.done():
            self.serverbound_task.cancel()

        self.client.chat(TextComponent("Stopped broadcasting!").color("green"))

    async def _handle_bc_client(self, reader: StreamReader, writer: StreamWriter):
        client = ClientProxy(reader, writer, ("localhost", 41222, "localhost", 41222))
        client.proxy = self
        # TODO: check for eid clashes on server
        client.eid = random.getrandbits(31)

        self.clients.append(client)

    def _verify_broadcast_action(self, action: BC_ACTION, *args):
        match action, self.broadcasting:
            case "start", True:
                raise CommandException("You are already broadcasting!")
            case "stop", False:
                raise CommandException("You are not broadcasting!")
            case "status", False:
                raise CommandException("You are not broadcasting!")
            case "chat", False:
                raise CommandException("You are not broadcasting!")

    def bc_chat(self, username: str, msg: str):
        self.client.chat(
            TextComponent("[")
            .color("dark_gray")
            .append(TextComponent("BROADCAST").color("red"))
            .append(TextComponent("]").color("dark_gray"))
            .appends(TextComponent(f"{username}:").color("aqua"))
            .appends(TextComponent(msg).color("white"))
        )

    def _announce_to_all(self, packet_id: int, data: bytes):
        """Send a packet to all spectator clients."""
        for client in self.clients:
            if client.state == State.PLAY:
                client.client.send_packet(packet_id, data)

    def _announce_player_entity(self, packet_id: int, data: bytes):
        """Send a packet about the player entity to spectators who have it spawned."""
        for client in self.clients:
            if (
                client.state == State.PLAY
                and client.eid in self._transformer.player_spawned_for
            ):
                client.client.send_packet(packet_id, data)

    @subscribe("close")
    async def bc_on_close(self, _):  # _: reason (str); unused (for now?)
        await self._stop_broadcasting(reason="The broadcast owner disconnected!")

    async def _update_gamestate(self):
        while self.open:
            id, *data = await self.client.pqueue.get()
            self.gamestate.update(id, b"".join(data))
            self._forward_spec_packet(id, *data)

    async def _update_serverbound(self):
        """Process serverbound packets (player -> server) and transform for spectators."""
        try:
            while self.open:
                id, *data = await self.server.pqueue.get()
                if self.clients:
                    self._transformer.handle_serverbound_packet(id, b"".join(data))
        except asyncio.CancelledError:
            pass  # Task was cancelled, exit gracefully

    def _forward_spec_packet(self, id: int, *data: bytes):
        """Forward a clientbound packet to spectators with appropriate transformations."""
        if not self.clients:
            return

        # Handle Join Game specially to update EID per client
        if id == 0x01:
            buff_data = b"".join(data)
            # Extract player EID and update transformer
            self._transformer._player_eid = int.from_bytes(
                buff_data[:4], "big", signed=True
            )
            self._transformer.reset()

            # Start listening to serverbound packets if not already
            if self.serverbound_task is None or self.serverbound_task.done():
                self.serverbound_task = asyncio.create_task(self._update_serverbound())

            # Forward with modified EID for each client
            for client in self.clients:
                if client.state == State.PLAY:
                    client.client.send_packet(id, Int(client.eid) + buff_data[4:])
        else:
            # Use transformer for other packets
            self._transformer.forward_clientbound_packet(
                id, data, self._spawn_players_after_position
            )

    def _spawn_players_after_position(self):
        """Callback to spawn player for clients after position update."""
        for client in self.clients:
            if client.state == State.PLAY:
                self._spawn_player_for_client(client)

    def _spawn_player_for_client(self, client: ClientProxy):
        """Spawn the player entity for a specific spectator client."""
        if client.eid in self._transformer.player_spawned_for:
            return

        if not self._transformer.player_uuid:
            return

        # Ensure player is in tab list first (includes skin properties)
        self._ensure_player_in_tab_list(client)

        # Use CURRENT gamestate values, not cached transformer values
        # This ensures correct position/rotation when spectator joins mid-session
        current_position = self.gamestate.position
        current_rotation = self.gamestate.rotation

        # Build and send Spawn Player packet
        spawn_data = build_spawn_player_packet(
            player_eid=self._transformer.player_eid,
            player_uuid=self._transformer.player_uuid,
            position=current_position,
            rotation=current_rotation,
            metadata_flags=self._transformer.player_metadata_flags,
        )
        client.client.send_packet(0x0C, spawn_data)

        # Send full player metadata (includes skin layers at index 10)
        player_entity = self.gamestate.get_entity(self.gamestate.player_entity_id)
        if player_entity and player_entity.metadata:
            # Use gamestate's _pack_metadata to build the full metadata
            full_metadata = self.gamestate._pack_metadata(player_entity.metadata)
            client.client.send_packet(
                0x1C,  # Entity Metadata
                VarInt.pack(self._transformer.player_eid) + full_metadata,
            )

        # Send Entity Head Look (0x19) to ensure head rotation is correct
        client.client.send_packet(
            0x19,
            VarInt.pack(self._transformer.player_eid)
            + Angle.pack(current_rotation.yaw),
        )

        # Send current held item from gamestate
        held_item = self.gamestate.get_held_item()
        if held_item and held_item.item:
            client.client.send_packet(
                0x04,
                VarInt.pack(self._transformer.player_eid)
                + Short.pack(0)  # Equipment slot 0 = held item
                + Slot.pack(held_item),
            )

        # Send armor equipment from player inventory
        # Slots: 0=held, 1=boots, 2=leggings, 3=chestplate, 4=helmet
        armor = (
            self.gamestate.get_armor()
        )  # Returns [helmet, chestplate, leggings, boots]
        armor_slots = [(4, armor[0]), (3, armor[1]), (2, armor[2]), (1, armor[3])]
        for equip_slot, item in armor_slots:
            if item and item.item:
                client.client.send_packet(
                    0x04,
                    VarInt.pack(self._transformer.player_eid)
                    + Short.pack(equip_slot)
                    + Slot.pack(item),
                )

        # Send any other tracked equipment
        for slot, item in self._transformer.player_equipment.items():
            if slot == 0:
                continue  # Already sent held item above
            if item and item.item:
                client.client.send_packet(
                    0x04,
                    VarInt.pack(self._transformer.player_eid)
                    + Short.pack(slot)
                    + Slot.pack(item),
                )

        # Sync transformer state with current gamestate so subsequent updates work correctly
        self._transformer._player_position = current_position
        self._transformer._player_rotation = current_rotation

        self._transformer.mark_spawned(client.eid)

    def _ensure_player_in_tab_list(self, client: ClientProxy):
        """Ensure the player being watched is in the spectator's tab list."""
        # Normalize UUID to hyphenated format to match gamestate storage
        try:
            normalized_uuid = str(uuid_mod.UUID(self._transformer.player_uuid))
        except ValueError:
            normalized_uuid = self._transformer.player_uuid

        player_info = self.gamestate.player_list.get(normalized_uuid)

        if player_info:
            data = build_player_list_add_packet(
                player_uuid=self._transformer.player_uuid,
                player_name=player_info.name,
                properties=player_info.properties,
                gamemode=player_info.gamemode,
                ping=player_info.ping,
                display_name=player_info.display_name,
            )
        else:
            data = build_player_list_add_packet(
                player_uuid=self._transformer.player_uuid,
                player_name=self.username,
            )

        client.client.send_packet(0x38, data)
