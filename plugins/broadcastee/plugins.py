import asyncio
import re
import typing
from typing import TYPE_CHECKING

import pyroh

from core.events import listen_server, subscribe
from core.net import Server, State
from core.plugin import Plugin
from protocol.datatypes import Buffer, Short, String, VarInt

if TYPE_CHECKING:
    from proxhy.settings import ProxhySettings


class BroadcasteeClosePlugin(Plugin):
    @subscribe("close")
    async def _broadcastee_event_close(self, _match, _data):
        typing.cast(pyroh.StreamWriter, self.server.writer)
        self.server.writer.write_eof()
        await self.server.writer.drain()

    @listen_server(0x46, blocking=True)
    async def _packet_set_compression(self, buff: Buffer):
        self.server.compression_threshold = buff.unpack(VarInt)
        self.server.compression = True

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


class BroadcasteeSettingsPlugin(Plugin):
    settings: ProxhySettings

    @listen_server(0x3F)
    async def packet_client_plugin_message(self, buff: Buffer):
        channel = buff.unpack(String)  # e.g. PROXHY|Events for proxhy events channel
        data = buff.read()

        await self.emit(f"plugin:{channel}", data)

    @subscribe(r"plugin:PROXHY\|Events")
    async def _event_login_success(self, _match, _data):
        if Buffer(_data).unpack(String) == "login_success":
            for setting in self.settings.broadcast.get_all_settings():
                value = setting.get()
                self.server.send_packet(
                    0x17,
                    String.pack("PROXHY|Settings"),
                    String.pack(setting._key),
                    String.pack(value),
                    String.pack(value),
                )

    @subscribe(r"setting:broadcast\..*")
    async def _setting_broadcast_any(self, match: re.Match[str], data: list[str]):
        setting = match.string.split(":")[1]

        old_value, new_value = data
        self.server.send_packet(
            0x17,
            String.pack("PROXHY|Settings"),
            String.pack(setting),
            String.pack(old_value),
            String.pack(new_value),
        )
