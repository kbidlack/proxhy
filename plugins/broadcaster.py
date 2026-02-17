import asyncio
import random
import shelve
import uuid
import uuid as uuid_mod
from pathlib import Path
from typing import Optional

import httpx
import pyroh
from compass import ConnectionRequest, MinecraftPeerClient
from platformdirs import user_config_dir

import auth
from broadcasting.proxy import BroadcastPeerProxy
from broadcasting.transform import (
    PlayerTransformer,
    build_player_list_add_packet,
    build_spawn_player_packet,
)
from core.events import listen_server, subscribe
from core.net import State
from core.proxy import Proxy
from gamestate.state import Vec3d
from plugins.commands import CommandException, CommandGroup
from protocol.datatypes import (
    UUID,
    Angle,
    Buffer,
    Chat,
    Int,
    Short,
    Slot,
    TextComponent,
    VarInt,
)
from proxhy.argtypes import BroadcastPlayer, MojangPlayer
from proxhy.plugin import ProxhyPlugin

from .broadcastee.proxy import broadcastee_plugin_list

BROKER_URL = "http://163.192.4.69:3000"


class BroadcastPluginState:
    BC_DATA_PATH: Path
    clients: list[BroadcastPeerProxy]
    broadcast_invites: dict[str, ConnectionRequest]
    broadcast_requests: set[str]
    compass_client: MinecraftPeerClient | None
    broadcast_pyroh_server: pyroh.Server
    broadcast_server_task: asyncio.Task
    _transformer: PlayerTransformer


class BroadcastPlugin(ProxhyPlugin):
    def _init_broadcasting(self):
        self.BC_DATA_PATH = Path(user_config_dir("proxhy")) / "broadcast.db"

        with shelve.open(self.BC_DATA_PATH, writeback=True) as db:
            if not db.get("trusted"):
                db["trusted"] = dict()  # uuid: name

        self.clients: list[BroadcastPeerProxy] = []
        self.broadcast_invites: dict[str, ConnectionRequest] = {}
        self.broadcast_requests: set[str] = set()
        self.joining_broadcast: bool = False

        self._respawn_debounce_task: Optional[asyncio.Task] = None

        self.compass_client: MinecraftPeerClient | None = None

        self._transformer = PlayerTransformer(
            gamestate=self.gamestate,
            announce_func=self._announce_to_all,
            announce_player_func=self._announce_player_entity,
        )

        self._setup_broadcast_commands()
        self._setup_compass_commands()

    def _setup_compass_commands(self):
        compass = CommandGroup("compass", help="Compass client commands.")

        @compass.command("init")
        async def _command_compass_init(self: BroadcastPlugin):
            """Initialize the compass client."""
            if self.compass_client is not None:
                raise CommandException(
                    "The Compass client has already been initialized!"
                )

            asyncio.create_task(self.initialize_cc())
            self.client.chat(
                TextComponent("Initializing Compass client...").color("yellow")
            )

        @compass.command("status")
        async def _command_compass_status(self: BroadcastPlugin):
            """Get the compass client status."""
            self.client.chat(TextComponent("Compass Client Status:").color("gold"))
            initialized = self.compass_client is not None
            self.client.chat(
                TextComponent("Initialized: ")
                .color("green")
                .append(TextComponent(str(initialized)).color("yellow"))
            )
            if initialized and self.compass_client is not None:
                has_session = self.compass_client.session_token is not None
                self.client.chat(
                    TextComponent("Session Active: ")
                    .color("green")
                    .append(TextComponent(str(has_session)).color("yellow"))
                )
                self.client.chat(
                    TextComponent("Username: ")
                    .color("green")
                    .append(
                        TextComponent(self.compass_client.mc_username).color("yellow")
                    )
                )

        # TODO: add /compass restart and /compass close (or deinit) if needed
        # and /compass discoverable (toggle)

        self.command_registry.register(compass)

    def _setup_broadcast_commands(self):
        bc = CommandGroup("broadcast", "bc", help="Broadcast commands.")

        @bc.command("chat")
        async def _command_broadcast_chat(self, *message: str):
            """Send a message to the broadcast chat."""
            if not message:
                raise CommandException("Please provide a message to broadcast!")
            self.bc_chat(self.username, " ".join(message))

        @bc.command("list")
        async def _command_broadcast_list(self):
            """List all players in the broadcast."""
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
            """Join a broadcast by Iroh node ID."""
            self.client.chat(
                TextComponent("Joining")
                .color("yellow")
                .appends(
                    TextComponent(node_id)
                    .color("aqua")
                    .hover_text(node_id)
                    .click_event("suggest_command", node_id)
                )
            )
            await self._join_broadcast_by_node_id(node_id)

        @bc.command("join")
        async def _command_broadcast_join(self, request_id: str):
            """Join a broadcast invite."""
            if self.joining_broadcast:
                raise CommandException(
                    TextComponent("You are already joining a broadcast!").color("red")
                )

            if self.compass_client is None:
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
                .appends(TextComponent(request.from_player).color("aqua"))
                .append("'s broadcast...")
                .color("yellow")
            )

            del self.broadcast_invites[request_id]
            reader, writer = await request.accept()

            await self._join_broadcast_with_streams(reader, writer)

        @bc.command("accept")
        async def _command_broadcast_accept(self, request_id: str):
            """Accept a broadcast request."""
            if self.compass_client is None:
                raise CommandException(
                    "The compass client is not connected yet! (wait a second?)"
                )

            try:
                request = self.broadcast_invites[request_id]
            except KeyError:
                raise CommandException(
                    TextComponent("You have no broadcast requests from that player!")
                )

            if request.reason != "proxhy.broadcast_request":
                raise CommandException(
                    TextComponent(
                        "That is not a broadcast request! Use /bc join instead."
                    )
                )

            self.client.chat(
                TextComponent("Accepting ")
                .color("green")
                .append(TextComponent(request.from_player).color("aqua"))
                .appends("into your broadcast!")
            )

            del self.broadcast_invites[request_id]
            reader, writer = await request.accept()
            asyncio.create_task(self.on_broadcast_peer(reader, writer))

        @bc.command("slime")
        async def _command_broadcast_slime(
            self: BroadcastPlugin, player: BroadcastPlayer
        ):
            """Slime a player out of the broadcast."""
            client = player.client

            client.client.send_packet(
                0x40,
                Chat.pack(
                    TextComponent("You have been slimed out of the broadcast.").color(
                        "red"
                    )
                ),
            )
            client.client.close()

        async def _send_peer_request(
            self: BroadcastPlugin,
            player: MojangPlayer,
            reason: str,
            command: str,
            already_pending_msg: str,
            sent_msg: str,
            expired_msg: str,
        ):
            if self.compass_client is None:
                raise CommandException(
                    TextComponent("The compass client is not connected yet!")
                    .appends(TextComponent("(Try again)").color("gold"))
                    .click_event("run_command", f"/bc {command} {player.name}")
                    .hover_text(
                        TextComponent(f"/bc {command} {player.name}").color("gold")
                    )
                )

            name = player.name

            if name.casefold() == self.username.casefold():
                raise CommandException(
                    TextComponent("You cannot invite or request yourself!")
                )

            if name in self.broadcast_invites:
                raise CommandException(
                    TextComponent(name)
                    .color("aqua")
                    .appends("has already sent you an invite!")
                )
            if name in self.broadcast_requests:
                raise CommandException(
                    TextComponent(name).color("aqua").appends(already_pending_msg)
                )
            elif name in [getattr(c, "username", "") for c in self.clients]:
                raise CommandException(
                    TextComponent(name)
                    .color("aqua")
                    .appends("has already joined the broadcast!")
                )

            req_task = asyncio.create_task(
                self.compass_client.request_connection(name, reason=reason)
            )

            done, _ = await asyncio.wait({req_task}, timeout=0.5)

            if req_task in done:
                try:
                    await req_task
                except httpx.HTTPStatusError as e:
                    raise CommandException(
                        TextComponent("Unable to connect to ")
                        .append(TextComponent(name).color("blue"))
                        .append(
                            f" due to a compass error :( ({e.response.status_code})"
                        )
                    )

            asyncio.create_task(self._iphone_ringtone())
            self.client.chat(
                TextComponent(sent_msg)
                .color("green")
                .appends(TextComponent(name).color("aqua"))
                .append("! They have 60 seconds to accept.")
            )

            self.broadcast_requests.add(name)

            try:
                return await req_task
            except httpx.HTTPStatusError as e:
                raise CommandException(
                    TextComponent("Unable to connect to ")
                    .append(TextComponent(name).color("gold"))
                    .append(f" due to a compass error :( ({e.response.status_code})")
                )
            except asyncio.TimeoutError:
                raise CommandException(
                    TextComponent(expired_msg)
                    .append(TextComponent(name).color("gold"))
                    .append(" expired!")
                )
            finally:
                self.broadcast_requests.discard(name)

        @bc.command("invite")
        async def _command_broadcast_invite(self, player: MojangPlayer):
            result = await _send_peer_request(
                self,
                player,
                reason="proxhy.broadcast",
                command="invite",
                already_pending_msg="has already been invited to the broadcast!",
                sent_msg="Invited",
                expired_msg="The broadcast invite to ",
            )
            if result is None:
                raise CommandException(
                    TextComponent(player.name)
                    .color("gold")
                    .appends("denied your invite!")
                )
            reader, writer = result
            asyncio.create_task(self.on_broadcast_peer(reader, writer))

        @bc.command("request")
        async def _command_broadcast_request(self, player: MojangPlayer):
            result = await _send_peer_request(
                self,
                player,
                reason="proxhy.broadcast_request",
                command="request",
                already_pending_msg="has already been sent a request!",
                sent_msg="Requested to join",
                expired_msg="The broadcast request to ",
            )
            if result is None:
                raise CommandException(
                    TextComponent(player.name)
                    .color("gold")
                    .appends("denied your request!")
                )
            # If we get here, the request was accepted - join their broadcast
            reader, writer = result
            self.client.chat(
                TextComponent(player.name)
                .color("aqua")
                .appends(
                    TextComponent(
                        "accepted your request! Joining their broadcast..."
                    ).color("green")
                )
            )
            await self._join_broadcast_with_streams(reader, writer)

        @bc.command("server")
        async def _command_broadcast_server(self: BroadcastPlugin):
            try:
                # TODO: add more info?
                return (
                    TextComponent("Server Node ID:")
                    .color("green")
                    .appends(
                        TextComponent(self.broadcast_pyroh_server.node_id)
                        .color("yellow")
                        .hover_text(
                            TextComponent("Get Node ID to copy").color("yellow")
                        )
                        .click_event(
                            "suggest_command", self.broadcast_pyroh_server.node_id
                        )
                    )
                )
            except AttributeError:
                raise CommandException(
                    "The broadcast server has not been initialized yet!"
                )

        self.command_registry.register(bc)

        trust = bc.group("trust", help="Manage trusted players.")

        @trust.command("add")
        async def _command_broadcast_trust_add(
            self: BroadcastPlugin, player: MojangPlayer
        ):
            """Add a trusted player."""
            with shelve.open(self.BC_DATA_PATH, writeback=True) as db:
                if player.uuid in db["trusted"]:
                    raise CommandException(
                        TextComponent(player.name)
                        .color("gold")
                        .appends("is already in your trusted player list!")
                    )
                db["trusted"][player.uuid] = player.name

            self.client.chat(
                TextComponent("Added")
                .color("green")
                .appends(TextComponent(player.name).color("aqua"))
                .appends("to trusted players!")
            )

        @trust.command("remove")
        async def _command_broadcast_untrust(
            self: BroadcastPlugin, player: MojangPlayer
        ):
            """Remove a trusted player."""
            with shelve.open(self.BC_DATA_PATH, writeback=True) as db:
                if player.uuid not in db["trusted"]:
                    raise CommandException(
                        TextComponent(player.name)
                        .color("gold")
                        .appends("is not in your trusted players list!")
                    )
                del db["trusted"][player.uuid]

            self.client.chat(
                TextComponent("Removed")
                .color("red")
                .appends(TextComponent(player.name).color("gold"))
                .appends("from trusted players!")
            )

        @trust.command("list")
        async def _command_broadcast_trust_list(self: BroadcastPlugin):
            """List all trusted players."""
            with shelve.open(self.BC_DATA_PATH) as db:
                players = db["trusted"].values()

                if not players:
                    return TextComponent(
                        "There are no players in your trusted list!"
                    ).color("green")

                self.client.chat(
                    TextComponent("Players in broadcast trusted list:").color("green")
                )

                msg = TextComponent("> ").color("green")
                for i, name in enumerate(players):
                    if i != 0:
                        msg.append(TextComponent(", ").color("green"))
                    msg.append(TextComponent(name).color("aqua"))
                return msg

    async def _join_broadcast_by_node_id(self, node_id: str):
        if self.joining_broadcast:
            raise CommandException(
                TextComponent("You are already joining a broadcast!").color("red")
            )

        if self.clients:
            raise CommandException(
                TextComponent(
                    "You cannot join a broadcast while spectators are connected!"
                ).color("red")
            )

        self.joining_broadcast = True
        try:
            try:
                reader, writer = await asyncio.wait_for(
                    pyroh.connect(
                        pyroh.node_addr(node_id),
                        alpn="proxhy.broadcast/1",
                        node=self.broadcast_pyroh_server.node,
                    ),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                raise CommandException(
                    TextComponent(
                        "Connection timed out! The broadcaster may be unavailable."
                    ).color("red")
                )
            except pyroh.iroh.iroh_ffi.IrohError as e:
                raise CommandException(
                    TextComponent(f"Connection failed: {e.message()}").color("red")
                )

            await self._setup_broadcastee_proxy(reader, writer, node_id)
        except CommandException:
            self.joining_broadcast = False
            raise

    async def _join_broadcast_with_streams(
        self,
        reader: pyroh.StreamReader,
        writer: pyroh.StreamWriter,
    ):
        if self.joining_broadcast:
            raise CommandException(
                TextComponent("You are already joining a broadcast!").color("red")
            )

        if self.clients:
            raise CommandException(
                TextComponent(
                    "You cannot join a broadcast while spectators are connected!"
                ).color("red")
            )

        self.joining_broadcast = True
        try:
            await self._setup_broadcastee_proxy(reader, writer, "compass-broker")
        except CommandException:
            self.joining_broadcast = False
            raise

    async def _setup_broadcastee_proxy(
        self,
        reader: pyroh.StreamReader,
        writer: pyroh.StreamWriter,
        identifier: str,
    ):
        BroadcasteeProxy = type(
            "BroadcasteeProxy",
            (*broadcastee_plugin_list, Proxy),
            {"username": self.username, "uuid": self.uuid},
        )

        new_proxy = BroadcasteeProxy(
            self.client.reader,
            self.client.writer,
            autostart=False,
        )

        await new_proxy.create_server(reader, writer)
        await self.transfer_to(new_proxy)

        self.server.writer.write_eof()
        # build player removal packet
        # because 0x01 doesn't clear for some reason bruh
        self.client.send_packet(
            0x38,
            VarInt.pack(4),
            VarInt.pack(len(self.gamestate.player_list)),
            *(
                UUID.pack(uuid.UUID(player.uuid))
                for player in self.gamestate.player_list.values()
            ),
        )

        await new_proxy.join(self.username, identifier)

    @subscribe("login_success")
    async def _broadcast_event_login_success(self, _match, _data):
        bc_pyroh_server_task = asyncio.create_task(
            self.initialize_broadcast_pyroh_server()
        )

        if self.dev_mode:
            self.client.chat(
                TextComponent("==> Dev Mode Activated <==").color("green").bold()
            )  # TODO: move to somewhere more appropriate
        else:
            bc_pyroh_server_task.add_done_callback(
                lambda _: asyncio.create_task(self.initialize_cc())
            )

        self._transformer.init_from_gamestate(self.uuid)

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
        self.access_token, self.username, self.uuid = await auth.load_auth_info(
            self.username
        )

        client = MinecraftPeerClient(
            mc_username=self.username,
            mc_access_token=self.access_token,
            mc_uuid=self.uuid,
            broker_url=BROKER_URL,
        )
        await client.register()
        client.on_connection_request = self.on_request  # type: ignore
        await client.start_session()

        self.compass_client = client
        self.client.chat(TextComponent("✓ Compass client initialized!").color("green"))

    @listen_server(0x07, blocking=True)
    async def _packet_respawn(self, buff: Buffer):
        for client in self.clients:
            if not client.watching:
                client._reset_spec()

        self.client.send_packet(0x07, buff.getvalue())

        if self._respawn_debounce_task is not None:
            self._respawn_debounce_task.cancel()

        async def spawn_bats_debounced():
            await asyncio.sleep(0.4)
            for client in self.clients:
                client._spawn_bat()
                if client.watching:
                    client._spectate(client.bat_eid)

        self._respawn_debounce_task = asyncio.create_task(spawn_bats_debounced())

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
        client.handle_client_task = asyncio.create_task(client.handle_client())

        # we await here to keep this method alive so pyroh doesn't close the reader/writer
        try:
            await client.handle_client_task
        except asyncio.CancelledError:
            pass
        finally:
            if client.open:
                await client.close()

    @subscribe("close")
    async def _broadcast_event_close(self, _match, reason):
        if self.logged_in:
            if hasattr(self, "broadcast_server_task") and self.broadcast_server_task:
                # self.broadcast_pyroh_server.close() this doesnt do anything ):
                # self.broadcast_server_task.cancel()
                if reason != "transfer":
                    try:
                        await asyncio.wait_for(
                            self.broadcast_pyroh_server.wait_closed(), timeout=0.5
                        )
                    except asyncio.TimeoutError:
                        pass

            try:
                await asyncio.wait_for(
                    self.disconnect_clients(reason="The broadcast owner disconnected!"),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                pass

            try:
                if self.compass_client is not None:
                    await asyncio.wait_for(
                        self.compass_client.stop_session(), timeout=0.5
                    )
                    self.compass_client = None
            except (
                httpx.HTTPError,
                asyncio.TimeoutError,
            ):
                pass

            self._transformer.reset()

    async def _expire_broadcast_request(self, request_id: str):
        if request_id in self.broadcast_invites:
            request = self.broadcast_invites.pop(request_id)
            self.client.chat(
                TextComponent("The broadcast invite from")
                .color("red")
                .appends(TextComponent(request.from_player).color("aqua"))
                .appends(TextComponent("expired!").color("red"))
            )

    def _build_broadcast_request_message(
        self,
        username: str,
        message: str,
        button_label: str,
        command: str,
        hover_text: str,
    ) -> TextComponent:
        return (
            TextComponent(username)
            .color("aqua")
            .bold()
            .appends(TextComponent(message).color("gold"))
            .appends(TextComponent("[").color("dark_gray"))
            .append(
                TextComponent(button_label)
                .color("green")
                .bold()
                .click_event("run_command", command)
                .hover_text(
                    TextComponent(hover_text)
                    .color("green")
                    .appends(TextComponent(username).color("aqua"))
                )
            )
            .append(TextComponent("]").color("dark_gray"))
        )

    async def on_request(self, request: ConnectionRequest):
        request_id = request.from_player
        self.broadcast_invites[request_id] = request

        if request.reason == "proxhy.broadcast":
            asyncio.create_task(self._samsung_ringtone())
            self.client.chat(
                self._build_broadcast_request_message(
                    request.from_player,
                    "has invited you to join their broadcast! You have 60 seconds to accept.",
                    "Join",
                    f"/bc join {request_id}",
                    "Join ",
                )
            )
            asyncio.get_running_loop().call_later(
                60,
                lambda: asyncio.create_task(self._expire_broadcast_request(request_id)),
            )
        elif request.reason == "proxhy.broadcast_request":
            asyncio.create_task(self._samsung_ringtone())
            with shelve.open(self.BC_DATA_PATH) as db:
                trusted: set[str] = db["trusted"]

            if request.from_uuid in trusted:
                self.client.chat(
                    TextComponent(request.from_player)
                    .color("aqua")
                    .bold()
                    .appends(
                        TextComponent(
                            "requested to join your broadcast! Auto-accepting..."
                        ).color("green")
                    )
                )
                del self.broadcast_invites[request_id]
                reader, writer = await request.accept()
                asyncio.create_task(self.on_broadcast_peer(reader, writer))
            else:
                self.client.chat(
                    self._build_broadcast_request_message(
                        request.from_player,
                        "wants to join your broadcast! You have 60 seconds to accept.",
                        "Accept",
                        f"/bc accept {request_id}",
                        "Let ",
                    )
                )
                asyncio.get_running_loop().call_later(
                    60,
                    lambda: asyncio.create_task(
                        self._expire_broadcast_request(request_id)
                    ),
                )
        else:
            self.client.chat(
                TextComponent(request.from_player)
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
                        .appends(TextComponent(request.from_player).color("aqua"))
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
        self, _match, data: tuple[int, *tuple[bytes, ...]]
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
                        packet_id, Int.pack(client.eid) + buff_data[4:]
                    )
        else:
            # Use transformer for other packets
            self._transformer.forward_clientbound_packet(
                packet_id, tuple(packet_data), self._spawn_players_after_position
            )

    @subscribe("sb_gamestate_update")
    async def _broadcast_event_sb_gamestate_update(
        self, _match, data: tuple[int, *tuple[bytes, ...]]
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
        # Use truncated fixed-point values to match what was sent to clients
        self._transformer._last_position = Vec3d(
            int(current_position.x * 32) / 32,
            int(current_position.y * 32) / 32,
            int(current_position.z * 32) / 32,
        )
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

    @listen_server(0x45)
    async def packet_title(self, buff: Buffer):
        action = buff.unpack(VarInt)
        if action in {0, 1}:  # set title, set subtitle
            for client in self.clients:
                if client.settings.titles.get() == "ON":
                    client.client.send_packet(0x45, buff.getvalue())

        self.client.send_packet(0x45, buff.getvalue())
