from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Union

# Default settings dictionary
default_settings: Dict[str, Any]

class SettingProperty[T = str]:
    """A setting property that can be accessed with dot notation and auto-saves."""

    def __init__(
        self,
        config_data: Dict[str, Any],
        parent_settings: Settings,
        key_path: List[str],
    ) -> None: ...
    @property
    def state(self) -> T: ...
    @state.setter
    def state(self, value: T) -> None: ...
    @property
    def display_name(self) -> str: ...
    @property
    def description(self) -> str: ...
    def toggle(self) -> T: ...
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...
    states: Dict[
        T,
        Literal[
            "black",
            "dark_blue",
            "dark_green",
            "dark_aqua",
            "dark_red",
            "dark_purple",
            "gold",
            "gray",
            "dark_gray",
            "blue",
            "green",
            "aqua",
            "red",
            "light_purple",
            "yellow",
            "white",
        ],
    ] = ...  # Mapping of state keys to colors

class SettingGroup:
    """A group of settings that can be accessed with dot notation."""

    def __init__(
        self,
        config_data: Dict[str, Any],
        parent_settings: Settings,
        key_path: List[str],
    ) -> None: ...
    @property
    def description(self) -> str: ...
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...

class Settings:
    """Main settings class with auto-save functionality."""

    def __init__(
        self, settings_file: Union[str, Path] = "proxhy_settings.json"
    ) -> None: ...
    def _load_settings(self) -> Dict[str, Any]: ...
    def _merge_settings(
        self, default: Dict[str, Any], loaded: Dict[str, Any]
    ) -> Dict[str, Any]: ...
    def _save_settings(self, settings_data: Dict[str, Any]) -> None: ...
    def _save(self) -> None: ...
    def reset_to_defaults(self) -> None: ...
    def get_setting_by_path(self, path: str) -> Any: ...
    def toggle_setting_by_path(self, path: str) -> tuple: ...
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...

    # GROUPS
    bedwars: Bedwars

    class Bedwars:
        """Settings related to the BedWars game mode."""

        description: str

        # SETTINGS
        display_top_stats: DisplayTopStats
        api_key_reminder: ApiKeyReminder

        # GROUPS
        tablist: Tablist

        class Tablist:
            """Settings related to the BedWars player list."""

            description: str

            # SETTINGS
            show_stats: Settings.Bedwars.Tablist.ShowFkdr
            is_mode_specific: Settings.Bedwars.Tablist.IsModeSpecific

            # SETTINGS CLASSES
            # show_stats
            class ShowFkdr(SettingProperty[Literal["OFF", "ON"]]): ...
            # is_mode_specific
            class IsModeSpecific(SettingProperty[Literal["OFF", "ON"]]): ...

        # display_top_stats
        class DisplayTopStats(
            SettingProperty[Literal["OFF", "FKDR", "STAR", "INDEX"]]
        ): ...

        # api_key_reminder
        class ApiKeyReminder(SettingProperty[Literal["ON", "OFF"]]): ...
