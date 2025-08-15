"""Legacy compatibility plugin for existing Proxhy functionality."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..core import PluginBase, State, listen_client, listen_server
from ..core.datatypes import Buffer, VarInt, String, UnsignedShort

if TYPE_CHECKING:
    from ..core import ProxhyFramework


class LegacyProxhyPlugin(PluginBase):
    """Plugin that provides basic Proxhy functionality with backward compatibility."""
    
    @property
    def name(self) -> str:
        return "legacy_proxhy"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def description(self) -> str:
        return "Legacy compatibility plugin for existing Proxhy functionality"
    
    async def on_enable(self) -> None:
        """Register packet handlers when plugin is enabled."""
        # Register the packet handlers with the proxy's listener registry
        proxy = self.framework.proxy
        
        # Register basic handshake handler
        proxy.listeners.register_client_listener(
            0x00, State.HANDSHAKING, self.packet_handshake, blocking=True, override=True
        )
    
    async def packet_handshake(self, proxy, buff: Buffer):
        """Handle client handshake packet."""
        if len(buff.getvalue()) <= 2:  # https://wiki.vg/Server_List_Ping#Status_Request
            return

        buff.unpack(VarInt)  # protocol version
        buff.unpack(String)  # server address
        buff.unpack(UnsignedShort)  # server port
        next_state = buff.unpack(VarInt)

        proxy.state = State(next_state)