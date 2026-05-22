import asyncio
import random
import re
import uuid as uuid_mod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import compass
import pyroh
from compass import CompassClient, RequestFailure
from petty.endpoints import Proxy
from petty.events import listen_server, subscribe
from petty.net import State
from petty.protocol.datatypes import (
    UUID,
    Angle,
    Buffer,
    Byte,
    Chat,
    Int,
    Short,
    Slot,
    String,
    TextComponent,
    VarInt,
)

import auth
from broadcasting.plugin import BroadcastPeerPlugin
from broadcasting.proxy import BroadcastPeerProxy
from broadcasting.transform import (
    PlayerTransformer,
    build_player_list_add_packet,
    build_spawn_player_packet,
)
from gamestate.state import Vec3d
from plugins.commands import CommandException, CommandGroup, Lazy, command
from proxhy.argtypes import BroadcastPlayer, MojangPlayer
from proxhy.p2p import StreamIntent
from proxhy.player_list import PlayerList, PlayerListSystem
from proxhy.utils import offline_uuid

from .broadcastee.proxy import broadcastee_plugin_list

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin

BROKER_URL = "http://163.192.4.69:8080/ticket"


@dataclass
class ConnectionRequest:
    from_player: str
    intent: StreamIntent
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    conn: pyroh.Connection

    expires_task: Optional[asyncio.TimerHandle] = None


class BroadcastPlugin:
    clients: list[BroadcastPeerPlugin]

    sent_broadcast_requests: set[str]
    sent_broadcast_invites: set[str]

    received_broadcast_requests: dict[str, ConnectionRequest]
    received_broadcast_invites: dict[str, ConnectionRequest]

    compass_client: Optional[CompassClient]
    broadcast_pyroh_server: pyroh.Server
    broadcast_server_task: asyncio.Task
    broadcast_chat_toggled: bool
    _transformer: PlayerTransformer

    endpoint: Optional[pyroh.Endpoint]
    compass_client: CompassClient

    def _init_broadcasting(self: ProxhyPlugin):
        self.clients: list[BroadcastPeerProxy] = []
        self.joining_broadcast: bool = False

        self.broadcast_chat_toggled = False

        self._respawn_debounce_task: Optional[asyncio.Task] = None

        self._transformer = PlayerTransformer(
            gamestate=self.gamestate,
            announce_func=self._announce_to_all,
            announce_player_func=self._announce_player_entity,
        )
        self.compass_client = CompassClient(
            broker_url=BROKER_URL,
            username="",
            uuid="",
            access_token="",
        )  # so I can say that compass_client is not optional lol

        self.sent_broadcast_invites = set()
        self.sent_broadcast_requests = set()
        self.received_broadcast_invites = dict()
        self.received_broadcast_requests = dict()
        self._last_broadcast_request_time: float = 0

        self._setup_broadcast_commands()
        self._setup_compass_commands()

    @property
    def whitelist(self: ProxhyPlugin) -> set[str]:
        return set(PlayerList("whitelist").names())

    def _setup_compass_commands(self: ProxhyPlugin):
        compass = CommandGroup("compass", help="Compass client commands.")

        @compass.command("initialize", "init")
        async def _command_compass_init(self: ProxhyPlugin):
            """Initialize the compass client."""
            if self.compass_client.registered:
                raise CommandException(
                    "The Compass client has already been initialized!"
                )

            self.create_task(self.initialize_cc())
            return TextComponent("Initializing Compass client...").color("yellow")

        @compass.command("status")
        async def _command_compass_status(self: ProxhyPlugin):
            """Get the compass client status."""

            return (
                TextComponent("Compass Client Status:\n")
                .color("gold")
                .append(TextComponent("Registered:").color("green"))
                .appends(
                    TextComponent(str(self.compass_client.registered)).color("yellow")
                )
                .appends(TextComponent("Broker URL:").color("green"), separator="\n")
                .appends(
                    TextComponent(self.compass_client.broker_url)
                    .color("yellow")
                    .hover_text(TextComponent("Click to copy").color("yellow"))
                    .click_event("suggest_command", self.compass_client.broker_url)
                )
            )

        # TODO: add /compass restart and /compass close (or deinit) if needed

        PlayerListSystem(
            "whitelist",
            "wl",
            label="the whitelist",
            help="Manage your compass whitelist.",
            key=lambda proxy: "whitelist",
            add_type=MojangPlayer,
            display=lambda player: f"§b{player.name}",
            on_change=lambda proxy: proxy._update_compass_client_settings(),
        ).register(self, onto=compass)

        self.command_registry.register(compass)

    def _setup_broadcast_commands(self: ProxhyPlugin):
        bc = CommandGroup("broadcast", "bc", help="Broadcast commands.")

        @bc.command("chat")
        async def _command_broadcast_chat(self: ProxhyPlugin, *message: str):
            """Send a message to the broadcast chat."""
            if not message:
                raise CommandException("Please provide a message to broadcast!")
            self.bc_chat(self.username, " ".join(message))

        @bc.command("list")
        async def _command_broadcast_list(self: ProxhyPlugin):
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

        @bc.command("join")
        async def _command_broadcast_join(
            self: ProxhyPlugin, player: Lazy[MojangPlayer]
        ):
            """Send a request to join a player's broadcast."""
            mplayer, endpoint_addr = await self._get_player_endpoint_addr(player)
            reader, writer = await self._ask_peer(
                name=mplayer.name,
                addr=endpoint_addr,
                reason=StreamIntent.BROADCAST_REQUEST,
                command="request",
                sent_msg="Requested to join",
                expired_msg="The broadcast request to ",
            )
            await self._join_broadcast_with_streams(reader, writer, endpoint_addr.id)

        @bc.command("accept")
        async def _command_broadcast_accept(self: ProxhyPlugin, username: str):
            """Accept a broadcast invite or request from a player."""

            request = self.received_broadcast_invites.get(
                username
            ) or self.received_broadcast_requests.get(username)
            if request is None:
                raise CommandException(
                    TextComponent(
                        "You have no pending broadcast invites or requests from that player!"
                    )
                )

            self._clear_pending_received(request)

            if request.intent == StreamIntent.BROADCAST_INVITE:
                self.downstream.chat(
                    TextComponent("Joining ")
                    .color("yellow")
                    .append(TextComponent(request.from_player).color("aqua"))
                    .appends("'s broadcast...")
                )
                request.writer.write(int.to_bytes(1))
                return await self._join_broadcast_with_streams(
                    request.reader, request.writer, request.conn.remote_node_id
                )

            self.downstream.chat(
                TextComponent("Accepting ")
                .color("green")
                .append(TextComponent(request.from_player).color("aqua"))
                .appends(" into your broadcast!")
            )
            request.writer.write(int.to_bytes(1))
            self.create_task(self.on_broadcast_peer(request.reader, request.writer))

        @bc.command("slime")
        async def _command_broadcast_slime(self: ProxhyPlugin, player: BroadcastPlayer):
            """Slime a player out of the broadcast."""
            client = player.client

            client.downstream.send_packet(
                0x40,
                Chat.pack(
                    TextComponent("You have been slimed out of the broadcast.").color(
                        "red"
                    )
                ),
            )
            client.downstream.close()

        @bc.command("invite")
        async def _command_broadcast_invite(
            self: ProxhyPlugin, player: Lazy[MojangPlayer]
        ):
            """Send a broadcast invite to a player."""
            mplayer, endpoint_addr = await self._get_player_endpoint_addr(player)
            result = await self._ask_peer(
                mplayer.name,
                addr=endpoint_addr,
                reason=StreamIntent.BROADCAST_INVITE,
                command="invite",
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
            self.create_task(self.on_broadcast_peer(reader, writer))

        @bc.command("server")
        async def _command_broadcast_server(self: ProxhyPlugin):
            try:
                # TODO: add more info?
                return (
                    TextComponent("Server Node ID:")
                    .color("green")
                    .appends(
                        TextComponent(self.broadcast_pyroh_server.id)
                        .color("yellow")
                        .hover_text(
                            TextComponent("Get Node ID to copy").color("yellow")
                        )
                        .click_event("suggest_command", self.broadcast_pyroh_server.id)
                    )
                )
            except AttributeError:
                raise CommandException(
                    "The broadcast server has not been initialized yet!"
                )

        self.command_registry.register(bc)

        PlayerListSystem(
            "trust",
            label="trusted players",
            help="Manage trusted players.",
            key=lambda proxy: "trusted",
            add_type=MojangPlayer,
            display=lambda player: f"§b{player.name}",
            uuid=lambda player: player.uuid,
        ).register(self, onto=bc)

    async def _get_player_endpoint_addr(
        self: ProxhyPlugin, player: Lazy[MojangPlayer]
    ) -> tuple[MojangPlayer, pyroh.EndpointAddr]:
        if not self.compass_client.registered:
            raise CommandException("The compass client is not connected yet!")

        player = await player

        try:
            async with asyncio.timeout(1):
                response = await self.compass_client.request(player.name)
        except IOError as e:
            raise CommandException(
                TextComponent("Unable to connect to ")
                .append(TextComponent(player.name).color("blue"))
                .appends(f"): [IOError(errno={e.errno})]")
            )
        except compass.RequestFailure as e:
            raise CommandException(e.details)
        except asyncio.TimeoutError:
            raise CommandException(
                f"Timed out while trying to connect to {player.name}"
            )
        except Exception as e:
            raise CommandException(
                f"An unknown error occurred while trying to connect to {player.name}! ({e})"
            )

        if not response.success:
            raise CommandException(response.details)

        return player, pyroh.EndpointAddr.from_ticket(response.details)

    async def _ask_peer(
        self: ProxhyPlugin,
        name: str,
        addr: pyroh.EndpointAddr,
        reason: StreamIntent,
        command: str,
        sent_msg: str,
        expired_msg: str,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self.endpoint is None:
            raise CommandException(
                TextComponent("The endpoint is not connected yet!")
                .appends(TextComponent("(Try again)").color("gold"))
                .click_event("run_command", f"/bc {command} {name}")
                .hover_text(TextComponent(f"/bc {command} {name}").color("gold"))
            )

        now = asyncio.get_event_loop().time()
        if now - self._last_broadcast_request_time < 5:
            raise CommandException(
                TextComponent(
                    "Please wait before sending another broadcast request!"
                ).color("red")
            )

        if name.casefold() == self.username.casefold():
            raise CommandException(TextComponent(f"You cannot {command} yourself!"))

        if name.casefold() in {c.username.casefold() for c in self.clients}:
            raise CommandException(
                TextComponent(name)
                .color("aqua")
                .appends("has already joined the broadcast!")
            )

        sent_set = (
            self.sent_broadcast_invites
            if reason == StreamIntent.BROADCAST_INVITE
            else self.sent_broadcast_requests
        )

        if name in sent_set:
            raise CommandException(
                TextComponent(f"You already have a pending {command} for")
                .appends(TextComponent(name).color("aqua"))
                .append("!")
            )

        if (
            reason == StreamIntent.BROADCAST_INVITE
            and name in self.sent_broadcast_requests
        ):
            raise CommandException(
                TextComponent("You already have a pending request for ")
                .appends(TextComponent(name).color("aqua"))
                .append("!")
            )

        if (
            reason == StreamIntent.BROADCAST_REQUEST
            and name in self.sent_broadcast_invites
        ):
            raise CommandException(
                TextComponent("You already have a pending invite for ")
                .appends(TextComponent(name).color("aqua"))
                .append("!")
            )

        try:
            async with asyncio.timeout(5):
                conn = await self.endpoint.connect(addr, alpn=b"proxhy/1")
                reader, writer = await conn.open_bi()
                writer.write(Byte.pack(reason))
                writer.write(self.username.zfill(16).encode("utf-8"))
        except asyncio.TimeoutError:
            raise CommandException(
                TextComponent("Timed out while connecting to")
                .appends(TextComponent(name).color("gold"))
                .append("!")
            )
        except OSError as e:
            raise CommandException(
                TextComponent("Failed to connect to")
                .appends(TextComponent(name).color("gold"))
                .append(f"! [OSError(errno={e.errno})]")
            )

        self._last_broadcast_request_time = asyncio.get_event_loop().time()
        self.create_task(self._iphone_ringtone())
        self.downstream.chat(
            TextComponent(sent_msg)
            .color("green")
            .appends(TextComponent(name).color("aqua"))
            .append("! They have 60 seconds to accept.")
        )

        sent_set.add(name)

        try:
            async with asyncio.timeout(60):
                accepted = int.from_bytes(await reader.read(1))
                if accepted:
                    return reader, writer
                writer.close()
                raise CommandException(
                    TextComponent(name).color("gold").appends(f"denied your {command}!")
                )
        except asyncio.TimeoutError:
            raise CommandException(
                TextComponent(expired_msg)
                .append(TextComponent(name).color("gold"))
                .appends("expired!")
            )
        except CommandException:
            raise
        except Exception as e:
            raise CommandException(
                TextComponent("An unknown error occurred while trying to connect to")
                .appends(TextComponent(name).color("gold"))
                .appends(f"! ({e})")
            )
        finally:
            sent_set.discard(name)

    async def _join_broadcast_with_streams(
        self: ProxhyPlugin,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        node_id: str,
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
            BroadcasteeProxy = type(
                "BroadcasteeProxy",
                (*broadcastee_plugin_list, Proxy),
                {"username": self.username, "uuid": self.uuid},
            )

            new_proxy = BroadcasteeProxy(
                self.downstream.reader,
                self.downstream.writer,
                autostart=False,
            )

            await new_proxy.create_server(reader, writer)
            await self.transfer_to(new_proxy)

            self.upstream.writer.write_eof()

            await new_proxy.join(self.username, node_id)
        except CommandException:
            self.joining_broadcast = False
            raise

    @subscribe("login_success")
    async def _broadcast_event_login_success(self: ProxhyPlugin, _match, _data):
        bc_pyroh_server_task = self.create_task(
            self.initialize_broadcast_pyroh_server()
        )

        if not self.dev_mode:
            bc_pyroh_server_task.add_done_callback(
                lambda _: self.create_task(self.initialize_cc())
            )

        self._transformer.init_from_gamestate(str(self.uuid))

    async def initialize_broadcast_pyroh_server(self: ProxhyPlugin):
        self.endpoint = await pyroh.Endpoint.bind(alpns=[b"proxhy/1"])
        self.broadcast_pyroh_server = self.endpoint.start_server(
            self.handle_new_connection
        )
        self.broadcast_server_task = self.create_task(
            self.broadcast_pyroh_server.serve_forever()
        )

        if self.dev_mode:
            self.downstream.chat(
                TextComponent("✓ Broadcast server initialized!").color("green")
            )

    async def initialize_cc(self: ProxhyPlugin):
        self.access_token, self.username, self.uuid = await auth.load_auth_info(
            self.username
        )
        self.uuid = self.uuid

        self.compass_client = CompassClient(
            broker_url=BROKER_URL,
            username=self.username,
            uuid=str(self.uuid),
            access_token=self.access_token,
        )

        if self.endpoint is None:
            self.downstream.chat(
                TextComponent(
                    "Failed to initialize the compass client. (this should not happen!)"
                ).color("red")
            )
            return  # TODO: log

        try:
            async with asyncio.timeout(5):
                await self.compass_client.register(self.endpoint)
                await self._update_compass_client_settings()
        except asyncio.TimeoutError:
            return self.downstream.chat(
                TextComponent("Failed to initialize compass client (timed out)!").color(
                    "red"
                )
            )
        except RequestFailure as e:
            return self.downstream.chat(
                TextComponent(f"Failed to initialize the compass client! ({e.details})")
            )
        except Exception as e:
            return self.downstream.chat(
                TextComponent(
                    f"Failed to initialize compass client due to an unknown error! ({e})"
                ).color("red")
            )

        if self.dev_mode:
            self.downstream.chat(
                TextComponent("✓ Compass client initialized!").color("green")
            )

    @listen_server(0x07, blocking=True)
    async def _packet_respawn(self: ProxhyPlugin, buff: Buffer):
        for client in self.clients:
            if not client.watching:
                client._reset_spec()

        self.downstream.send_packet(0x07, buff.getvalue())

        if self._respawn_debounce_task is not None:
            self._respawn_debounce_task.cancel()

        async def spawn_bats_debounced():
            await asyncio.sleep(0.4)
            for client in self.clients:
                client._spawn_bat()
                if client.watching:
                    client._spectate(client.bat_eid)

        self._respawn_debounce_task = self.create_task(spawn_bats_debounced())

    async def _update_compass_client_settings(self: ProxhyPlugin):
        await self.compass_client.update_settings(
            discoverable=self.settings.compass.discoverable.get() == "ON",
            whitelist=set()
            if self.settings.compass.whitelist.get() == "OFF"
            else self.whitelist,
        )

    @subscribe("setting:compass.discoverable")
    async def _setting_compass_discoverable(self: ProxhyPlugin, _match, data: list):
        await self._update_compass_client_settings()

    @subscribe("setting:compass.whitelist")
    async def _setting_compass_whitelist(self: ProxhyPlugin, _match, data: list):
        await self._update_compass_client_settings()

    async def on_broadcast_peer(
        self: ProxhyPlugin, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        client = BroadcastPeerProxy(
            reader, writer, ("localhost", 41222), autostart=False
        )

        client.proxy = self
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
        client.handle_downstream_task = client.create_task(client.handle_downstream())

        # we await here to keep this method alive so pyroh doesn't drop the reader/writer
        try:
            await client.handle_downstream_task
        except asyncio.CancelledError:
            pass
        finally:
            if client.open:
                await client.close()

    @subscribe("close")
    async def _broadcast_event_close(self: ProxhyPlugin, _match, reason):
        if self.logged_in:
            self.disconnect_clients(reason="The broadcast owner disconnected!")

            if hasattr(self, "broadcast_pyroh_server"):
                self.broadcast_pyroh_server.close()

            try:
                if self.compass_client is not None:
                    await asyncio.wait_for(self.compass_client.close(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

            self._transformer.reset()

    def _clear_pending_received(self: ProxhyPlugin, request: ConnectionRequest):
        if request.expires_task is not None:
            request.expires_task.cancel()
            request.expires_task = None

        if request.intent == StreamIntent.BROADCAST_INVITE:
            self.received_broadcast_invites.pop(request.from_player, None)
        elif request.intent == StreamIntent.BROADCAST_REQUEST:
            self.received_broadcast_requests.pop(request.from_player, None)

    async def _expire_received(self: ProxhyPlugin, request: ConnectionRequest):
        if request.intent == StreamIntent.BROADCAST_INVITE:
            if request.from_player not in self.received_broadcast_invites:
                return
        elif request.intent == StreamIntent.BROADCAST_REQUEST:
            if request.from_player not in self.received_broadcast_requests:
                return

        self._clear_pending_received(request)

        word = (
            "invite" if request.intent == StreamIntent.BROADCAST_INVITE else "request"
        )
        self.downstream.chat(
            TextComponent(f"The broadcast {word} from")
            .color("red")
            .appends(TextComponent(request.from_player).color("aqua"))
            .appends(TextComponent("expired!").color("red"))
        )
        request.writer.write(int.to_bytes(0))

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

    async def handle_new_connection(self: ProxhyPlugin, conn: pyroh.Connection):
        try:
            async with asyncio.timeout(3):
                reader, writer = await conn.accept_bi()
                intent = StreamIntent(int.from_bytes(await reader.read(1)))
                username = (await reader.read(16)).decode("utf-8").strip("0")
        except (asyncio.TimeoutError, ValueError) as e:
            self.logger.warning(
                f"handle_new_connection: failed to accept connection from {conn.remote_node_id!r}: {e}"
            )
            conn.close()
            return

        async def _reject():
            writer.write(int.to_bytes(0))
            await writer.drain()
            conn.close()

        if not self.dev_mode and self.settings.compass.verify_node_id:
            try:
                response = await self.compass_client.verify(
                    username, conn.remote_node_id
                )
            except RequestFailure:
                self.logger.warning(
                    f"handle_new_connection: compass verification request failed for {username!r}"
                )
                await _reject()
                return

            verified = response.success
            uid = response.details

            if not verified:
                self.logger.warning(
                    f"handle_new_connection: {username!r} failed compass verification"
                )
                await _reject()
                return
        else:
            try:
                async with asyncio.timeout(3):
                    uid = await self.hypixel_client.get_uuid(username)
            except Exception as e:
                err_msg = (
                    "timed out"
                    if isinstance(e, asyncio.TimeoutError)
                    else f"unknown error ({e!r})"
                )
                uid = str(offline_uuid(username))
                self.logger.warning(
                    f"handle_new_connection: {err_msg} while fetching uuid for {username!r};"
                    f"using hash of 'OfflinePlayer:{username}'"
                )

        existing = self.received_broadcast_invites.get(
            username
        ) or self.received_broadcast_requests.get(username)
        if existing is not None:
            self.logger.warning(
                f"handle_new_connection: duplicate connection from {username!r}, rejecting"
            )
            await _reject()
            return

        request = ConnectionRequest(
            from_player=username,
            intent=intent,
            reader=reader,
            writer=writer,
            conn=conn,
        )

        self.create_task(self._samsung_ringtone())

        if intent == StreamIntent.BROADCAST_INVITE:
            self.received_broadcast_invites[username] = request
            self.downstream.chat(
                self._build_broadcast_request_message(
                    request.from_player,
                    "has invited you to join their broadcast! You have 60 seconds to accept.",
                    "Accept",
                    f"/bc accept {request.from_player}",
                    "Accept invite from ",
                )
            )
            request.expires_task = asyncio.get_running_loop().call_later(
                60,
                lambda: self.create_task(self._expire_received(request)),
            )
        elif intent == StreamIntent.BROADCAST_REQUEST:
            self.received_broadcast_requests[username] = request
            if PlayerList("trusted").contains_uuid(uid):
                self.downstream.chat(
                    TextComponent(request.from_player)
                    .color("aqua")
                    .bold()
                    .appends(
                        TextComponent(
                            " requested to join your broadcast! Auto-accepting..."
                        ).color("green")
                    )
                )
                self._clear_pending_received(request)
                request.writer.write(int.to_bytes(1))
                self.create_task(self.on_broadcast_peer(request.reader, request.writer))
                return

            self.downstream.chat(
                self._build_broadcast_request_message(
                    request.from_player,
                    "wants to join your broadcast! You have 60 seconds to accept.",
                    "Accept",
                    f"/bc accept {request.from_player}",
                    "Let ",
                )
            )
            request.expires_task = asyncio.get_running_loop().call_later(
                60,
                lambda: self.create_task(self._expire_received(request)),
            )

    def disconnect_clients(
        self: ProxhyPlugin, reason: str = "The broadcast was stopped!"
    ):
        for client in self.clients:
            client.downstream.send_packet(
                0x40,
                Chat.pack(TextComponent(reason).color("red")),
            )
            self.create_task(client.close())

    def bc_chat(self: ProxhyPlugin, username: str, msg: str):
        formatted_msg = (
            TextComponent("[")
            .color("dark_gray")
            .append(TextComponent("BROADCAST").color("red"))
            .append(TextComponent("]").color("dark_gray"))
            .appends(TextComponent(f"{username}:").color("aqua"))
            .appends(TextComponent(msg).color("white"))
        )
        self.downstream.chat(formatted_msg)

    def _announce_to_all(self: ProxhyPlugin, packet_id: int, data: bytes):
        """Send a packet to all spectator clients."""
        for client in self.clients:
            if client.state == State.PLAY:
                client.downstream.send_packet(packet_id, data)

    def _announce_player_entity(self: ProxhyPlugin, packet_id: int, data: bytes):
        """Send a packet about the player entity to spectators who have it spawned."""
        for client in self.clients:
            if (
                client.state == State.PLAY
                and client.eid in self._transformer.player_spawned_for
            ):
                client.downstream.send_packet(packet_id, data)

    def _filter_chat_message(self: ProxhyPlugin, buff: Buffer):
        msg = buff.unpack(Chat)
        system_msgs = {
            "You already tipped everyone that has boosters active, "
            "so there isn't anybody to be tipped right now!",  # <- + ^ = one message
            "You are sending commands too fast! Please slow down.",
            "Slow down! You can only use /tip every few seconds.",
            r"\{.*\}",
        }
        system_message = any(re.fullmatch(bm, msg) for bm in system_msgs)
        for client in self.clients:
            if not system_message or client.settings.hide_system_messages.get() != "ON":
                client.downstream.send_packet(0x02, buff.getvalue())

    @subscribe("cb_gamestate_update")
    async def _broadcast_event_cb_gamestate_update(
        self: ProxhyPlugin, _, data: tuple[int, bytes]
    ):
        packet_id, packet_data = data

        buff = Buffer(packet_data)
        """Forward a clientbound packet to spectators with appropriate transformations."""
        if not self.clients:
            return
        # Handle Join Game specially to update EID per client
        if packet_id == 0x01:
            self._transformer._player_eid = buff.unpack(Int)
            self._transformer.reset()

            # Forward with modified EID for each client
            for client in self.clients:
                if client.state == State.PLAY:
                    client.downstream.send_packet(
                        packet_id, Int.pack(client.eid) + buff.getvalue()[4:]
                    )
        elif packet_id == 0x02:
            self._filter_chat_message(buff=Buffer(buff.getvalue()))
        else:
            # Use transformer for other packets
            self._transformer.forward_clientbound_packet(
                packet_id, (packet_data,), self._spawn_players_after_position
            )

    @subscribe("sb_gamestate_update")
    async def _broadcast_event_sb_gamestate_update(
        self: ProxhyPlugin, _, data: tuple[int, bytes]
    ):
        packet_id, packet_data = data
        if self.clients:
            self._transformer.handle_serverbound_packet(packet_id, packet_data)

    def _spawn_players_after_position(self: ProxhyPlugin):
        """Callback to spawn player for clients after position update."""
        for client in self.clients:
            if client.state == State.PLAY:
                self._spawn_player_for_client(client)

    def _spawn_player_for_client(self: ProxhyPlugin, client: BroadcastPeerPlugin):
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
        client.downstream.send_packet(0x0C, spawn_data)

        # Send full player metadata (includes skin layers at index 10)
        player_entity = self.gamestate.get_entity(self.gamestate.player_entity_id)
        if player_entity and player_entity.metadata:
            # Use gamestate's _pack_metadata to build the full metadata
            full_metadata = self.gamestate._pack_metadata(player_entity.metadata)
            client.downstream.send_packet(
                0x1C,  # Entity Metadata
                VarInt.pack(self._transformer.player_eid) + full_metadata,
            )

        # Send Entity Head Look (0x19) to ensure head rotation is correct
        client.downstream.send_packet(
            0x19,
            VarInt.pack(self._transformer.player_eid)
            + Angle.pack(current_rotation.yaw),
        )

        # Send current held item from gamestate
        held_item = self.gamestate.get_held_item()
        if held_item and held_item.item:
            client.downstream.send_packet(
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
                client.downstream.send_packet(
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
                client.downstream.send_packet(
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

    def _ensure_player_in_tab_list(self: ProxhyPlugin, client: BroadcastPeerPlugin):
        """Ensure the player being watched is in the spectator's tab list."""
        # Normalize UUID to hyphenated format to match gamestate storage
        try:
            normalized_uuid = str(uuid_mod.UUID(self._transformer.player_uuid))
        except ValueError:
            normalized_uuid = self._transformer.player_uuid

        player_info = self.gamestate.player_list.get(normalized_uuid)

        try:
            normalized_uuid_obj = uuid_mod.UUID(self._transformer.player_uuid)
            client.downstream.send_packet(
                0x38,
                VarInt.pack(4),  # action: remove player
                VarInt.pack(1),
                UUID.pack(normalized_uuid_obj),
            )
        except ValueError:
            pass

        if player_info:
            data = build_player_list_add_packet(
                player_uuid=self._transformer.player_uuid,
                player_name=player_info.name,
                properties=player_info.properties,
                gamemode=0,  # force survival so the client renders the Spawn Player
                ping=player_info.ping,
                display_name=player_info.display_name,
            )
        else:
            data = build_player_list_add_packet(
                player_uuid=self._transformer.player_uuid,
                player_name=self.username,
            )

        client.downstream.send_packet(0x38, data)

    @listen_server(0x45)
    async def packet_title(self: ProxhyPlugin, buff: Buffer):
        action = buff.unpack(VarInt)
        if action in {0, 1}:  # set title, set subtitle
            for client in self.clients:
                if client.settings.titles.get() == "ON":
                    client.downstream.send_packet(0x45, buff.getvalue())

        self.downstream.send_packet(0x45, buff.getvalue())

    @command("chat", "ch")
    async def _command_chat(self: ProxhyPlugin, channel: str):
        if channel in {"b", "bc", "broadcast"}:
            self.broadcast_chat_toggled = not self.broadcast_chat_toggled
            self.downstream.chat(
                TextComponent("Toggled broadcast chat")
                .color("green")
                .appends(
                    TextComponent("ON" if self.broadcast_chat_toggled else "OFF")
                    .color("green" if self.broadcast_chat_toggled else "red")
                    .bold()
                )
            )
        else:
            self.upstream.chat(f"/chat {channel}")

    @subscribe("chat:client:.*")
    async def _event_chat_client_any(
        self: ProxhyPlugin, _match: re.Match, buff: Buffer
    ):
        msg = buff.unpack(String)
        if msg.startswith("/"):
            return  # let commands plugin handle it
        elif self.broadcast_chat_toggled:
            self.bc_chat(self.username, msg)
        else:
            self.upstream.send_packet(0x01, buff.getvalue())
