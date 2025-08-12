from ..command import command
from ..datatypes import TextComponent
from ..proxhy import Proxhy


class Commands(Proxhy):
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
