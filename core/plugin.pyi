import asyncio
from typing import Any, Coroutine, Literal, Optional

from core.events import EventListenerFunction
from protocol.datatypes import Buffer

from .net import Client, Server, State
from .proxy import PacketListenerList, Proxy

class Plugin:
    server: Server
    client: Client

    state: State
    open: bool

    CONNECT_HOST: tuple[str, int]

    handle_client_task: Optional[asyncio.Task]
    handle_server_task: Optional[asyncio.Task]

    _packet_listeners: dict[
        Literal["client", "server"],
        dict[tuple[int, State], PacketListenerList[Buffer]],
    ]
    _event_listeners: dict[str, list[EventListenerFunction]]

    async def handle_client(self) -> None: ...
    async def handle_server(self) -> None: ...
    async def emit(self, event: str, data: Any = None) -> list: ...
    async def close(self, reason: str = "", force: bool = False) -> None: ...
    async def transfer_to(self, new_proxy: Proxy) -> None: ...
    def create_task(self, coro: Coroutine) -> asyncio.Task: ...
