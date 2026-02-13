"""
Type-safe Settings API with automatic state management and validation.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from protocol.datatypes import Color_T, Item
    from protocol.datatypes import ItemName as Item_T

type SettingState = tuple[Item, Color_T]


class Setting[S: str]:
    """Represents a single setting with type-safe state management."""

    def __init__(
        self,
        key: str,
        display_name: str,
        description: str,
        item: Item_T,
        states: Dict[S, SettingState],
        default_state: S,
        storage: SettingsStorage,
    ):
        self._key = key
        self._display_name = display_name
        self._description = description
        self._item: Item_T = item
        self._states = states
        self._default_state = default_state
        self._storage = storage

    @property
    def name(self) -> str:
        return self._key.split(".")[-1]

    @property
    def description(self) -> str:
        """Returns the setting description."""
        return self._description

    @property
    def display_name(self) -> str:
        """Returns the setting display name."""
        return self._display_name

    @property
    def item(self) -> Item_T:
        """Returns the setting item identifier."""
        return self._item

    @property
    def states(self) -> Dict[S, SettingState]:
        """Returns available states and their items and colors."""
        return self._states.copy()

    def get(self) -> S:
        """Get the current value of this setting."""
        return self._storage.get_setting(self._key, self._default_state)

    def set(self, value: S) -> None:
        """Set the value of this setting."""
        if value not in self._states:
            raise ValueError(
                f"Invalid state '{value}'. Valid states: {list(self._states.keys())}"
            )
        self._storage.set_setting(self._key, value)

    def reset(self) -> None:
        """Reset this setting to its default value."""
        self.set(self._default_state)

    def toggle(self) -> tuple[S, S]:
        """Toggle to the next state in the sequence."""
        current_state = self.get()
        state_keys = list(self._states.keys())
        current_index = state_keys.index(current_state)
        next_index = (current_index + 1) % len(state_keys)
        self.set(state_keys[next_index])
        return current_state, state_keys[next_index]


class SettingGroup:
    """Represents a group of settings with metadata."""

    def __init__(self, key: str, display_name: str, description: str, item: Item_T):
        self._key = key
        self._display_name = display_name
        self._description = description
        self._item: Item_T = item

    @property
    def name(self) -> str:
        return self._key.split(".")[-1]

    @property
    def description(self) -> str:
        """Returns the group description."""
        return self._description

    @property
    def display_name(self) -> str:
        """Returns the group display name."""
        return self._display_name

    @property
    def item(self) -> Item_T:
        """Returns the group item identifier."""
        return self._item

    def reset_all(self) -> None:
        """Reset all settings in this group and any nested groups."""
        # Get all attributes of this instance
        for attr_name in dir(self):
            # Skip private attributes and methods
            if attr_name.startswith("_"):
                continue

            attr_value = getattr(self, attr_name)

            # Reset individual settings
            if isinstance(attr_value, Setting):
                attr_value.reset()

            # Recursively reset nested groups
            elif isinstance(attr_value, SettingGroup):
                attr_value.reset_all()

    def toggle_setting_by_path(self, path: str) -> tuple[Any, Any]:
        current = self
        for attr in path.split("."):
            if hasattr(current, attr):
                current = getattr(current, attr)
            else:
                raise AttributeError(f"Setting path '{path}' not found")

        if isinstance(current, Setting):
            return current.toggle()
        else:
            raise ValueError(f"Path '{path}' does not point to a Setting")

    def get_setting_by_path(self, path: str) -> Setting | SettingGroup:
        """Get a setting or setting group by its dot-separated path."""
        if not path:
            return self

        current = self

        for attr in path.split("."):
            current = getattr(current, attr)

        return current

    def get_all_settings(self) -> list[Setting]:
        """Get all Setting instances in this group"""
        settings = []

        for attr_name in dir(self):
            # Skip private attributes and methods
            if attr_name.startswith("_"):
                continue

            attr_value = getattr(self, attr_name)

            # Add individual settings
            if isinstance(attr_value, Setting):
                settings.append(attr_value)

        return settings

    def get_all_groups(self) -> list[SettingGroup]:
        """Get all SettingGroup instances in this group"""
        groups = []

        for attr_name in dir(self):
            # Skip private attributes and methods
            if attr_name.startswith("_"):
                continue

            attr_value = getattr(self, attr_name)

            # Add nested groups
            if isinstance(attr_value, SettingGroup):
                groups.append(attr_value)

        return groups


class SettingsStorage:
    """Handles persistent storage of setting values."""

    def __init__(self, storage_file: Path = Path("settings.json")):
        self.storage_file = Path(storage_file)
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load settings from disk."""
        if self.storage_file.exists():
            try:
                with open(self.storage_file, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._data = {}

    def _save(self) -> None:
        """Save settings to disk."""
        try:
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_file, "w") as f:
                json.dump(self._data, f, indent=2)
        except IOError:
            pass  # Silently fail if we can't save

    def get_setting[T](self, key: str, default: T) -> T:
        """Get a setting value."""
        return self._data.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        """Set a setting value."""
        self._data[key] = value
        self._save()


def create_setting[T: str](
    key: str,
    display_name: str,
    description: str,
    item: Item_T,
    states: Dict[T, SettingState],
    default_state: T,
    storage: SettingsStorage,
) -> Setting[T]:
    """Helper function to create a setting with proper typing."""
    return Setting(key, display_name, description, item, states, default_state, storage)
