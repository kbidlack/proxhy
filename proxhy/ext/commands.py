import asyncio
from collections import namedtuple
from typing import TYPE_CHECKING, Callable

import hypixel
from hypixel import ApiError, InvalidApiKey, KeyRequired

from ..command import CommandException, command
from ..datatypes import String, TextComponent
from ..proxhy import Proxhy
from ..settings import SettingGroup, SettingProperty


class Commands(Proxhy):
    if TYPE_CHECKING:
        from .statcheck import StatCheck

        log_bedwars_stats: Callable = StatCheck.log_bedwars_stats
        _update_stats: Callable = StatCheck._update_stats

    @command()
    async def key(self, key):
        try:
            new_client = hypixel.Client(key)
            await new_client.player("gamerboy80")  # test key
            # await new_client.validate_keys()
        except (InvalidApiKey, KeyRequired, ApiError):
            raise CommandException("Invalid API Key!")
        else:
            if new_client:
                await new_client.close()

        if self.hypixel_client:
            await self.hypixel_client.close()

        self.hypixel_api_key = key
        self.hypixel_client = hypixel.Client(key)
        api_key_msg = TextComponent("Updated API Key!").color("green")
        self.client.chat(api_key_msg)

        await self._update_stats()

    @command("setting")
    async def edit_settings(self, setting_name: str, value: str = ""):
        value = value.upper()
        setting_attrs = setting_name.split(".")

        if len(setting_attrs) == 1:
            setting_name = setting_attrs[0]
            if not hasattr(self.settings, setting_name):
                raise CommandException(f"Setting '{setting_name}' does not exist!")
            setting_attrs = [setting_name]
            parent_obj = self.settings
        else:
            prev_sa = "settings"
            parent_obj = self.settings
            for sa in setting_attrs[:-1]:
                if not hasattr(parent_obj, sa):
                    if isinstance(parent_obj, SettingGroup):
                        raise CommandException(
                            f"Setting group '{prev_sa}' does not have a setting named '{sa}'!"
                        )
                    elif isinstance(parent_obj, SettingProperty):
                        raise CommandException(f"'{prev_sa}' is a setting!")
                    else:
                        raise CommandException("This should not happen!")
                prev_sa = sa
                parent_obj = getattr(parent_obj, sa)

        if not hasattr(parent_obj, setting_attrs[-1]):
            if isinstance(parent_obj, SettingGroup):
                raise CommandException(
                    f"Setting group '{'.'.join(setting_attrs[:-1])}' does not have a setting named '{setting_attrs[-1]}'!"
                )
            elif isinstance(parent_obj, SettingProperty):
                raise CommandException(
                    f"'{'.'.join(setting_attrs[:-1])}' is a setting!"
                )
            else:
                raise CommandException("This should not happen!")

        setting_obj = getattr(parent_obj, setting_attrs[-1])

        if isinstance(setting_obj, SettingGroup):
            raise CommandException(f"'{setting_name}' is a setting group!")
        elif isinstance(setting_obj, SettingProperty):
            setting_obj: SettingProperty
        else:
            raise CommandException("This should not happen!")

        if value and (value not in setting_obj.states):
            raise CommandException(
                f"Invalid value '{value}' for setting '{setting_name}'; "
                f"valid values are: {', '.join(setting_obj.states.keys())}"
            )

        old_state = setting_obj.state
        old_state_color = setting_obj.states[old_state]
        new_state = value or setting_obj.toggle()
        setting_obj.state = new_state
        new_state_color = setting_obj.states[new_state]

        settings_msg = (
            TextComponent("Changed ")
            .append(TextComponent(setting_obj.display_name).color("yellow"))
            .append(TextComponent(" from "))
            .append(TextComponent(old_state.upper()).bold().color(old_state_color))
            .append(TextComponent(" to "))
            .append(TextComponent(new_state.upper()).bold().color(new_state_color))
            .append(TextComponent("!"))
        )
        self.client.chat(settings_msg)

        Callback = namedtuple("Callback", ["setting", "old_state", "new_state", "func"])
        callbacks = [
            Callback(
                setting="bedwars.tablist.show_fkdr",
                old_state="OFF",
                new_state="ON",
                func=self._update_stats,
            )
        ]
        # TODO: implement reset_tablist() for ON -> OFF

        for callback in callbacks:
            if (
                setting_name == callback.setting
                and old_state == callback.old_state
                and new_state == callback.new_state
            ):
                if asyncio.iscoroutinefunction(callback.func):
                    await callback.func()
                else:
                    callback.func()

    @command("rq")
    async def requeue(self):
        if not self.rq_game.mode:
            raise CommandException("No game to requeue!")
        else:
            self.server.send_packet(0x01, String(f"/play {self.rq_game.mode}"))

    @command()  # Mmm, garlic bread.
    async def garlicbread(self):  # Mmm, garlic bread.
        return TextComponent("Mmm, garlic bread.").color("yellow")  # Mmm, garlic bread.
