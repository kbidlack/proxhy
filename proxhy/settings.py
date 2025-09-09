from __future__ import annotations

from pathlib import Path
from typing import Literal

from platformdirs import user_config_dir

from core.settings import Setting, SettingGroup, SettingsStorage, create_setting

config_dir = Path(user_config_dir("proxhy", ensure_exists=True))
config_dir.mkdir(parents=True, exist_ok=True)
settings_file = config_dir / "settings.json"


class TablistGroup(SettingGroup):
    def __init__(self, storage: SettingsStorage):
        super().__init__(
            key="bedwars.tablist",
            display_name="Tablist",
            description="Settings related to the Bedwars player list.",
            item="minecraft:sign",
        )

        # Define all tablist settings
        self.show_stats: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.tablist.show_stats",
            display_name="Show Tablist Stats",
            description="In Bedwars, shows users' stats next to their name in the tablist.",
            item="minecraft:iron_sword",
            states={"OFF": "red", "ON": "green"},
            default_state="OFF",
            storage=storage,
        )

        self.is_mode_specific: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.tablist.is_mode_specific",
            display_name="Mode-Specific Tablist Stats",
            description="[NOT IMPLEMENTED] In Bedwars, the tablist will show users' stats for the mode you're playing.\nex: Solo stats instead of overall.",
            item="minecraft:writable_book",
            states={"OFF": "red", "ON": "green"},
            default_state="OFF",
            storage=storage,
        )

        self.show_rankname: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.tablist.show_rankname",
            display_name="Show Rankname in Tablist",
            description="In Bedwars, the tablist will show users' colorized ranks and usernames instead of team color.",
            item="minecraft:name_tag",
            states={"OFF": "red", "ON": "green"},
            default_state="OFF",
            storage=storage,
        )


class BedwarsGroup(SettingGroup):
    def __init__(self, storage: SettingsStorage):
        super().__init__(
            key="bedwars",
            display_name="Bedwars",
            description="Bedwars settings.",
            item="minecraft:bed",
        )

        self.tablist = TablistGroup(storage)

        self.display_top_stats: Setting[Literal["OFF", "FKDR", "STAR", "INDEX"]] = (
            create_setting(
                key="bedwars.display_top_stats",
                display_name="Preface Top Players",
                description="In Bedwars, receive a chat message at the start of the game highlighting the best players.",
                item="minecraft:golden_sword",
                states={
                    "OFF": "red",
                    "FKDR": "green",
                    "STAR": "green",
                    "INDEX": "green",
                },
                default_state="OFF",
                storage=storage,
            )
        )

        self.announce_first_rush: Setting[
            Literal["OFF", "FIRST RUSH", "BOTH ADJACENT"]
        ] = create_setting(
            key="bedwars.announce_first_rush",
            display_name="Highlight First Rush Stats",
            description="At the start of a Bedwars game, display a title card with the name and stats of your first rush.",
            item="minecraft:wool",
            states={"OFF": "red", "FIRST RUSH": "yellow", "BOTH ADJACENT": "green"},
            default_state="OFF",
            storage=storage,
        )

        self.api_key_reminder: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.api_key_reminder",
            display_name="Invalid API Key Reminders",
            description="In the Bedwars pregame, send a reminder with a link to developer.hypixel.net if your API key is invalid.",
            item="minecraft:tripwire_hook",
            states={"OFF": "red", "ON": "green"},
            default_state="OFF",
            storage=storage,
        )


class ProxhySettings(SettingGroup):
    """Main settings class with type-safe access to all settings."""

    def __init__(self):
        super().__init__(
            key="proxhy",
            display_name="ProxhySettings",
            description="Main settings for Proxhy application.",
            item="minecraft:command_block",
        )
        self._storage = SettingsStorage(Path(settings_file))

        self.bedwars = BedwarsGroup(self._storage)
