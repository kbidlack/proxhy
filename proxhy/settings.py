from pathlib import Path
from typing import Literal

from petty.protocol.datatypes import Item
from platformdirs import user_config_dir

from plugins.settings._settings import (  # import directly to avoid circular imports
    Setting,
    SettingGroup,
    SettingsStorage,
    create_setting,
)

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
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="OFF",
            storage=storage,
        )

        self.is_mode_specific: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.tablist.is_mode_specific",
            display_name="Mode-Specific Tablist Stats",
            description="In Bedwars, the tablist will show users' stats for the mode you're playing.\nex: Solo stats instead of overall.",
            item="minecraft:writable_book",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="OFF",
            storage=storage,
        )

        self.show_rankname: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.tablist.show_rankname",
            display_name="Show Rankname in Tablist",
            description="In Bedwars, the tablist will show users' colorized ranks and usernames instead of team color.",
            item="minecraft:name_tag",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="OFF",
            storage=storage,
        )

        self.show_respawn_timer: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.tablist.show_respawn_timer",
            display_name="Show Respawn Timer",
            description="In Bedwars, shows a timer next to players' names showing how long until they respawn.",
            item="minecraft:clock",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="ON",
            storage=storage,
        )

        self.show_eliminated_players: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.tablist.show_eliminated_players",
            display_name="Show Eliminated Players",
            description="In Bedwars, shows eliminated players in the tablist, grayed out.",
            item="minecraft:bone",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="ON",
            storage=storage,
        )


class VisualGroup(SettingGroup):
    def __init__(self, storage: SettingsStorage):
        super().__init__(
            key="visual",
            display_name="Visual",
            description="Toggle Proxhy's visual feautures.",
            item="minecraft:ender_eye",
        )

        self.height_limit_warnings: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.visual.height_limit_warnings",
            display_name="Height Limit Warnings",
            description="When you're near the top or bottom of the map, display particles and a warning in the actionbar.",
            item="minecraft:quartz_stairs",
            states={
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
            },
            default_state="ON",
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

        self.visual = VisualGroup(storage)

        self.display_top_stats: Setting[Literal["OFF", "FKDR", "STAR", "INDEX"]] = (
            create_setting(
                key="bedwars.display_top_stats",
                display_name="Preface Top Players",
                description="In Bedwars, receive a chat message at the start of the game highlighting the best players.",
                item="minecraft:golden_sword",
                states={
                    "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                    "FKDR": (
                        Item.from_display_name("Lime Stained Glass Pane"),
                        "green",
                    ),
                    "STAR": (
                        Item.from_display_name("Lime Stained Glass Pane"),
                        "green",
                    ),
                    "INDEX": (
                        Item.from_display_name("Lime Stained Glass Pane"),
                        "green",
                    ),
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
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "FIRST RUSH": (
                    Item.from_display_name("Yellow Stained Glass Pane"),
                    "yellow",
                ),
                "BOTH ADJACENT": (
                    Item.from_display_name("Lime Stained Glass Pane"),
                    "green",
                ),
            },
            default_state="OFF",
            storage=storage,
        )

        self.api_key_reminder: Setting[Literal["OFF", "ON"]] = create_setting(
            key="bedwars.api_key_reminder",
            display_name="Invalid API Key Reminders",
            description="In the Bedwars pregame, send a reminder with a link to developer.hypixel.net if your API key is invalid.",
            item="minecraft:tripwire_hook",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="OFF",
            storage=storage,
        )


class CompassGroup(SettingGroup):
    def __init__(self, storage: SettingsStorage):
        super().__init__(
            key="compass",
            display_name="Compass",
            description="Compass client settings.",
            item="minecraft:compass",
        )

        self.discoverable: Setting[Literal["ON", "OFF"]] = create_setting(
            key="compass.discoverable",
            display_name="Discoverable",
            description="Allow other players to request your node ID from the compass server",
            item="minecraft:ender_eye",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="ON",
            storage=storage,
        )

        self.whitelist: Setting[Literal["ON", "OFF"]] = create_setting(
            key="compass.whitelist",
            display_name="Whitelist",
            description="Restrict who can request your node ID from the compass server",
            item="minecraft:filled_map",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="OFF",
            storage=storage,
        )

        self.verify_node_id: Setting[Literal["ON", "OFF"]] = create_setting(
            key="compass.verify_node_id",
            display_name="Verify Node ID",
            description="Verify the Iroh node ID of incoming requests via the compass broker",
            item="minecraft:gold_nugget",
            states={
                "OFF": (Item.from_display_name("Red Stained Glass Pane"), "red"),
                "ON": (Item.from_display_name("Lime Stained Glass Pane"), "green"),
            },
            default_state="ON",
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

        from broadcasting.settings import BroadcastSettings  # avoid circular import

        self.bedwars = BedwarsGroup(self._storage)
        self.compass = CompassGroup(self._storage)
        self.broadcast = BroadcastSettings(self._storage)
