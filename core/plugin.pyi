import asyncio
from typing import Any, Literal, Optional

from protocol.datatypes import Buffer

from .net import Client, Server, State
from .proxy import ListenerList

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
        dict[tuple[int, State], ListenerList[Buffer]],
    ]
    _event_listeners: dict[str, ListenerList[Any]]

    async def handle_client(self) -> None: ...
    async def handle_server(self) -> None: ...
    async def emit(self, event: str, data: Any = None) -> list: ...
    async def close(self, reason: str = "", force: bool = False) -> None: ...

class ProxhyPlugin(Plugin):
    FAKE_CONNECT_HOST: tuple[str, int]

    dev_mode: bool
