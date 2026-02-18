from typing import Literal

from plugins.settings import Setting, SettingGroup, SettingsStorage, create_setting
from protocol.datatypes import Item


class BroadcastSettings(SettingGroup):
    def __init__(self, storage: SettingsStorage):
        super().__init__(
            key="broadcast",
            display_name="Broadcast",
            description="Broadcast peer settings.",
            item="minecraft:command_block",
        )
        self._storage = storage

        self.fly_speed: Setting[Literal["0.5x", "1x", "2x"]] = create_setting(
            key="broadcast.fly_speed",
            display_name="Fly Speed",
            description="The speed at which you fly at.",
            item="minecraft:feather",
            states={
                "0.5x": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "1x": (
                    Item.from_display_name("Yellow Stained Glass Pane"),
                    "yellow",
                ),
                "2x": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="1x",
            storage=self._storage,
        )

        self.titles: Setting[Literal["OFF", "ON"]] = create_setting(
            key="broadcast.titles",
            display_name="Titles",
            description="Show title messages on screen.",
            item="minecraft:sign",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="ON",
            storage=self._storage,
        )

        self.hide_system_messages: Setting[Literal["OFF", "ON"]] = create_setting(
            key="broadcast.hide_system_messages",
            display_name="Hide System Messages",
            description="Hide messages that frequently come from automated client commands, "
            "like /tip, /who, and /locraw. May also suppress some user-originated output "
            "from these commands!",
            item="minecraft:book",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="ON",
            storage=self._storage,
        )
