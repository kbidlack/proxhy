# YIPPEEE
# this is going to be sooooooo fun

import asyncio
import json

from core.events import listen_client, listen_server, subscribe
from core.plugin import Plugin
from protocol.datatypes import Buffer, Byte, ByteArray, Chat, Int, String, VarInt
from proxhy.mcmodels import Game, Team, Teams


class HypixelStatePlugin(Plugin):
    game: Game

    def _init_gamestate(self):
        self.teams: Teams = Teams()

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

    def _update_teams(self, buff: Buffer):
        name = buff.unpack(String)
        mode = buff.unpack(Byte)

        # team creation
        if mode == 0:
            display_name = buff.unpack(String)
            prefix = buff.unpack(String)
            suffix = buff.unpack(String)
            friendly_fire = buff.unpack(Byte)
            name_tag_visibility = buff.unpack(String)
            color = buff.unpack(Byte)

            player_count = buff.unpack(VarInt)
            players = set()
            for _ in range(player_count):
                players.add(buff.unpack(String))

            self.teams.append(
                Team(
                    name,
                    display_name,
                    prefix,
                    suffix,
                    friendly_fire,
                    name_tag_visibility,
                    color,
                    players,
                )
            )
        # team removal
        elif mode == 1:
            self.teams.delete(name)
        # team information updation
        elif mode == 2:
            team = self.teams.get(name)
            if team:
                team.display_name = buff.unpack(String)
                team.prefix = buff.unpack(String)
                team.suffix = buff.unpack(String)
                team.friendly_fire = buff.unpack(Byte)
                team.name_tag_visibility = buff.unpack(String)
                team.color = buff.unpack(Byte)

        # add/remove players to team
        elif mode in {3, 4}:
            add = True if mode == 3 else False
            player_count = buff.unpack(VarInt)
            players = {buff.unpack(String) for _ in range(player_count)}

            if add:
                self.teams.get(name).players |= players
            else:
                self.teams.get(name).players -= players

    def _update_game(self, game: dict):
        self.game.update(game)
        if game.get("mode"):
            return self.rq_game.update(game)
        else:
            return

    @subscribe(r"chat:server:\{.*\}$")
    async def on_chat_locraw(self, buff: Buffer):
        message = buff.unpack(Chat)

        if not self.received_locraw.is_set():
            if "limbo" in message:  # sometimes returns limbo right when you join
                if not self.teams:  # probably in limbo
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

    @listen_server(0x3E)
    async def packet_teams(self, buff: Buffer):
        # game state
        self._update_teams(buff.clone())

        self.client.send_packet(0x3E, buff.getvalue())
        await self.emit("update_teams")

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
