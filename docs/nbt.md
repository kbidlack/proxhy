# NBT (Named Binary Tag) Module

A comprehensive Python module for reading and writing Minecraft's NBT (Named Binary Tag) binary data format.

## Features

- **Complete NBT Support**: Implements all 13 NBT tag types as defined in the [NBT specification](https://wiki.vg/NBT)
- **Java & Bedrock Edition**: Supports both big-endian (Java Edition) and little-endian (Bedrock Edition) formats
- **Compression Support**: Handles uncompressed, gzip, and zlib compressed NBT files
- **File I/O**: Easy-to-use functions for loading and saving NBT files
- **Dictionary Conversion**: Convert between NBT data and Python dictionaries
- **Type Safety**: Strongly typed tag classes with proper validation

## Supported Tag Types

| Tag ID | Tag Name | Description |
|--------|----------|-------------|
| 0 | TAG_End | Signifies the end of a TAG_Compound |
| 1 | TAG_Byte | A single signed byte |
| 2 | TAG_Short | A signed 16-bit integer |
| 3 | TAG_Int | A signed 32-bit integer |
| 4 | TAG_Long | A signed 64-bit integer |
| 5 | TAG_Float | A 32-bit floating point number |
| 6 | TAG_Double | A 64-bit floating point number |
| 7 | TAG_Byte_Array | A length-prefixed array of signed bytes |
| 8 | TAG_String | A length-prefixed UTF-8 string |
| 9 | TAG_List | A list of nameless tags of the same type |
| 10 | TAG_Compound | A collection of named tags |
| 11 | TAG_Int_Array | A length-prefixed array of signed integers |
| 12 | TAG_Long_Array | A length-prefixed array of signed longs |

## Quick Start

### Basic Usage

```python
from proxhy.nbt import *

# Create a simple NBT structure
root = TagCompound("MyData")
root["name"] = TagString("name", "Player")
root["level"] = TagInt("level", 42)
root["health"] = TagFloat("health", 20.0)

# Save to file (gzip compressed)
dump(root, "player.nbt", compression='gzip')

# Load from file
loaded = load("player.nbt")
print(f"Player name: {loaded['name'].value}")
```

### Working with Complex Structures

```python
# Create a player with inventory
player = TagCompound("Player")
player["name"] = TagString("name", "Steve")
player["position"] = TagList("position", TagType.TAG_Double)

# Add position coordinates
player["position"].append(TagDouble(None, 100.5))
player["position"].append(TagDouble(None, 64.0))
player["position"].append(TagDouble(None, -200.25))

# Create inventory
inventory = TagList("Inventory", TagType.TAG_Compound)

# Add an item
item = TagCompound()
item["id"] = TagString("id", "minecraft:diamond_sword")
item["Count"] = TagByte("Count", 1)
item["Damage"] = TagShort("Damage", 0)
inventory.append(item)

player["Inventory"] = inventory
```

### Dictionary Conversion

```python
# Convert Python dict to NBT
data = {
    "player": {
        "name": "TestPlayer", 
        "level": 50,
        "health": 20.0,
        "inventory": [
            {"id": "minecraft:sword", "count": 1},
            {"id": "minecraft:bread", "count": 32}
        ]
    }
}

nbt_data = from_dict(data, "GameData")
dump(nbt_data, "game.nbt", compression='zlib')

# Convert NBT back to dict
loaded_nbt = load("game.nbt")
python_dict = to_dict(loaded_nbt)
```

### Bedrock Edition Support

```python
# Use little-endian format for Bedrock Edition
bedrock_data = TagCompound("BedrockWorld")
bedrock_data["version"] = TagInt("version", 1)
bedrock_data["name"] = TagString("name", "My Bedrock World")

# Save in Bedrock format
bedrock_bytes = dumps(bedrock_data, little_endian=True)

# Load Bedrock format
loaded_bedrock = loads(bedrock_bytes, little_endian=True)
```

## API Reference

### Main Functions

#### `load(file_path, little_endian=False)`
Load NBT data from a file.
- `file_path`: Path to the NBT file
- `little_endian`: Use little-endian byte order (Bedrock Edition)
- Returns: Root `TagCompound`

#### `loads(data, little_endian=False)`
Load NBT data from bytes.
- `data`: Raw NBT binary data
- `little_endian`: Use little-endian byte order (Bedrock Edition)
- Returns: Root `TagCompound`

#### `dump(tag, file_path, compression=None, little_endian=False)`
Save NBT data to a file.
- `tag`: Root `TagCompound` to save
- `file_path`: Path to save the NBT file
- `compression`: Compression type (`'gzip'`, `'zlib'`, or `None`)
- `little_endian`: Use little-endian byte order (Bedrock Edition)

#### `dumps(tag, compression=None, little_endian=False)`
Serialize NBT data to bytes.
- `tag`: Root `TagCompound` to serialize  
- `compression`: Compression type (`'gzip'`, `'zlib'`, or `None`)
- `little_endian`: Use little-endian byte order (Bedrock Edition)
- Returns: Serialized NBT binary data

#### `from_dict(data, name="")`
Create a `TagCompound` from a Python dictionary.
- `data`: Dictionary to convert
- `name`: Name for the root compound
- Returns: `TagCompound` representation

#### `to_dict(tag)`
Convert a `TagCompound` to a Python dictionary.
- `tag`: `TagCompound` to convert
- Returns: Dictionary representation

### Tag Classes

All tag classes inherit from `NBTTag` and have the following structure:

```python
class TagByte(NBTTag):
    def __init__(self, name=None, value=0):
        super().__init__(name, value)
```

#### TagCompound Methods

```python
compound = TagCompound("MyCompound")

# Dictionary-like access
compound["key"] = TagString("key", "value")
value = compound["key"]
if "key" in compound:
    print("Key exists")

# Iteration
for key, tag in compound.items():
    print(f"{key}: {tag.value}")
```

#### TagList Methods

```python
tag_list = TagList("MyList", TagType.TAG_String)

# Add items
tag_list.append(TagString(None, "item1"))
tag_list.append(TagString(None, "item2"))

# Access items
for item in tag_list.value:
    print(item.value)
```

## Error Handling

The module defines custom exceptions:

- `NBTError`: Base exception for NBT-related errors
- `NBTParseError`: Raised when NBT data cannot be parsed
- `NBTWriteError`: Raised when NBT data cannot be written

```python
try:
    data = load("invalid.nbt")
except NBTParseError as e:
    print(f"Failed to parse NBT: {e}")
except NBTError as e:
    print(f"NBT error: {e}")
```

## Performance Notes

- The module automatically detects compression when loading data
- For large datasets, use appropriate compression (`zlib` is typically smaller)
- Little-endian mode is slightly slower due to byte order conversion
- Dictionary conversion creates deep copies of the data

## Compatibility

- Python 3.7+
- No external dependencies (uses only standard library)
- Compatible with NBT files from all Minecraft versions
- Supports both Java Edition and Bedrock Edition formats

## Examples

See `test_nbt.py` for comprehensive examples including:
- Basic tag manipulation
- Complex nested structures
- File I/O operations
- Compression testing
- Dictionary conversion
- Bedrock Edition format
- Error handling

## License

This module follows the same license as the parent project.
