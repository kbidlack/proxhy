from typing import Any, Literal

from protocol.datatypes import Buffer

from .net import Client, Server, State
from .proxy import ListenerList

class Plugin:
    server: Server
    client: Client

    state: State
    open: bool

    CONNECT_HOST: tuple[str, int, str, int]

    _packet_listeners: dict[
        Literal["client", "server"],
        dict[tuple[int, State], ListenerList[Buffer]],
    ]
    _event_listeners: dict[str, ListenerList[Any]]

    async def handle_client(self) -> None: ...
    async def handle_server(self) -> None: ...
    async def emit(self, event: str, data: Any = None) -> list: ...
    async def close(self, reason: str = "") -> None: ...
