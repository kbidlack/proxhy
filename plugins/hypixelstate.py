import asyncio
from typing import TYPE_CHECKING, Callable, Optional

import orjson
from petty.events import listen_client, listen_server, subscribe
from petty.protocol.datatypes import Buffer, ByteArray, Chat, Int, String

from proxhypixel.models import Game

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin


class HypixelStatePlugin:
    client_type: str
    game: Game
    rq_game: Game
    received_locraw: asyncio.Event
    received_who: asyncio.Event
    entity_id: int
    get_health: Callable[[str], Optional[int | float]]
    real_players: Callable[[], set[str]]

    def _init_hypixelstate(self: ProxhyPlugin):
        self.client_type = ""

        self.game = Game()
        self.rq_game = Game()

        self.received_locraw = asyncio.Event()
        self.received_locraw.set()

        self.received_who = asyncio.Event()
        self.received_who.set()

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self: ProxhyPlugin, buff: Buffer):
        self.entity_id = buff.unpack(Int)
        self.received_locraw.clear()

        if not self.client_type == "lunar":
            self.upstream.send_packet(0x01, String.pack("/locraw"))

    def _update_game(self: ProxhyPlugin, game: dict):
        self.game.update(game)
        if game.get("mode"):
            return self.rq_game.update(game)
        else:
            return

    @subscribe(r"chat:server:\{.*\}$")
    async def _hypixelstate_event_chat_server_locraw(
        self: ProxhyPlugin, _match, buff: Buffer
    ):
        message = buff.unpack(Chat)

        if not self.received_locraw.is_set():
            if "limbo" in message:  # sometimes returns limbo right when you join
                if not self.gamestate.teams.values():  # probably in limbo
                    return
                elif self.client_type != "lunar":
                    await asyncio.sleep(0.1)
                    return self.upstream.send_packet(0x01, String.pack("/locraw"))
            else:
                self.received_locraw.set()
                self._update_game(orjson.loads(message))
        else:
            self.downstream.send_packet(0x02, buff.getvalue())
            self._update_game(orjson.loads(message))

    @listen_client(0x17)
    async def packet_plugin_channel(self: ProxhyPlugin, buff: Buffer):
        self.upstream.send_packet(0x17, buff.getvalue())

        channel = buff.unpack(String)
        data = buff.unpack(ByteArray)
        if channel == "MC|Brand":
            if b"lunarclient" in data:
                self.client_type = "lunar"
            elif b"vanilla" in data:
                self.client_type = "vanilla"

    def get_health(self: ProxhyPlugin, player_name: str) -> Optional[float]:
        health = None

        for name, score in (self.gamestate.scores.get("health") or {}).items():
            if name.casefold() == player_name.casefold():
                health = float(score.value)

        if player_name.casefold() == self.username.casefold():
            health = float(self.gamestate.health)

        if health is not None:
            return round(health, 1)

        return None

    def real_players(self: ProxhyPlugin) -> set[str]:
        return self.gamestate.real_players()
