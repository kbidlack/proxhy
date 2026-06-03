import asyncio
import re
from asyncio import StreamReader, StreamWriter
from typing import TYPE_CHECKING

from petty.events import listen_client, listen_server, subscribe
from petty.net import ServerStream, State
from petty.protocol.datatypes import Buffer, Short, String, VarInt
from plugins.commands import CommandsPlugin, command

if TYPE_CHECKING:
    from plugins.broadcastee.plugin import BroadcasteePlugin


class BroadcasteeClosePlugin:
    @subscribe("close")
    async def _broadcastee_event_close(self: BroadcasteePlugin, _match, _data):
        self.upstream.writer.write_eof()
        await self.upstream.writer.drain()

    @listen_server(0x46, blocking=True)
    async def _packet_set_compression(self: BroadcasteePlugin, buff: Buffer):
        self.upstream.send_packet(0x46)
        self.upstream.compression_threshold = buff.unpack(VarInt)
        self.upstream.compression = True

    async def create_server(
        self: BroadcasteePlugin,
        reader: StreamReader,
        writer: StreamWriter,
    ):
        self.upstream = ServerStream(reader, writer)

    async def join(self: BroadcasteePlugin, username: str, node_id: str):
        self.state = State.PLAY

        self.handle_upstream_task = asyncio.create_task(self.handle_upstream())

        self.upstream.send_packet(
            0x00,
            VarInt.pack(47),
            String.pack(node_id),
            Short.pack(25565),
            VarInt.pack(State.LOGIN.value),
        )
        self.upstream.send_packet(0x00, String.pack(username))

        await self.upstream.drain()


class BroadcasteeSettingsPlugin:
    @listen_server(0x3F)
    async def packet_client_plugin_message(self: BroadcasteePlugin, buff: Buffer):
        channel = buff.unpack(String)  # e.g. PROXHY|Events for proxhy events channel
        data = Buffer(buff.read())

        await self.emit(f"plugin:{channel}", data)

    @subscribe(r"plugin:PROXHY\|Events")
    async def _event_login_success(
        self: BroadcasteePlugin, _match: re.Match, buff: Buffer
    ):
        if buff.unpack(String) == "login_success":
            for setting in self.settings.broadcast.get_all_settings():
                value = setting.get()
                self.upstream.send_packet(
                    0x17,
                    String.pack("PROXHY|Settings"),
                    String.pack(setting._key),
                    String.pack(value),
                    String.pack(value),
                )

    @subscribe(r"setting:broadcast\..*")
    async def _setting_broadcast_any(
        self: BroadcasteePlugin, match: re.Match[str], data: list[str]
    ):
        setting = match.string.split(":")[1]

        old_value, new_value = data
        self.upstream.send_packet(
            0x17,
            String.pack("PROXHY|Settings"),
            String.pack(setting),
            String.pack(old_value),
            String.pack(new_value),
        )


class BroadcasteeCommandsPlugin(CommandsPlugin):
    @command("help")
    async def _command_help(self: BroadcasteePlugin, *args: str):
        self.upstream.chat(f"/help {' '.join(args)}")

    @listen_client(0x14)
    async def packet_tab_complete(self: BroadcasteePlugin, buff: Buffer):
        self.upstream.send_packet(0x14, buff.getvalue())

    @listen_server(0x3A)
    async def packet_server_tab_complete(self: BroadcasteePlugin, buff: Buffer):
        self.downstream.send_packet(0x3A, buff.getvalue())
