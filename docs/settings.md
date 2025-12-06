# proxhy/settings.py

```python
from proxhy.settings import ProxhySettings

# Initialize the settings system
settings = ProxhySettings()

# Access setting groups (fully type-checked)
settings.bedwars                    # BedwarsGroup
settings.bedwars.tablist           # TablistGroup

# Access individual settings (fully type-checked)
settings.bedwars.display_top_stats  # Setting[DisplayTopStatsState]

# Get and set values (type-safe)
current_value = settings.bedwars.display_top_stats.get()  # Returns current state
settings.bedwars.display_top_stats.set("FKDR")           # Type-safe - only valid states accepted

# Access metadata
settings.description                                     # "Main settings for Proxhy application."
settings.bedwars.description                             # "Bedwars settings."
settings.bedwars.display_top_stats.description          # Full setting description
settings.bedwars.display_top_stats.states               # Available states and colors

# Automatic reset (inherited from SettingGroup)
settings.reset_all()                                     # Resets ALL settings automatically
```

## Type Safety in Action

The system provides type checking for all operations:

```python
# ✅ These work - valid states
settings.bedwars.display_top_stats.set("OFF")
settings.bedwars.display_top_stats.set("FKDR") 
settings.bedwars.display_top_stats.set("STAR")
settings.bedwars.display_top_stats.set("INDEX")

# ❌ This fails type checking - invalid state
settings.bedwars.display_top_stats.set("INVALID")  # Type error!

# ❌ This fails type checking - invalid setting
settings.bedwars.invalid_setting                   # Type error!
```

## Automatic Reset

The system automatically discovers and resets all settings without manual maintenance:

```python
settings = ProxhySettings()

# Set some values
settings.bedwars.display_top_stats.set("FKDR")
settings.bedwars.tablist.show_stats.set("ON")

# Reset everything automatically - no need to manually list each setting!
settings.reset_all()  # ✅ Automatically finds and resets ALL settings

# You can also reset individual groups
settings.bedwars.reset_all()          # Resets all bedwars settings
settings.bedwars.tablist.reset_all()  # Resets just tablist settings
```


## Adding New Settings

To add new settings, simply extend the appropriate group class:

### 1. Define the state type
```python
NewSettingState = Literal["OPTION1", "OPTION2", "OPTION3"]
```

You can also skip this step and insert the state type directly into the code below.

### 2. Add to the group class
```python
class BedwarsGroup(SettingGroup):
    def __init__(self, storage: SettingsStorage):
        # ... existing code ...
        
        self.new_setting: Setting[NewSettingState] = create_setting(
            key="bedwars.new_setting",
            display_name="My New Setting",
            description="Description of what this setting does.",
            item="minecraft:item_name",
            states={"OPTION1": "red", "OPTION2": "yellow", "OPTION3": "green"},
            default_state="OPTION1",
            storage=storage
        )
```

## Adding New Setting Groups

To add a completely new group:

### 1. Create the group class
```python
class NewGroup(SettingGroup):
    def __init__(self, storage: SettingsStorage):
        super().__init__(
            display_name="New Group",
            description="Description of this group.",
            item="minecraft:group_item"
        )
        
        self.some_setting: Setting[SomeState] = create_setting(
            # ... setting definition ...
        )
```

### 2. Add to parent group (for example, ProxhySettings)
```python
class ProxhySettings:
    def __init__(self, storage_file: str = "settings.json"):
        self._storage = SettingsStorage(storage_file)
        
        self.bedwars = BedwarsGroup(self._storage)
        self.new_group = NewGroup(self._storage)  # Add here
        
        # reset_all() automatically discovers new_group - no changes needed!
```

## File Structure

- **`core/settings.py`** - Core base classes (Setting, SettingGroup, SettingsStorage)
- **`proxhy/settings.py`** - Proxhy's setting definitions

## Architecture

The system is built on three core classes:

- **Setting[T]**: Represents an individual setting with type-safe state management
- **SettingGroup**: Represents a group of related settings with metadata and automatic reset functionality
- **SettingsStorage**: Handles automatic persistence to/from JSON

Each setting is parameterized with a `Literal` type that defines exactly which states are valid, providing complete type safety. The main `ProxhySettings` class inherits from `SettingGroup`, automatically gaining the `reset_all()` functionality.
