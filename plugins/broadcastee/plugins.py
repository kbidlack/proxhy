import asyncio
import typing

import pyroh

from core.events import subscribe
from core.net import Server, State
from core.plugin import Plugin
from protocol.datatypes import Short, String, VarInt


class BroadcasteeClosePlugin(Plugin):
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
