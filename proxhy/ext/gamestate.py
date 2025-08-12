# YIPPEEE
# this is going to be sooooooo fun

import asyncio
import json
import re

from ..datatypes import Buffer, Byte, String, VarInt
from ..mcmodels import Team
from ..proxhy import Proxhy, on_chat
from ._methods import method


class GameState(Proxhy):
    @method
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

    @method
    def _update_game(self, game: dict):
        self.game.update(game)
        if game.get("mode"):
            return self.rq_game.update(game)
        else:
            return

    @on_chat(lambda s: bool(re.match(r"^\{.*\}$", s)), "server", True)
    async def on_chat_locraw(self, message: str, buff: Buffer):
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
            self._update_game(json.loads(message))
