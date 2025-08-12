import json
from pathlib import Path

default_settings = {
    "bedwars": {
        "item": "minecraft:bed",
        "description": "Bedwars settings.",
        "tablist": {
            "item": "minecraft:sign",
            "display_name": "Tablist",
            "description": "Settings related to the BedWars player list.",
            "show_fkdr": {
                "display_name": "Show Tablist FKDR",
                "description": "In BedWars, shows users' FKDR next to their name in the tablist.",
                "item": "minecraft:iron_sword",
                "states": {
                    "OFF": "red",
                    "ON": "green",
                },
                "state": "OFF",
            },
            "is_mode_specific": {
                "display_name": "Mode-Specific Tablist FKDR",
                "description": "In BedWars, the tablist will show users' FKDR for the mode you're playing.\nex: Solo FKDR instead of overall.",
                "item": "minecraft:writable_book",
                "states": {
                    "OFF": "red",
                    "ON": "green",
                },
                "state": "OFF"
            },
        },
        "display_top_stats": {
            "display_name": "Preface top players",
            "description": "In BedWars, receive a chat message at the start of the game highlighting the best players.",
            "item": "minecraft:golden_sword",
            "states": {
                "OFF": "red",
                "FKDR": "green",
                "STAR": "green",
                "INDEX": "green",
            },
            "state": "INDEX",
        },
    }
}


class SettingProperty:
    """A setting property that can be accessed with dot notation and auto-saves."""

    def __init__(self, config_data, parent_settings, key_path):
        self._config_data = config_data
        self._parent_settings = parent_settings
        self._key_path = key_path

        # No need for reverse mapping - state names are now the keys directly

    @property
    def state(self):
        """Get the current state name."""
        current_state_key = self._config_data.get("state", "OFF")
        # In the new format, the state key is the state name itself
        return current_state_key

    @state.setter
    def state(self, value):
        """Set the state by name (OFF, ON, FKDR, STAR, INDEX)."""
        if (
            isinstance(value, str)
            and "states" in self._config_data
            and value in self._config_data["states"]
        ):
            # State name is valid
            state_key = value
        else:
            valid_states = list(self._config_data.get("states", {}).keys())
            raise ValueError(f"Invalid state '{value}'. Valid states: {valid_states}")

        self._config_data["state"] = state_key
        self._parent_settings._save()

    @property
    def states(self):
        """Get the mapping of state names to colors."""
        return self._config_data.get("states", {})

    @property
    def display_name(self):
        """Get the display name of the setting."""
        return self._config_data.get("display_name", "")

    @property
    def description(self):
        """Get the description of the setting."""
        return self._config_data.get("description", "")

    def toggle(self):
        """Toggle to the next available state in the sequence."""
        if "states" not in self._config_data:
            raise ValueError("Cannot toggle: no states defined for this setting")

        # Get all state names in order
        state_names = list(self._config_data["states"].keys())
        if not state_names:
            raise ValueError("Cannot toggle: no states available")

        # Find current state index
        current_state = self.state
        try:
            current_index = state_names.index(current_state)
        except ValueError:
            # Current state not found, start from first state
            current_index = -1

        # Move to next state (wrap around to first if at end)
        next_index = (current_index + 1) % len(state_names)
        next_state = state_names[next_index]
        prev_state = self.state

        # Set the new state
        self.state = next_state
        return prev_state, next_state

    def __str__(self):
        return f"{self.display_name}: {self.state}"

    def __repr__(self):
        return (
            f"SettingProperty(display_name='{self.display_name}', state='{self.state}')"
        )


class SettingGroup:
    """A group of settings that can be accessed with dot notation."""

    def __init__(self, config_data, parent_settings, key_path):
        self._config_data = config_data
        self._parent_settings = parent_settings
        self._key_path = key_path

        # Create attributes for each setting/group
        for key, value in config_data.items():
            if key == "description":
                continue

            if isinstance(value, dict):
                if "state" in value:
                    # This is a setting property
                    setattr(
                        self,
                        key,
                        SettingProperty(value, parent_settings, key_path + [key]),
                    )
                else:
                    # This is a setting group
                    setattr(
                        self,
                        key,
                        SettingGroup(value, parent_settings, key_path + [key]),
                    )

    @property
    def description(self):
        """Get the description of the setting group."""
        return self._config_data.get("description", "")

    def __str__(self):
        return f"SettingGroup: {self.description}"

    def __repr__(self):
        return f"SettingGroup(description='{self.description}')"


class Settings:
    """Main settings class with auto-save functionality."""

    def __init__(self, settings_file: str | Path = "proxhy_settings.json"):
        self._settings_file = Path(settings_file)
        self._config_data = self._load_settings()

        # Create attributes for each top-level setting group
        for key, value in self._config_data.items():
            if isinstance(value, dict):
                setattr(self, key, SettingGroup(value, self, [key]))

    def _load_settings(self):
        """Load settings from JSON file or create default settings."""
        try:
            if self._settings_file.exists():
                with open(self._settings_file, "r") as f:
                    loaded_settings = json.load(f)
                # Merge with default settings to ensure new settings are included
                return self._merge_settings(default_settings, loaded_settings)
            else:
                # Create file with default settings
                self._save_settings(default_settings)
                return default_settings.copy()
        except (json.JSONDecodeError, IOError):
            # print(f"Error loading settings file: {e}")
            # print("Using default settings...")
            return default_settings.copy()  # TODO: log this

    def _merge_settings(self, default, loaded):
        """Merge loaded settings with default settings."""
        result = default.copy()
        for key, value in loaded.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_settings(result[key], value)
            else:
                result[key] = value
        return result

    def _save_settings(self, settings_data):
        """Save settings data to JSON file."""
        try:
            with open(self._settings_file, "w") as f:
                json.dump(settings_data, f, indent=2)
        except IOError:
            # print(f"Error saving settings file: {e}")
            pass  # TODO: log this

    def _save(self):
        """Save current settings to file."""
        self._save_settings(self._config_data)

    def reset_to_defaults(self):
        """Reset all settings to default values."""
        self._config_data = default_settings.copy()
        self._save()

        # Recreate attributes
        for key, value in self._config_data.items():
            if isinstance(value, dict):
                setattr(self, key, SettingGroup(value, self, [key]))

    def get_setting_by_path(self, path) -> dict:
        """Get a setting by its path (e.g., 'bedwars.tablist.show_fkdr')."""
        keys = path.split(".")
        current: dict = self._config_data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                raise KeyError(f"Setting path '{path}' not found")

        return current
    
    def toggle_setting_by_path(self, path: str):
        """Toggle a setting by its path (e.g., 'bedwars.tablist.show_fkdr')."""
        # Get the setting data
        setting_data = self.get_setting_by_path(path)
        
        # Ensure it's a setting property (has 'state' key)
        if not isinstance(setting_data, dict) or "state" not in setting_data:
            raise ValueError(f"Path '{path}' does not point to a toggleable setting")
        
        # Create a temporary SettingProperty and toggle it
        keys = path.split(".")
        setting_property = SettingProperty(setting_data, self, keys)
        return setting_property.toggle()

    def __str__(self):
        return f"Settings(file='{self._settings_file}')"

    def __repr__(self):
        return f"Settings(settings_file='{self._settings_file}')"

