from protocol.datatypes import TextComponent
from proxhy.command import command
from proxhy.plugin import ProxhyPlugin

# from core.events import listen_server, subscribe
# from protocol.datatypes import (
#     UUID,
#     Boolean,
#     Buffer,
#     Chat,
#     String,
#     VarInt,
# )


class DebugPluginState:
    pass


class DebugPlugin(ProxhyPlugin):
    @command("game")
    async def _command_game(self):
        """Display current game info."""
        self.client.chat(TextComponent("Game:").color("green"))
        for key in type(self.game).__annotations__:
            if value := getattr(self.game, key):
                self.client.chat(
                    TextComponent(f"{key.capitalize()}: ")
                    .color("aqua")
                    .append(TextComponent(str(value)).color("yellow"))
                )

    @command("rqgame")
    async def _command_rqgame(self):
        """Display requeue game info."""
        self.client.chat(TextComponent("Requeue Game:").color("green"))
        for key in type(self.rq_game).__annotations__:
            if value := getattr(self.rq_game, key):
                self.client.chat(
                    TextComponent(f"{key.capitalize()}: ")
                    .color("aqua")
                    .append(TextComponent(str(value)).color("yellow"))
                )

    @command("teams")
    async def _command_teams(self):
        print("\n")
        for team_name, team in self.gamestate.teams.items():
            print(f"{team_name}: {team}")
        print("\n")

    @command("iphone_ringtone")
    async def _command_iphone_ringtone(self):
        await self._iphone_ringtone()

    @command("android_ringtone")
    async def _command_android_ringtone(self):
        await self._android_ringtone()

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
