import re
import shelve
from pathlib import Path

from platformdirs import user_config_dir

from core.events import subscribe
from protocol.datatypes import Buffer, Chat, TextComponent
from proxhy.argtypes import HypixelPlayer
from proxhy.command import CommandGroup
from proxhy.errors import CommandException
from proxhy.formatting import get_rankname
from proxhy.plugin import ProxhyPlugin


class AutoboopPluginState:
    AB_DATA_PATH: Path
    autoboop_group: CommandGroup


class AutoboopPlugin(ProxhyPlugin):
    def _init_misc(self):
        self.AB_DATA_PATH = Path(user_config_dir("proxhy")) / "autoboop.db"
        self.autoboop_group = CommandGroup("autoboop", "ab")

        self._setup_autoboop_commands()

    def _setup_autoboop_commands(self):
        @self.autoboop_group.command("list", "ls")
        async def _autoboop_list(self):
            with shelve.open(self.AB_DATA_PATH) as db:
                players = sorted(db.keys())
                if not players:
                    return TextComponent("No players in autoboop!").color("green")

                self.client.chat(TextComponent("Players in autoboop:").color("green"))
                msg = TextComponent("> ").color("green")
                for i, name in enumerate(players):
                    if i != 0:
                        msg.append(TextComponent(", ").color("green"))
                    msg.append(TextComponent(db.get(name)).color("aqua"))
                return msg

        @self.autoboop_group.command("add")
        async def _autoboop_add(self, player: HypixelPlayer):
            rankname = get_rankname(player._player)

            with shelve.open(self.AB_DATA_PATH) as db:
                if db.get(player.name):
                    raise CommandException(
                        TextComponent("Player ")
                        .append(rankname)
                        .appends("is already in autoboop!")
                    )
                db[player.name] = rankname

            return (
                TextComponent("Added ")
                .color("green")
                .append(rankname)
                .appends(TextComponent("to autoboop!").color("green"))
            )

        @self.autoboop_group.command("remove", "rm")
        async def _autoboop_remove(self, player: HypixelPlayer):
            rankname = get_rankname(player._player)
            with shelve.open(self.AB_DATA_PATH) as db:
                if not db.get(player.name):
                    raise CommandException(
                        TextComponent("Player ")
                        .append(rankname)
                        .appends("is not in autoboop!")
                    )
                del db[player.name]

            return (
                TextComponent("Removed ")
                .color("green")
                .append(rankname)
                .appends(TextComponent("from autoboop!").color("green"))
            )

        self.command_registry.register(self.autoboop_group)

    @subscribe(r"chat:server:(Guild|Friend) > ([A-Za-z0-9_]+) joined.$")
    async def _autoboop_event_chat_server_guild_join(self, buff: Buffer):
        player = re.match(
            r"^(Guild|Friend) > ([A-Za-z0-9_]+) joined\.$", buff.unpack(Chat)
        )

        if not player or not player.group(2):
            return

        player_name = str(player.group(2))

        with shelve.open(self.AB_DATA_PATH) as db:
            if db.get(player_name):
                self.server.chat(f"/boop {player_name}")

        self.client.send_packet(0x02, buff.getvalue())
