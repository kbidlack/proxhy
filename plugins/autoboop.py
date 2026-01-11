import re
import shelve
from pathlib import Path

from platformdirs import user_config_dir

from core.events import subscribe
from core.plugin import Plugin
from protocol.datatypes import Buffer, Chat, TextComponent
from proxhy.argtypes import HypixelPlayer
from proxhy.command import CommandGroup, CommandRegistry
from proxhy.errors import CommandException


class AutoboopPlugin(Plugin):
    command_registry: CommandRegistry

    def _init_misc(self):
        self.AB_DATA_PATH = Path(user_config_dir("proxhy")) / "autoboop.db"

        # Set up autoboop command group
        self.autoboop_group = CommandGroup("autoboop", "ab")

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
            from proxhy.formatting import FormattedPlayer

            fplayer = FormattedPlayer(player._player)

            with shelve.open(self.AB_DATA_PATH) as db:
                if db.get(fplayer.name):
                    raise CommandException(
                        TextComponent("Player ")
                        .append(fplayer.rankname)
                        .appends("is already in autoboop!")
                    )
                db[fplayer.name] = fplayer.rankname

            return (
                TextComponent("Added ")
                .color("green")
                .append(fplayer.rankname)
                .appends(TextComponent("to autoboop!").color("green"))
            )

        @self.autoboop_group.command("remove", "rm")
        async def _autoboop_remove(self, player: HypixelPlayer):
            from proxhy.formatting import FormattedPlayer

            fplayer = FormattedPlayer(player._player)

            with shelve.open(self.AB_DATA_PATH) as db:
                if not db.get(fplayer.name):
                    raise CommandException(
                        TextComponent("Player ")
                        .append(fplayer.rankname)
                        .appends("is not in autoboop!")
                    )
                del db[fplayer.name]

            return (
                TextComponent("Removed ")
                .color("green")
                .append(fplayer.rankname)
                .appends(TextComponent("from autoboop!").color("green"))
            )

        self.command_registry.register(self.autoboop_group)

    @subscribe(r"chat:server:(Guild|Friend) > ([A-Za-z0-9_]+) joined.$")
    async def on_guild_join(self, buff: Buffer):
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
