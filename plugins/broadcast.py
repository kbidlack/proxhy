import asyncio
import random
import typing
import uuid as uuid_mod
from typing import Optional

import compass
import pyroh
from compass import CompassClient, ConnectionRequest

import auth
from broadcasting.peer_plugins import BroadcastPeerProxy
from broadcasting.transform import (
    PlayerTransformer,
    build_player_list_add_packet,
    build_spawn_player_packet,
)
from core.events import subscribe
from core.net import Server, State
from core.proxy import Proxy
from plugins.chat import ChatPlugin
from plugins.commands import CommandsPlugin
from plugins.settings import SettingsPlugin
from plugins.window import WindowPlugin
from protocol.datatypes import (
    Angle,
    Chat,
    Int,
    Short,
    Slot,
    String,
    TextComponent,
    VarInt,
)
from proxhy.argtypes import MojangPlayer
from proxhy.command import CommandGroup
from proxhy.errors import CommandException
from proxhy.plugin import ProxhyPlugin


class BroadcastPluginState:
    clients: list[BroadcastPeerProxy]
    broadcast_invites: dict[str, compass.ConnectionRequest]
    broadcast_requests: set[str]
    serverbound_task: Optional[asyncio.Task]
    compass_client_initialized: bool
    compass_client: CompassClient
    broadcast_pyroh_server: pyroh.Server
    broadcast_server_task: asyncio.Task


class BCClientClosePlugin(ProxhyPlugin):
    @subscribe("close")
    async def _bcclientclose_event_close(self, _):
        typing.cast(pyroh.StreamWriter, self.server.writer)
        self.server.writer.write_eof()
        await self.server.writer.drain()

    async def create_server(
        self, reader: pyroh.StreamReader, writer: pyroh.StreamWriter
    ):
        self.server = Server(reader, writer)

    async def join(self, username: str, node_id: str):
        self.state = State.LOGIN

        self.handle_server_task = asyncio.create_task(self.handle_server())

        self.server.send_packet(
            0x00,
            VarInt.pack(47),
            String.pack(node_id),
            Short.pack(25565),
            VarInt.pack(State.LOGIN.value),
        )
        self.server.send_packet(0x00, String.pack(username))

        await self.server.drain()

        self.state = State.PLAY


bc_client_plugin_list: tuple[type, ...] = (
    BCClientClosePlugin,
    ChatPlugin,
    CommandsPlugin,
    SettingsPlugin,
    WindowPlugin,
)

COMPASS_SERVER_NODE_ID = (
    "76eeec77bd4aa6a45a449cce220ff58f2edbde29ff4c80a839d4021bbb21b134"
)
compass_client = CompassClient(server_node_id=COMPASS_SERVER_NODE_ID)


class BroadcastPlugin(ProxhyPlugin):
    def _init_broadcasting(self):
        self.clients: list[BroadcastPeerProxy] = []
        self.broadcast_invites: dict[str, compass.ConnectionRequest] = {}
        self.broadcast_requests: set[str] = set()

        self.serverbound_task: Optional[asyncio.Task] = None

        self.compass_client_initialized = False

        self._transformer = PlayerTransformer(
            gamestate=self.gamestate,
            announce_func=self._announce_to_all,
            announce_player_func=self._announce_player_entity,
        )

        self._setup_broadcast_commands()
        self._setup_compass_commands()

    def _setup_compass_commands(self):
        compass = CommandGroup("compass")

        @compass.command("init")
        async def _command_compass_init(self: BroadcastPlugin):
            if self.compass_client_initialized:
                raise CommandException(
                    "The Compass client has already been initialized!"
                )

            asyncio.create_task(self.initialize_cc())
            self.client.chat(
                TextComponent("Initializing Compass client...").color("yellow")
            )

        @compass.command("status")
        async def _command_compass_status(self: BroadcastPlugin):
            self.client.chat(TextComponent("Compass Client Status:").color("gold"))
            self.client.chat(
                TextComponent("Initialized:")
                .color("green")
                .appends(
                    TextComponent(str(self.compass_client_initialized)).color("yellow")
                )
            )
            if self.compass_client_initialized:
                self.client.chat(
                    TextComponent("Node ID:")
                    .color("green")
                    .appends(
                        TextComponent(self.compass_client.server_node_id).color(
                            "yellow"
                        )
                    )
                )
                self.client.chat(
                    TextComponent("Connected:")
                    .color("green")
                    .appends(
                        TextComponent(self.compass_client.is_connected).color("yellow")
                    )
                )
                self.client.chat(
                    TextComponent("Registered:")
                    .color("green")
                    .appends(
                        TextComponent(self.compass_client.is_registered).color("yellow")
                    )
                )
                self.client.chat(
                    TextComponent("Discoverable:")
                    .color("green")
                    .appends(
                        TextComponent(self.compass_client.is_discoverable).color(
                            "yellow"
                        )
                    )
                )

        # TODO: add /compass restart and /compass close (or deinit) if needed
        # and /compass discoverable (toggle)

        self.command_registry.register(compass)

    def _setup_broadcast_commands(self):
        bc = CommandGroup("broadcast", "bc")

        @bc.command("chat")
        async def _command_broadcast_chat(self, *message: str):
            if not message:
                raise CommandException("Please provide a message to broadcast!")
            self.bc_chat(self.username, " ".join(message))

        @bc.command("list")
        async def _command_broadcast_list(self):
            if not self.clients:
                return TextComponent("No players are currently connected.").color(
                    "gold"
                )

            msg = TextComponent("Players: ").color("yellow")
            for i, client in enumerate(self.clients):
                if i > 0:
                    msg.append(TextComponent(", ").color("green"))
                msg.append(TextComponent(client.username).color("aqua"))
            return msg

        @bc.command("joinid")
        async def _command_broadcast_joinid(self: BroadcastPlugin, node_id: str):
            await self._join_broadcast_by_node_id(node_id)

        @bc.command("join")
        async def _command_broadcast_join(self, request_id: str):
            if not self.compass_client_initialized:
                raise CommandException(
                    "The compass client is not connected yet! (wait a second?)"
                )

            try:
                request = self.broadcast_invites[request_id]
            except KeyError:
                raise CommandException(
                    TextComponent("You have no broadcast invites from that player!")
                )

            self.client.chat(
                TextComponent("Joining")
                .color("yellow")
                .appends(TextComponent(request.username).color("aqua"))
                .append("'s broadcast...")
                .color("yellow")
            )

            del self.broadcast_invites[request_id]
            peer_info = await request.accept()

            await self._join_broadcast_by_node_id(peer_info.node_id)

        @bc.command("invite")
        async def _command_broadcast_invite(self, player: MojangPlayer):
            if not self.compass_client_initialized:
                raise CommandException(
                    TextComponent("The compass client is not connected yet!")
                    .appends(TextComponent("(Try again)").color("gold"))
                    .click_event("run_command", f"/bc invite {player.name}")
                    .hover_text(
                        TextComponent(f"/bc invite {player.name}").color("gold")
                    )
                )

            name = player.name
            uuid_ = player.uuid

            if name in self.broadcast_requests:
                raise CommandException(
                    TextComponent(name)
                    .color("aqua")
                    .appends("has already been invited to the broadcast!")
                )
            elif name in [getattr(c, "username", "") for c in self.clients]:
                raise CommandException(
                    TextComponent(name)
                    .color("aqua")
                    .appends("has already joined the broadcast!")
                )

            req_task = asyncio.create_task(
                self.compass_client.request_peer(
                    uuid_, request_reason="proxhy.broadcast", timeout=60
                )
            )

            done, _ = await asyncio.wait({req_task}, timeout=0.5)

            if req_task in done:
                try:
                    await req_task
                except compass.ProtocolError:
                    raise CommandException(
                        TextComponent("Unable to connect to ")
                        .append(TextComponent(name).color("blue"))
                        .append(" due to a compass protocol error :(")
                    )
                except compass.PeerUnavailableError:
                    raise CommandException(
                        TextComponent(name)
                        .color("blue")
                        .appends("is currently unavailable!")
                    )

            self.client.chat(
                TextComponent("Invited ")
                .color("green")
                .append(TextComponent(name).color("aqua"))
                .appends("to the broadcast! They have 60 seconds to accept.")
            )

            self.broadcast_requests.add(name)

            try:
                await req_task
            except compass.ProtocolError:
                raise CommandException(
                    TextComponent("Unable to connect to ")
                    .append(TextComponent(name).color("blue"))
                    .append(" due to a compass protocol error :(")
                )
            except asyncio.TimeoutError:
                raise CommandException(
                    TextComponent("The broadcast invite to ")
                    .append(TextComponent(name).color("blue"))
                    .append(" expired!")
                )
            except compass.PeerUnavailableError:
                raise CommandException(
                    TextComponent(name)
                    .color("blue")
                    .appends("is currently unavailable!")
                )
            finally:
                self.broadcast_requests.discard(name)

        @bc.command("server")
        async def _command_broadcast_server(self: BroadcastPlugin):
            # TODO: add more info?
            self.client.chat(
                TextComponent("Server Node ID:")
                .color("green")
                .appends(
                    TextComponent(self.broadcast_pyroh_server.node_id)
                    .color("yellow")
                    .hover_text(TextComponent("Get Node ID to copy").color("yellow"))
                    .click_event("suggest_command", self.broadcast_pyroh_server.node_id)
                )
            )

        self.command_registry.register(bc)

    async def _join_broadcast_by_node_id(self, node_id: str):
        # TODO: handle errors here properly
        reader, writer = await pyroh.connect(
            pyroh.node_addr(node_id),
            alpn="proxhy.broadcast/1",
            node=self.broadcast_pyroh_server.node,
        )

        BCClientProxy = type(
            "BCClientProxy",
            (*bc_client_plugin_list, Proxy),
            {"username": self.username, "uuid": self.uuid},
        )

        new_proxy = BCClientProxy(
            self.client.reader,
            self.client.writer,
            autostart=False,
        )

        await new_proxy.create_server(reader, writer)
        await self.transfer_to(new_proxy)

        self.server.writer.write_eof()
        await new_proxy.join(self.username, node_id)

    @subscribe("login_success")
    async def _broadcast_event_login_success(self, _):
        if self.dev_mode:
            self.client.chat(
                TextComponent("==> Dev Mode Activated <==").color("green").bold()
            )  # TODO: move to somewhere more appropriate
        else:
            asyncio.create_task(self.initialize_cc())

        self._transformer.init_from_gamestate(self.uuid)
        asyncio.create_task(self.initialize_broadcast_pyroh_server())

    async def initialize_broadcast_pyroh_server(self):
        self.broadcast_pyroh_server = await pyroh.serve(
            self.on_broadcast_peer, alpn=b"proxhy.broadcast/1"
        )
        self.broadcast_server_task = asyncio.create_task(
            self.broadcast_pyroh_server.serve_forever()
        )

        if self.dev_mode:
            self.client.chat(
                TextComponent("✓ Broadcast server initialized!").color("green")
            )

    async def initialize_cc(self):
        self.compass_client = CompassClient(
            COMPASS_SERVER_NODE_ID, node=self.broadcast_pyroh_server.node
        )
        await self.compass_client.connect()

        self.access_token, self.username, self.uuid = await auth.load_auth_info(
            self.username
        )  # this doesn't load if we are connecting to localhost
        # TODO: fix above (access token should be loaded even when connecting to localhost)
        await self.compass_client.register(self.uuid, self.username, self.access_token)

        await self.compass_client.set_discoverable()
        self.compass_client.start_listening(self.on_request)

        self.compass_client_initialized = True
        # no this is not ai i put the ✓ there myself
        self.client.chat(TextComponent("✓ Compass client initialized!").color("green"))

    async def on_broadcast_peer(
        self, reader: pyroh.StreamReader, writer: pyroh.StreamWriter
    ):
        client = BroadcastPeerProxy(
            reader, writer, ("localhost", 41222), autostart=False
        )

        # TODO: fix with protocols
        client.proxy = self  # type: ignore
        client.writer = writer  # store for closing later
        # TODO: check for eid clashes on server
        # how? server may add entity with that id.
        # so I guess in that extremely niche case we could
        # change the eid in the packet from the server for the new entity
        # then use that eid every time a packet for that entity comes through
        # or honestly, server probably doesn't reasonably go over a certain number
        # and we can just pick above there
        client.eid = random.getrandbits(31)

        # don't add to self.clients yet - wait until sync_spectator completes
        # in packet_login_start to avoid live packets mixing with sync packets

        # start processing packets from this client (runs until client disconnects)
        # we await here to keep this method alive so pyroh doesn't close the reader/writer
        client.handle_client_task = asyncio.create_task(client.handle_client())
        try:
            await client.handle_client_task
        except asyncio.CancelledError:
            pass
        finally:
            if client.open:
                await client.close()

    @subscribe("close")
    async def _broadcast_event_close(self, _):  # _: reason (str); unused (for now?)
        for tsk in {"cb_gamestate_task", "sb_gamestate_task"}:  # tsk tsk
            # might not be neceessary to check this anymore bc of gamestate plugin
            if hasattr(self, tsk) and (task := getattr(self, tsk)):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self.logged_in:
            if hasattr(self, "broadcast_server_task") and self.broadcast_server_task:
                self.broadcast_server_task.cancel()

            try:
                await asyncio.wait_for(
                    self.disconnect_clients(reason="The broadcast owner disconnected!"),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                pass

            try:
                self.compass_client.stop_listening()
                await asyncio.wait_for(
                    self.compass_client.set_undiscoverable(), timeout=0.5
                )
            except (
                compass.ProtocolError,
                compass.ConnectionError,
                asyncio.TimeoutError,
                AttributeError,  # probably no compass client, dev mode?
            ):
                pass  # probably not registered, or timed out

            self._transformer.reset()

            if self.serverbound_task and not self.serverbound_task.done():
                self.serverbound_task.cancel()
                try:
                    await self.serverbound_task
                except asyncio.CancelledError:
                    pass

    async def _expire_broadcast_request(self, request_id: str):
        if request_id in self.broadcast_invites:
            request = self.broadcast_invites.pop(request_id)
            self.client.chat(
                TextComponent("The broadcast invite from")
                .color("red")
                .appends(TextComponent(request.username).color("aqua"))
                .appends(TextComponent("expired!").color("red"))
            )

    async def on_request(self, request: ConnectionRequest):
        request_id = request.username
        self.broadcast_invites[request_id] = request

        if request.reason == "proxhy.broadcast":
            self.client.chat(
                TextComponent(request.username)
                .color("aqua")
                .bold()
                .appends(
                    TextComponent(
                        "has invited you to join their broadcast! You have 60 seconds to accept."
                    ).color("gold")
                )
                .appends(TextComponent("[").color("dark_gray"))
                .append(
                    TextComponent("Join")
                    .color("green")
                    .bold()
                    .click_event("run_command", f"/bc join {request_id}")
                    .hover_text(
                        TextComponent("Join")
                        .color("green")
                        .appends(TextComponent(request.username).color("aqua"))
                        .append("'s broadcast")
                    )
                )
                .append(TextComponent("]").color("dark_gray"))
            )
            asyncio.get_running_loop().call_later(
                60,
                lambda: asyncio.create_task(self._expire_broadcast_request(request_id)),
            )
        else:
            # TODO: support this...how?
            # or even better, why?
            self.client.chat(
                TextComponent(request.username)
                .color("aqua")
                .bold()
                .appends(
                    TextComponent(" has requested to connect to you! (reason: ").color(
                        "gold"
                    )
                )
                .append(
                    TextComponent(request.reason or "No reason provided").color("white")
                )
                .append(TextComponent(") ").color("gold"))
                .append(TextComponent("[").color("dark_gray"))
                .append(
                    TextComponent("Accept")
                    .color("green")
                    .bold()
                    .click_event("run_command", f"/connection accept {request_id}")
                    .hover_text(
                        TextComponent("Accept the connection from")
                        .color("green")
                        .appends(TextComponent(request.username).color("aqua"))
                    )
                )
                .append(TextComponent("]").color("dark_gray"))
            )

    async def disconnect_clients(self, reason: str = "The broadcast was stopped!"):
        for client in self.clients:
            client.client.send_packet(
                0x40,
                Chat.pack(TextComponent(reason).color("red")),
            )

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

    @subscribe("cb_gamestate_update")
    # needs to be async for subscribe -- TODO: allow sync subscribers?
    async def _broadcast_event_cb_gamestate_update(
        self, data: tuple[int, *tuple[bytes, ...]]
    ):
        packet_id, *packet_data = data
        """Forward a clientbound packet to spectators with appropriate transformations."""
        if not self.clients:
            return
        # Handle Join Game specially to update EID per client
        if id == 0x01:
            buff_data = b"".join(packet_data)
            # Extract player EID and update transformer
            self._transformer._player_eid = int.from_bytes(
                buff_data[:4], "big", signed=True
            )
            self._transformer.reset()

            # Forward with modified EID for each client
            for client in self.clients:
                if client.state == State.PLAY:
                    client.client.send_packet(
                        packet_id, Int(client.eid) + buff_data[4:]
                    )
        else:
            # Use transformer for other packets
            self._transformer.forward_clientbound_packet(
                packet_id, tuple(packet_data), self._spawn_players_after_position
            )

    @subscribe("sb_gamestate_update")
    async def _broadcast_event_sb_gamestate_update(
        self, data: tuple[int, *tuple[bytes, ...]]
    ):
        packet_id, *packet_data = data
        if self.clients:
            self._transformer.handle_serverbound_packet(
                packet_id, b"".join(packet_data)
            )

    def _spawn_players_after_position(self):
        """Callback to spawn player for clients after position update."""
        for client in self.clients:
            if client.state == State.PLAY:
                self._spawn_player_for_client(client)

    def _spawn_player_for_client(self, client: BroadcastPeerProxy):
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

        # Sync transformer's last known position/rotation for delta calculations
        self._transformer._last_position = current_position
        self._transformer._last_rotation = current_rotation

        self._transformer.mark_spawned(client.eid)

    def _ensure_player_in_tab_list(self, client: BroadcastPeerProxy):
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
