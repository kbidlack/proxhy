from typing import TYPE_CHECKING

from petty.events import listen_client, listen_server
from petty.protocol.datatypes import Buffer, Chat, String, TextComponent

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin


class ChatPlugin:
    @listen_server(0x02)
    async def packet_server_chat_message(self: ProxhyPlugin, buff: Buffer):
        results = await self.emit(
            f"chat:server:{buff.unpack(Chat)}", Buffer(buff.getvalue())
        )
        # if there are no handlers
        if not results:
            self.downstream.send_packet(0x02, buff.getvalue())

    @listen_client(0x01)
    async def packet_client_chat_message(self: ProxhyPlugin, buff: Buffer):
        results = await self.emit(
            f"chat:client:{buff.unpack(String)}", Buffer(buff.getvalue())
        )
        if not results:
            self.upstream.send_packet(0x01, buff.getvalue())

    async def send_api_key_err(self: ProxhyPlugin):
        self.downstream.chat(self.get_api_key_err())

    def get_api_key_err(self: ProxhyPlugin):
        return (
            TextComponent("Hypixel API key is invalid! Get one at ")
            .color("red")
            .append(
                TextComponent("developer.hypixel.net")
                .underlined()
                .click_event("open_url", "https://developer.hypixel.net/dashboard/")
                .color("white")
            )
            .append(TextComponent(" and enter it using ").color("red"))
            .append(
                TextComponent("/key hypixel")
                .underlined()
                .click_event("suggest_command", "/key hypixel ")
                .color("white")
            )
            .append(TextComponent(".").color("red"))
        )

    async def send_seraph_no_key_err(self: ProxhyPlugin):
        self.downstream.chat(self.get_seraph_no_key_err())

    def get_seraph_no_key_err(self: ProxhyPlugin):
        return (
            TextComponent("No Seraph API key set! Get one at ")
            .color("yellow")
            .append(
                TextComponent("seraph.si")
                .underlined()
                .click_event("open_url", "https://seraph.si/")
                .color("white")
            )
            .append(TextComponent(" and enter it using ").color("yellow"))
            .append(
                TextComponent("/key seraph")
                .underlined()
                .click_event("suggest_command", "/key seraph ")
                .color("white")
            )
            .append(TextComponent(".").color("yellow"))
        )
