from core.plugin import Plugin
from protocol.datatypes import TextComponent
from proxhy.command import command
from proxhy.mcmodels import Game, Teams


class DebugPlugin(Plugin):
    game: Game
    rq_game: Game
    teams: Teams

    # sorta debug commands
    @command("game")
    async def _game(self):
        game_msg = TextComponent("Game:").color("green")
        self.client.chat(game_msg)
        for key in self.game.__annotations__:
            if value := getattr(self.game, key):
                key_value_msg = (
                    TextComponent(f"{key.capitalize()}: ")
                    .color("aqua")
                    .append(TextComponent(str(value)).color("yellow"))
                )
                self.client.chat(key_value_msg)

    @command("rqgame")
    async def _rqgame(self):
        rq_game_msg = TextComponent("Requeue Game:").color("green")
        self.client.chat(rq_game_msg)
        for key in self.rq_game.__annotations__:
            if value := getattr(self.rq_game, key):
                key_value_msg = (
                    TextComponent(f"{key.capitalize()}: ")
                    .color("aqua")
                    .append(TextComponent(str(value)).color("yellow"))
                )
                self.client.chat(key_value_msg)

    @command("teams")
    async def _teams(self):
        print("\n")
        for team in self.teams:
            print(f"Team: {team}")
        print("\n")
