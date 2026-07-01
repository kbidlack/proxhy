"""Offers Proxhy's tab-alignment resource pack to the client on join.

See :mod:`proxhy.respack` for how the pack is built and served. This plugin
sends the clientbound Resource Pack Send packet (0x48) shortly after the client
has logged in and the world has loaded, and reports the client's Resource Pack
Status reply (0x19) so it is not forwarded to the backend server.
"""

import asyncio
from typing import TYPE_CHECKING

from petty.events import listen_client, subscribe
from petty.protocol.datatypes import Buffer, String, TextComponent, VarInt
from plugins.commands import CommandException, command
from proxhy.respack import ResourcePackServer

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin

# Serverbound Resource Pack Status (0x19) result codes.
_STATUS = {
    0: "loaded successfully",
    1: "declined",
    2: "download failed",
    3: "accepted",
}


class ResourcePackPlugin:
    def _init_resource_pack(self: ProxhyPlugin):
        self._sent_resource_pack = False

    @subscribe("login_success")
    async def _resource_pack_on_login(self: ProxhyPlugin, _match, _data):
        if self.settings.resource_pack.get() != "ON":
            return
        if self._sent_resource_pack:
            return
        # Send slightly after the JoinGame packet so the client is settled in a
        # world; sending mid-login can make the client silently drop the pack.
        self.create_task(self._send_resource_pack_delayed())

    async def _send_resource_pack_delayed(self: ProxhyPlugin):
        await asyncio.sleep(1.5)
        if self.open and self.downstream.open and not self._sent_resource_pack:
            await self.send_resource_pack()

    async def send_resource_pack(self: ProxhyPlugin) -> bool:
        """Start the pack server (if needed) and offer the pack to the client."""
        try:
            server = ResourcePackServer.instance()
            url = await server.url()
        except Exception as e:
            self.logger.warning(f"could not start resource pack server: {e!r}")
            return False

        self._sent_resource_pack = True
        self.downstream.send_packet(0x48, String.pack(url), String.pack(server.sha1))
        self.logger.debug(f"sent resource pack {url} (sha1={server.sha1})")
        return True

    @command("pack", "resourcepack")
    async def _command_pack(self: ProxhyPlugin):
        """(Re)offer Proxhy's tab-alignment resource pack to your client."""
        self._sent_resource_pack = False
        if not await self.send_resource_pack():
            raise CommandException(
                TextComponent("Could not start the resource pack server!").color("red")
            )
        return (
            TextComponent(
                "Offered the Proxhy resource pack — watch for a status message."
            )
            .color("green")
            .append("\n")
            .append(
                TextComponent('If you see "declined", set your client\'s ').color(
                    "gray"
                )
            )
            .append(TextComponent('"Server Resource Packs"').color("yellow"))
            .append(
                TextComponent(
                    " option (Options > ... or your client's settings) to Enabled. "
                    "Server packs apply automatically and never show in the resource "
                    "pack menu."
                ).color("gray")
            )
        )

    @listen_client(0x19)
    async def _resource_pack_status(self: ProxhyPlugin, buff: Buffer):
        # Consume the client's response to our server-sent pack; Hypixel does
        # not send resource packs, so there is nothing upstream to forward to.
        # The 1.8 Resource Pack Status packet is: String hash, VarInt result.
        try:
            buff.unpack(String)  # 40-char pack hash
            result = buff.unpack(VarInt)
        except Exception:
            return
        label = _STATUS.get(result, "unknown")
        self.logger.debug(f"client resource pack status: {result} ({label})")

        if result in (0, 3):  # loaded / accepted
            if result == 0:
                self.downstream.chat(
                    TextComponent(
                        "Proxhy resource pack applied — tablist columns "
                        "are now aligned!"
                    ).color("green")
                )
        elif result == 1:  # declined
            self.downstream.chat(
                TextComponent(
                    "You declined the Proxhy resource pack; tablist columns "
                    "won't be aligned. "
                )
                .color("red")
                .append(
                    TextComponent(
                        'Set "Server Resource Packs" to Enabled and rejoin, '
                        "or run /pack."
                    ).color("gray")
                )
            )
        elif result == 2:  # download failed
            self.downstream.chat(
                TextComponent(
                    "Proxhy resource pack download failed — the local "
                    "pack server may be unreachable."
                ).color("red")
            )
