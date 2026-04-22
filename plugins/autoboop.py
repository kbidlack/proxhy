import re
from typing import TYPE_CHECKING

from petty.events import subscribe
from petty.protocol.datatypes import Buffer, Chat

from plugins.commands import CommandGroup
from proxhy.argtypes import HypixelPlayer
from proxhy.player_list import PlayerList, PlayerListSystem
from proxhypixel.formatting import get_rankname

if TYPE_CHECKING:
    from proxhy.plugin import ProxhyPlugin


class AutoboopPlugin:
    autoboop_group: CommandGroup

    def _init_misc(self: ProxhyPlugin):
        self.autoboop_group = PlayerListSystem(
            "autoboop",
            "ab",
            help="Autoboop commands.",
            key=lambda proxy: f"autoboop:{proxy.username}",
            add_type=HypixelPlayer,
            display=lambda player: get_rankname(player._player),
        ).register(self)

    @subscribe(r"chat:server:(Guild|Friend) > ([A-Za-z0-9_]+) joined.$")
    async def _autoboop_event_chat_server_guild_join(
        self: ProxhyPlugin, _match, buff: Buffer
    ):
        player = re.match(
            r"^(Guild|Friend) > ([A-Za-z0-9_]+) joined\.$", buff.unpack(Chat)
        )

        if not player or not player.group(2):
            return

        player_name = str(player.group(2))

        if PlayerList(f"autoboop:{self.username}").contains(player_name):
            self.upstream.chat(f"/boop {player_name}")

        self.downstream.send_packet(0x02, buff.getvalue())
