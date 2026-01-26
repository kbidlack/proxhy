import asyncio
import typing

import pyroh

from core.events import listen_server, subscribe
from core.net import Server, State
from core.plugin import Plugin
from protocol.datatypes import Buffer, Short, String, VarInt


class BroadcasteeClosePlugin(Plugin):
    @subscribe("close")
    async def _broadcastee_event_close(self, _):
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
