import re
import shelve
from pathlib import Path

from platformdirs import user_config_dir

from core.command import CommandException, CommandGroup, Lazy
from core.events import subscribe
from protocol.datatypes import Buffer, Chat, TextComponent
from proxhy.argtypes import AutoboopPlayer, HypixelPlayer
from proxhy.plugin import ProxhyPlugin
from proxhypixel.formatting import get_rankname


class AutoboopPluginState:
    AB_DATA_PATH: Path
    autoboop_group: CommandGroup


class AutoboopPlugin(ProxhyPlugin):
    def _init_misc(self):
        self.AB_DATA_PATH = Path(user_config_dir("proxhy")) / "autoboop.db"
        self.autoboop_group = CommandGroup("autoboop", "ab", help="Autoboop commands.")

        self._setup_autoboop_commands()

    def _setup_autoboop_commands(self):
        @self.autoboop_group.command("list", "ls")
        async def _autoboop_list(self):
            """List all players in autoboop."""
            with shelve.open(self.AB_DATA_PATH) as db:
                user_players = db.get(self.username, {})
                players = sorted(user_players.keys())
                if not players:
                    return TextComponent("No players in autoboop!").color("green")

                self.client.chat(TextComponent("Players in autoboop:").color("green"))
                msg = TextComponent("> ").color("green")
                for i, name in enumerate(players):
                    if i != 0:
                        msg.append(TextComponent(", ").color("green"))
                    msg.append(TextComponent(user_players[name]).color("aqua"))
                return msg

        @self.autoboop_group.command("add")
        async def _autoboop_add(self, player: HypixelPlayer):
            """Add a player to autoboop."""
            rankname = get_rankname(player._player)
            key = player.name.lower()

            with shelve.open(self.AB_DATA_PATH) as db:
                user_players = db.get(self.username, {})
                if user_players.get(key):
                    raise CommandException(
                        TextComponent("Player ")
                        .append(rankname)
                        .appends("is already in autoboop!")
                    )
                user_players[key] = rankname
                db[self.username] = user_players

            return (
                TextComponent("Added ")
                .color("green")
                .append(rankname)
                .appends(TextComponent("to autoboop!").color("green"))
            )

        @self.autoboop_group.command("remove", "rm")
        async def _autoboop_remove(self, _player: Lazy[AutoboopPlayer]):
            """Remove a player from autoboop"""
            key = _player.value.lower()

            with shelve.open(self.AB_DATA_PATH) as db:
                user_players = db.get(self.username, {})
                if key in user_players:
                    rankname = user_players.pop(key)
                    db[self.username] = user_players
                    return (
                        TextComponent("Removed ")
                        .color("green")
                        .append(rankname)
                        .appends(TextComponent("from autoboop!").color("green"))
                    )

            player = await _player
            rankname = get_rankname(player._player)
            raise CommandException(
                TextComponent("Player ").append(rankname).appends("is not in autoboop!")
            )

        self.command_registry.register(self.autoboop_group)

    @subscribe(r"chat:server:(Guild|Friend) > ([A-Za-z0-9_]+) joined.$")
    async def _autoboop_event_chat_server_guild_join(self, _match, buff: Buffer):
        player = re.match(
            r"^(Guild|Friend) > ([A-Za-z0-9_]+) joined\.$", buff.unpack(Chat)
        )

        if not player or not player.group(2):
            return

        player_name = str(player.group(2))

        with shelve.open(self.AB_DATA_PATH) as db:
            user_players = db.get(self.username, {})
            if player_name.lower() in user_players:
                self.server.chat(f"/boop {player_name}")

        self.client.send_packet(0x02, buff.getvalue())
