import asyncio
import json

from core.events import listen_client, listen_server, subscribe
from core.plugin import ProxhyPlugin
from protocol.datatypes import Buffer, ByteArray, Chat, Int, String
from proxhy.gamestate import GameState
from proxhy.mcmodels import Game


class HypixelStatePlugin(ProxhyPlugin):
    game: Game
    gamestate: GameState

    def _init_hypixelstate(self):
        self.client_type = ""

        self.game = Game()
        self.rq_game = Game()

        self.received_locraw = asyncio.Event()
        self.received_locraw.set()

        self.received_who = asyncio.Event()
        self.received_who.set()

    @listen_server(0x01, blocking=True)
    async def packet_join_game(self, buff: Buffer):
        self.entity_id = buff.unpack(Int)
        self.received_locraw.clear()

        if not self.client_type == "lunar":
            self.server.send_packet(0x01, String("/locraw"))

    def _update_game(self, game: dict):
        self.game.update(game)
        if game.get("mode"):
            return self.rq_game.update(game)
        else:
            return

    @subscribe(r"chat:server:\{.*\}$")
    async def _hypixelstate_event_chat_server_locraw(self, buff: Buffer):
        message = buff.unpack(Chat)

        if not self.received_locraw.is_set():
            if "limbo" in message:  # sometimes returns limbo right when you join
                if not self.gamestate.teams.values():  # probably in limbo
                    return
                elif self.client_type != "lunar":
                    await asyncio.sleep(0.1)
                    return self.server.send_packet(0x01, String("/locraw"))
            else:
                self.received_locraw.set()
                self._update_game(json.loads(message))
        else:
            self.client.send_packet(0x02, buff.getvalue())
            self._update_game(json.loads(message))

    @listen_client(0x17)
    async def packet_plugin_channel(self, buff: Buffer):
        self.server.send_packet(0x17, buff.getvalue())

        channel = buff.unpack(String)
        data = buff.unpack(ByteArray)
        if channel == "MC|Brand":
            if b"lunarclient" in data:
                self.client_type = "lunar"
            elif b"vanilla" in data:
                self.client_type = "vanilla"
