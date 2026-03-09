from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin

from petty.events import listen_client, listen_server
from petty.protocol.datatypes import Buffer, Chat, String


class ChatPlugin:
    @listen_server(0x02)
    async def packet_server_chat_message(self: ProxhyPlugin, buff: Buffer):
        results = await self.emit(
            f"chat:server:{buff.unpack(Chat)}", Buffer(buff.getvalue())
        )
        # if there are no handlers
        if not results:
            self.client.send_packet(0x02, buff.getvalue())

    @listen_client(0x01)
    async def packet_client_chat_message(self: ProxhyPlugin, buff: Buffer):
        results = await self.emit(
            f"chat:client:{buff.unpack(String)}", Buffer(buff.getvalue())
        )
        if not results:
            self.server.send_packet(0x01, buff.getvalue())
