import asyncio

from core.events import subscribe
from proxhy.gamestate import GameState
from proxhy.plugin import ProxhyPlugin


class GameStatePluginState:
    gamestate: GameState
    cb_gamestate_task: asyncio.Task
    sb_gamestate_task: asyncio.Task


class GameStatePlugin(ProxhyPlugin):
    def _init_0_gamestate(self):  # since other plugins require we put 0
        self.gamestate = GameState()

        self.cb_gamestate_task = asyncio.create_task(self._update_clientbound())

    @subscribe("login_success")
    async def _gamestate_event_login_success(self, _):
        self.sb_gamestate_task = asyncio.create_task(self._update_serverbound())

    async def _update_clientbound(self):
        while self.open:
            id, *data = await self.client.pqueue.get()
            self.gamestate.update(id, b"".join(data))
            await self.emit(
                "cb_gamestate_update", (id, *data)
            )  # TODO: avoid unpacking? by passing tuple[bytes] everywhere

    async def _update_serverbound(self):
        while self.open:
            id, *data = await self.server.pqueue.get()
            self.gamestate.update_serverbound(id, b"".join(data))
            await self.emit("sb_gamestate_update", (id, *data))
