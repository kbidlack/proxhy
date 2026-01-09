import asyncio
import random
import typing
import uuid as uuid_mod
from typing import Awaitable, Callable, Literal, Optional

import compass
import hypixel
import pyroh
from compass import CompassClient, ConnectionRequest, PeerInfo

import auth
from broadcasting.peer_plugins import BroadcastPeerProxy
from broadcasting.transform import (
    PlayerTransformer,
    build_player_list_add_packet,
    build_spawn_player_packet,
)
from core.events import subscribe
from core.net import Server, State
from core.plugin import Plugin
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
from proxhy import utils
from proxhy.command import command
from proxhy.errors import CommandException
from proxhy.gamestate import GameState


class BCClientClosePlugin(Plugin):
    @subscribe("close")
    async def _close_bc_client_proxy(self, _):
        typing.cast(pyroh.StreamWriter, self.server.writer)
        self.server.writer.write_eof()
        await self.server.writer.drain()

    async def create_server(
        self, reader: pyroh.StreamReader, writer: pyroh.StreamWriter
    ):
        self.server = Server(reader, writer)

    async def join(
        self,
        username: str,
        peer_info: PeerInfo,
    ):
        self.state = State.LOGIN

        self.handle_server_task = asyncio.create_task(self.handle_server())

        self.server.send_packet(
            0x00,
            VarInt.pack(47),
            String.pack(peer_info.node_id),
            Short.pack(25565),  # technically wrong but whatever
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

type BC_COMMAND_ACTION = Literal["invite", "request", "chat", "list", "join", "leave"]


class BroadcastPlugin(Plugin):
    username: str
    uuid: str
    access_token: str
    logged_in: bool
    transfer_to: Callable[[Proxy], Awaitable[None]]

    def _init_broadcasting(self):
        self.clients: list[BroadcastPeerProxy] = []

        self.broadcast_invites: dict[str, compass.ConnectionRequest] = dict()
        self.broadcast_requests: set[str] = set()

        self.gamestate = GameState()
        self.gamestate_task = asyncio.create_task(self._update_gamestate())
        self.serverbound_task: Optional[asyncio.Task] = None

        self.compass_client_initialized = False

        # Initialize the transformer with callback functions
        self._transformer = PlayerTransformer(
            gamestate=self.gamestate,
            announce_func=self._announce_to_all,
            announce_player_func=self._announce_player_entity,
        )

    @subscribe("login_success")
    async def on_login_success(self, _):
        asyncio.create_task(self.initialize_cc())

        # Initialize transformer with current player state
        self._transformer.init_from_gamestate(self.uuid)

        # Start listening to serverbound packets for player movement/actions
        # (must be after login when server connection exists)
        if self.serverbound_task is None or self.serverbound_task.done():
            self.serverbound_task = asyncio.create_task(self._update_serverbound())

    async def initialize_cc(self):
        # TODO: wait for compass client initialization
        self.broadcast_pyroh_server = await pyroh.serve(
            self.on_broadcast_peer, alpn=b"proxhy.broadcast/1"
        )
        self.broadcast_server_task = asyncio.create_task(
            self.broadcast_pyroh_server.serve_forever()
        )

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
            reader, writer, ("localhost", 41222, "localhost", 41222), autostart=False
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
    async def _close_broadcast(self, _):  # _: reason (str); unused (for now?)
        if hasattr(self, "gamestate_task") and self.gamestate_task:
            self.gamestate_task.cancel()
            try:
                await self.gamestate_task
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

        self.broadcast_invites.update({request_id: request})

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
                TextComponent("")
                .append(TextComponent(f"{request.username}").color("aqua").bold())
                .append(
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

    @command("bc")
    async def broadcast(self, action: BC_COMMAND_ACTION, *args: str):
        def _verify_one_args(*args: str):
            if len(args) > 1:
                raise CommandException(
                    "Broadcast invite only accepts one parameter: player!"
                )
            elif len(args) < 1:
                raise CommandException(
                    "Broadcast invite requires one parameter: player!"
                )

        if action == "chat":
            self.bc_chat(self.username, " ".join(args))
        elif action == "list":
            if not self.clients:
                return self.client.chat(
                    TextComponent("No players are currently connected.").color("gold")
                )

            players = [c.username for c in self.clients]
            tc = TextComponent("Player: ").color("yellow")
            for i, name in enumerate(players):
                tc.append(TextComponent(name).color("aqua"))
                if i != len(players) - 1:
                    tc.append(TextComponent(", ").color("green"))
            self.client.chat(tc)

        elif action == "join":
            if not self.compass_client_initialized:
                raise CommandException(
                    "The compass client is not connected yet! (wait a second?)"
                )

            _verify_one_args(*args)

            request_id = args[0]
            try:
                request = self.broadcast_invites[request_id]
            except KeyError:
                raise CommandException(  # TODO: add name via mojang api?
                    TextComponent("You have no broadcast invites from that player!")
                )
            del self.broadcast_invites[request_id]

            peer_info = await request.accept()

            # TODO: handle errors here properly
            reader, writer = await pyroh.connect(
                pyroh.node_addr(peer_info.node_id),
                alpn="proxhy.broadcast/1",
                node=self.broadcast_pyroh_server.node,
            )

            BCClientProxy = type(
                "BCClientProxy",
                (*bc_client_plugin_list, Proxy),
                {"username": self.username, "uuid": self.uuid},
                # ^ keep username & uuid for bc proxy
            )

            new_proxy = BCClientProxy(
                self.client.reader,
                self.client.writer,
                autostart=False,
            )

            await new_proxy.create_server(reader, writer)
            await self.transfer_to(new_proxy)

            self.server.writer.write_eof()
            await new_proxy.join(self.username, peer_info)

        elif action == "invite":
            if not self.compass_client_initialized:
                raise CommandException(
                    TextComponent(
                        "The compass client is not connected yet, please wait a second!"
                    )
                    .appends(TextComponent("(Try again)").color("gold"))
                    .click_event("run_command", f"/bc invite {' '.join(args)}")
                    .hover_text(
                        TextComponent(f"/bc invite {' '.join(args)}").color("gold")
                    )
                )

            _verify_one_args(*args)
            async with utils._Client() as client:
                try:
                    player_info = await client.get_profile(args[0])
                except hypixel.PlayerNotFound:
                    raise CommandException(
                        TextComponent("Player '")
                        .appends(TextComponent(args[0]).color("blue"))
                        .appends("' was not found!")
                    )

            name = player_info.name
            uuid_ = player_info.uuid

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

            # start and see if it immediately fails; if it does
            # the peer may be offline and there is no point
            # in sending the invite success message
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
                        TextComponent("Unable to connect to")
                        .appends(TextComponent(name).color("blue"))
                        .append("due to a compass protocol error ):")
                    )
                except compass.PeerUnavailableError:
                    raise CommandException(
                        TextComponent(name)
                        .color("blue")
                        .appends("is currently unavailable!")
                        .color("red")
                    )

            self.client.chat(
                TextComponent("Invited")
                .color("green")
                .appends(TextComponent(name).color("aqua"))
                .appends(
                    TextComponent(
                        "to the broadcast! They have 60 seconds to accept."
                    ).color("green")
                )
            )

            self.broadcast_requests.add(name)

            try:
                await req_task
            except compass.ProtocolError:
                raise CommandException(
                    TextComponent("Unable to connect to")
                    .appends(TextComponent(name).color("blue"))
                    .append("due to a compass protocol error ):")
                )
            except asyncio.TimeoutError:
                raise CommandException(
                    TextComponent("The broadcast invite to")
                    .appends(TextComponent(name).color("blue"))
                    .appends("expired!")
                )
            except compass.PeerUnavailableError:
                raise CommandException(
                    TextComponent(name)
                    .color("blue")
                    .appends("is currently unavailable!")
                    .color("red")
                )
            finally:
                if name in self.broadcast_requests:
                    self.broadcast_requests.remove(name)

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

        # Sync transformer state with current gamestate so subsequent updates work correctly
        self._transformer._player_position = current_position
        self._transformer._player_rotation = current_rotation

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
