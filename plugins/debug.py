from core.events import listen_server, subscribe
from core.plugin import Plugin
from protocol.datatypes import (
    UUID,
    Boolean,
    Buffer,
    Chat,
    String,
    TextComponent,
    VarInt,
)
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

    # @subscribe("chat:server:.*")
    # async def log_chat_msg(self, buff: Buffer):
    #     buff = Buffer(buff.getvalue())
    #     print(buff.unpack(Chat))

    # @listen_server(0x38)
    # async def log_0x38(self, buff: Buffer):
    #     action = buff.unpack(VarInt)  # which of the 5 actions
    #     count = buff.unpack(VarInt)  # number of players affected
    #     print(f"\n0x38 Player Info packet: action={action}, count={count}")

    #     for _ in range(count):
    #         uuid = buff.unpack(UUID)
    #         print(f" - UUID: {uuid}")

    #         if action == 0:  # ADD_PLAYER
    #             name = buff.unpack(String)
    #             props_count = buff.unpack(VarInt)
    #             props = []
    #             for _ in range(props_count):
    #                 key = buff.unpack(String)
    #                 value = buff.unpack(String)
    #                 signed = buff.unpack(Boolean)
    #                 sig = buff.unpack(String) if signed else None
    #                 props.append((key, value, sig))
    #             gamemode = buff.unpack(VarInt)
    #             ping = buff.unpack(VarInt)
    #             has_display = buff.unpack(Boolean)
    #             display = buff.unpack(Chat) if has_display else None
    #             print(
    #                 f"   ADD_PLAYER name={name}, gamemode={gamemode}, ping={ping}, display={display}, len(props)={len(props)}"
    #             )

    #         elif action == 1:  # UPDATE_GAMEMODE
    #             gamemode = buff.unpack(VarInt)
    #             print(f"   UPDATE_GAMEMODE -> {gamemode}")

    #         elif action == 2:  # UPDATE_LATENCY
    #             ping = buff.unpack(VarInt)
    #             print(f"   UPDATE_LATENCY -> {ping} ms")

    #         elif action == 3:  # UPDATE_DISPLAY_NAME
    #             has_display = buff.unpack(Boolean)
    #             display = buff.unpack(Chat) if has_display else None
    #             print(f"   UPDATE_DISPLAY_NAME -> {display}")

    #         elif action == 4:  # REMOVE_PLAYER
    #             pass
    #             print("   REMOVE_PLAYER")

    #         else:
    #             pass
    #             print(f"   Unknown action {action}")
    #     print("")
