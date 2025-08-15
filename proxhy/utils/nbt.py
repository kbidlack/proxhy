"""
NBT (Named Binary Tag) module for reading and writing Minecraft NBT binary data.

This module implements the NBT specification from https://wiki.vg/NBT
Supports both Java Edition (big-endian) and Bedrock Edition (little-endian) formats.
"""

import gzip
import io
import struct
import zlib
from enum import IntEnum
from typing import Any, Dict, List, Optional


class TagType(IntEnum):
    """NBT Tag type constants."""

    TAG_End = 0
    TAG_Byte = 1
    TAG_Short = 2
    TAG_Int = 3
    TAG_Long = 4
    TAG_Float = 5
    TAG_Double = 6
    TAG_Byte_Array = 7
    TAG_String = 8
    TAG_List = 9
    TAG_Compound = 10
    TAG_Int_Array = 11
    TAG_Long_Array = 12


class NBTError(Exception):
    """Base exception for NBT-related errors."""

    pass


class NBTParseError(NBTError):
    """Exception raised when NBT data cannot be parsed."""

    pass


class NBTWriteError(NBTError):
    """Exception raised when NBT data cannot be written."""

    pass


class NBTTag:
    """Base class for all NBT tags."""

    def __init__(self, name: Optional[str] = None, value: Any = None):
        self.name = name
        self.value = value

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name!r}: {self.value!r})"

    def __eq__(self, other):
        if not isinstance(other, NBTTag):
            return False
        return self.name == other.name and self.value == other.value


class TagEnd(NBTTag):
    """TAG_End - Signifies the end of a TAG_Compound."""

    def __init__(self):
        super().__init__(None, None)


class TagByte(NBTTag):
    """TAG_Byte - A single signed byte."""

    def __init__(self, name: Optional[str] = None, value: int = 0):
        super().__init__(name, value)


class TagShort(NBTTag):
    """TAG_Short - A single signed, big endian 16 bit integer."""

    def __init__(self, name: Optional[str] = None, value: int = 0):
        super().__init__(name, value)


class TagInt(NBTTag):
    """TAG_Int - A single signed, big endian 32 bit integer."""

    def __init__(self, name: Optional[str] = None, value: int = 0):
        super().__init__(name, value)


class TagLong(NBTTag):
    """TAG_Long - A single signed, big endian 64 bit integer."""

    def __init__(self, name: Optional[str] = None, value: int = 0):
        super().__init__(name, value)


class TagFloat(NBTTag):
    """TAG_Float - A single, big endian IEEE-754 single-precision floating point number."""

    def __init__(self, name: Optional[str] = None, value: float = 0.0):
        super().__init__(name, value)


class TagDouble(NBTTag):
    """TAG_Double - A single, big endian IEEE-754 double-precision floating point number."""

    def __init__(self, name: Optional[str] = None, value: float = 0.0):
        super().__init__(name, value)


class TagByteArray(NBTTag):
    """TAG_Byte_Array - A length-prefixed array of signed bytes."""

    def __init__(self, name: Optional[str] = None, value: Optional[List[int]] = None):
        super().__init__(name, value or [])


class TagString(NBTTag):
    """TAG_String - A length-prefixed modified UTF-8 string."""

    def __init__(self, name: Optional[str] = None, value: str = ""):
        super().__init__(name, value)


class TagList(NBTTag):
    """TAG_List - A list of nameless tags, all of the same type."""

    def __init__(
        self,
        name: Optional[str] = None,
        tag_type: TagType = TagType.TAG_End,
        value: Optional[List[NBTTag]] = None,
    ):
        super().__init__(name, value or [])
        self.tag_type = tag_type

    def append(self, tag: NBTTag):
        """Add a tag to the list."""
        if not self.value:
            # Map tag class names to TagType enum values
            tag_type_map = {
                "TagEnd": TagType.TAG_End,
                "TagByte": TagType.TAG_Byte,
                "TagShort": TagType.TAG_Short,
                "TagInt": TagType.TAG_Int,
                "TagLong": TagType.TAG_Long,
                "TagFloat": TagType.TAG_Float,
                "TagDouble": TagType.TAG_Double,
                "TagByteArray": TagType.TAG_Byte_Array,
                "TagString": TagType.TAG_String,
                "TagList": TagType.TAG_List,
                "TagCompound": TagType.TAG_Compound,
                "TagIntArray": TagType.TAG_Int_Array,
                "TagLongArray": TagType.TAG_Long_Array,
            }
            class_name = type(tag).__name__
            self.tag_type = tag_type_map.get(class_name, TagType.TAG_End)
        self.value.append(tag)

    def __repr__(self):
        return (
            f"TagList({self.name!r}, {self.tag_type.name}, {len(self.value)} entries)"
        )


class TagCompound(NBTTag):
    """TAG_Compound - A collection of named tags."""

    def __init__(
        self, name: Optional[str] = None, value: Optional[Dict[str, NBTTag]] = None
    ):
        super().__init__(name, value or {})

    def __getitem__(self, key: str) -> NBTTag:
        return self.value[key]

    def __setitem__(self, key: str, value: NBTTag):
        self.value[key] = value
        value.name = key

    def get(self, key: str, default: Any = None) -> Optional[NBTTag]:
        """Get a tag by name."""
        return self.value.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.value

    def __len__(self) -> int:
        return len(self.value)

    def keys(self):
        return self.value.keys()

    def values(self):
        return self.value.values()

    def items(self):
        return self.value.items()

    def __repr__(self):
        return f"TagCompound({self.name!r}, {len(self.value)} entries)"


class TagIntArray(NBTTag):
    """TAG_Int_Array - A length-prefixed array of signed integers."""

    def __init__(self, name: Optional[str] = None, value: Optional[List[int]] = None):
        super().__init__(name, value or [])


class TagLongArray(NBTTag):
    """TAG_Long_Array - A length-prefixed array of signed longs."""

    def __init__(self, name: Optional[str] = None, value: Optional[List[int]] = None):
        super().__init__(name, value or [])


class NBTReader:
    """NBT binary data reader."""

    def __init__(self, data: bytes, little_endian: bool = False):
        """
        Initialize NBT reader.

        Args:
            data: Raw NBT binary data
            little_endian: Whether to use little-endian byte order (Bedrock Edition)
        """
        self.data = io.BytesIO(data)
        self.little_endian = little_endian
        self.endian = "<" if little_endian else ">"

    def read_byte(self) -> int:
        """Read a single signed byte."""
        return struct.unpack("b", self.data.read(1))[0]

    def read_short(self) -> int:
        """Read a signed 16-bit integer."""
        return struct.unpack(f"{self.endian}h", self.data.read(2))[0]

    def read_int(self) -> int:
        """Read a signed 32-bit integer."""
        return struct.unpack(f"{self.endian}i", self.data.read(4))[0]

    def read_long(self) -> int:
        """Read a signed 64-bit integer."""
        return struct.unpack(f"{self.endian}q", self.data.read(8))[0]

    def read_float(self) -> float:
        """Read a 32-bit floating point number."""
        return struct.unpack(f"{self.endian}f", self.data.read(4))[0]

    def read_double(self) -> float:
        """Read a 64-bit floating point number."""
        return struct.unpack(f"{self.endian}d", self.data.read(8))[0]

    def read_string(self) -> str:
        """Read a length-prefixed UTF-8 string."""
        length = self.read_short()
        if length < 0:
            raise NBTParseError(f"Invalid string length: {length}")
        if length == 0:
            return ""
        data = self.data.read(length)
        if len(data) != length:
            raise NBTParseError(f"Expected {length} bytes for string, got {len(data)}")
        return data.decode("utf-8")

    def read_byte_array(self) -> List[int]:
        """Read a length-prefixed array of signed bytes."""
        length = self.read_int()
        if length < 0:
            raise NBTParseError(f"Invalid byte array length: {length}")
        if length == 0:
            return []
        data = self.data.read(length)
        if len(data) != length:
            raise NBTParseError(
                f"Expected {length} bytes for byte array, got {len(data)}"
            )
        return list(struct.unpack(f"{length}b", data))

    def read_int_array(self) -> List[int]:
        """Read a length-prefixed array of signed integers."""
        length = self.read_int()
        if length < 0:
            raise NBTParseError(f"Invalid int array length: {length}")
        if length == 0:
            return []
        data = self.data.read(length * 4)
        if len(data) != length * 4:
            raise NBTParseError(
                f"Expected {length * 4} bytes for int array, got {len(data)}"
            )
        return list(struct.unpack(f"{self.endian}{length}i", data))

    def read_long_array(self) -> List[int]:
        """Read a length-prefixed array of signed longs."""
        length = self.read_int()
        if length < 0:
            raise NBTParseError(f"Invalid long array length: {length}")
        if length == 0:
            return []
        data = self.data.read(length * 8)
        if len(data) != length * 8:
            raise NBTParseError(
                f"Expected {length * 8} bytes for long array, got {len(data)}"
            )
        return list(struct.unpack(f"{self.endian}{length}q", data))

    def read_tag(self, tag_type: TagType, name: Optional[str] = None) -> NBTTag:
        """Read a tag of the specified type."""
        if tag_type == TagType.TAG_End:
            return TagEnd()
        elif tag_type == TagType.TAG_Byte:
            return TagByte(name, self.read_byte())
        elif tag_type == TagType.TAG_Short:
            return TagShort(name, self.read_short())
        elif tag_type == TagType.TAG_Int:
            return TagInt(name, self.read_int())
        elif tag_type == TagType.TAG_Long:
            return TagLong(name, self.read_long())
        elif tag_type == TagType.TAG_Float:
            return TagFloat(name, self.read_float())
        elif tag_type == TagType.TAG_Double:
            return TagDouble(name, self.read_double())
        elif tag_type == TagType.TAG_Byte_Array:
            return TagByteArray(name, self.read_byte_array())
        elif tag_type == TagType.TAG_String:
            return TagString(name, self.read_string())
        elif tag_type == TagType.TAG_List:
            return self.read_list(name)
        elif tag_type == TagType.TAG_Compound:
            return self.read_compound(name)
        elif tag_type == TagType.TAG_Int_Array:
            return TagIntArray(name, self.read_int_array())
        elif tag_type == TagType.TAG_Long_Array:
            return TagLongArray(name, self.read_long_array())
        else:
            raise NBTParseError(f"Unknown tag type: {tag_type}")

    def read_list(self, name: Optional[str] = None) -> TagList:
        """Read a TAG_List."""
        try:
            tag_type = TagType(self.read_byte())
        except ValueError as e:
            raise NBTParseError(f"Invalid tag type in list: {e}")

        length = self.read_int()

        if length < 0:
            raise NBTParseError(f"Invalid list length: {length}")

        tags = []
        for _ in range(length):
            tag = self.read_tag(tag_type)
            tags.append(tag)

        return TagList(name, tag_type, tags)

    def read_compound(self, name: Optional[str] = None) -> TagCompound:
        """Read a TAG_Compound."""
        tags = {}

        while True:
            try:
                tag_type = TagType(self.read_byte())
            except ValueError as e:
                raise NBTParseError(f"Invalid tag type in compound: {e}")

            if tag_type == TagType.TAG_End:
                break

            tag_name = self.read_string()
            tag = self.read_tag(tag_type, tag_name)
            tags[tag_name] = tag

        return TagCompound(name, tags)

    def read_root(self) -> TagCompound:
        """Read the root compound tag."""
        try:
            tag_type = TagType(self.read_byte())
        except ValueError as e:
            raise NBTParseError(f"Invalid tag type at root: {e}")

        if tag_type != TagType.TAG_Compound:
            raise NBTParseError(f"Expected TAG_Compound as root, got {tag_type}")

        name = self.read_string()
        return self.read_compound(name)


class NBTWriter:
    """NBT binary data writer."""

    def __init__(self, little_endian: bool = False):
        """
        Initialize NBT writer.

        Args:
            little_endian: Whether to use little-endian byte order (Bedrock Edition)
        """
        self.data = io.BytesIO()
        self.little_endian = little_endian
        self.endian = "<" if little_endian else ">"

    def write_byte(self, value: int):
        """Write a single signed byte."""
        self.data.write(struct.pack("b", value))

    def write_short(self, value: int):
        """Write a signed 16-bit integer."""
        self.data.write(struct.pack(f"{self.endian}h", value))

    def write_int(self, value: int):
        """Write a signed 32-bit integer."""
        self.data.write(struct.pack(f"{self.endian}i", value))

    def write_long(self, value: int):
        """Write a signed 64-bit integer."""
        self.data.write(struct.pack(f"{self.endian}q", value))

    def write_float(self, value: float):
        """Write a 32-bit floating point number."""
        self.data.write(struct.pack(f"{self.endian}f", value))

    def write_double(self, value: float):
        """Write a 64-bit floating point number."""
        self.data.write(struct.pack(f"{self.endian}d", value))

    def write_string(self, value: str):
        """Write a length-prefixed UTF-8 string."""
        encoded = value.encode("utf-8")
        self.write_short(len(encoded))
        self.data.write(encoded)

    def write_byte_array(self, value: List[int]):
        """Write a length-prefixed array of signed bytes."""
        self.write_int(len(value))
        if value:
            self.data.write(struct.pack(f"{len(value)}b", *value))

    def write_int_array(self, value: List[int]):
        """Write a length-prefixed array of signed integers."""
        self.write_int(len(value))
        if value:
            self.data.write(struct.pack(f"{self.endian}{len(value)}i", *value))

    def write_long_array(self, value: List[int]):
        """Write a length-prefixed array of signed longs."""
        self.write_int(len(value))
        if value:
            self.data.write(struct.pack(f"{self.endian}{len(value)}q", *value))

    def write_tag(self, tag: NBTTag, write_header: bool = True):
        """Write a tag."""
        if isinstance(tag, TagEnd):
            if write_header:
                self.write_byte(TagType.TAG_End)
        elif isinstance(tag, TagByte):
            if write_header:
                self.write_byte(TagType.TAG_Byte)
                self.write_string(tag.name or "")
            self.write_byte(tag.value)
        elif isinstance(tag, TagShort):
            if write_header:
                self.write_byte(TagType.TAG_Short)
                self.write_string(tag.name or "")
            self.write_short(tag.value)
        elif isinstance(tag, TagInt):
            if write_header:
                self.write_byte(TagType.TAG_Int)
                self.write_string(tag.name or "")
            self.write_int(tag.value)
        elif isinstance(tag, TagLong):
            if write_header:
                self.write_byte(TagType.TAG_Long)
                self.write_string(tag.name or "")
            self.write_long(tag.value)
        elif isinstance(tag, TagFloat):
            if write_header:
                self.write_byte(TagType.TAG_Float)
                self.write_string(tag.name or "")
            self.write_float(tag.value)
        elif isinstance(tag, TagDouble):
            if write_header:
                self.write_byte(TagType.TAG_Double)
                self.write_string(tag.name or "")
            self.write_double(tag.value)
        elif isinstance(tag, TagByteArray):
            if write_header:
                self.write_byte(TagType.TAG_Byte_Array)
                self.write_string(tag.name or "")
            self.write_byte_array(tag.value)
        elif isinstance(tag, TagString):
            if write_header:
                self.write_byte(TagType.TAG_String)
                self.write_string(tag.name or "")
            self.write_string(tag.value)
        elif isinstance(tag, TagList):
            if write_header:
                self.write_byte(TagType.TAG_List)
                self.write_string(tag.name or "")
            self.write_list(tag)
        elif isinstance(tag, TagCompound):
            if write_header:
                self.write_byte(TagType.TAG_Compound)
                self.write_string(tag.name or "")
            self.write_compound(tag)
        elif isinstance(tag, TagIntArray):
            if write_header:
                self.write_byte(TagType.TAG_Int_Array)
                self.write_string(tag.name or "")
            self.write_int_array(tag.value)
        elif isinstance(tag, TagLongArray):
            if write_header:
                self.write_byte(TagType.TAG_Long_Array)
                self.write_string(tag.name or "")
            self.write_long_array(tag.value)
        else:
            raise NBTWriteError(f"Unknown tag type: {type(tag)}")

    def write_list(self, tag: TagList):
        """Write a TAG_List."""
        self.write_byte(tag.tag_type)
        self.write_int(len(tag.value))

        for item in tag.value:
            self.write_tag(item, write_header=False)

    def write_compound(self, tag: TagCompound):
        """Write a TAG_Compound."""
        for child_tag in tag.value.values():
            self.write_tag(child_tag)

        # Write TAG_End
        self.write_byte(TagType.TAG_End)

    def write_root(self, tag: TagCompound):
        """Write the root compound tag."""
        self.write_byte(TagType.TAG_Compound)
        self.write_string(tag.name or "")
        self.write_compound(tag)

    def get_data(self) -> bytes:
        """Get the written binary data."""
        return self.data.getvalue()


def load(file_path: str, little_endian: bool = False) -> TagCompound:
    """
    Load NBT data from a file.

    Args:
        file_path: Path to the NBT file
        little_endian: Whether to use little-endian byte order (Bedrock Edition)

    Returns:
        The root TagCompound
    """
    with open(file_path, "rb") as f:
        data = f.read()

    return loads(data, little_endian)


def loads(data: bytes, little_endian: bool = False) -> TagCompound:
    """
    Load NBT data from bytes.

    Args:
        data: Raw NBT binary data
        little_endian: Whether to use little-endian byte order (Bedrock Edition)

    Returns:
        The root TagCompound
    """
    # Try to detect compression
    try:
        # Try gzip first
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        # Try zlib
        elif (
            data[:2] == b"\x78\x9c"
            or data[:2] == b"\x78\x01"
            or data[:2] == b"\x78\xda"
        ):
            data = zlib.decompress(data)
    except Exception:
        # If decompression fails, assume uncompressed
        pass

    reader = NBTReader(data, little_endian)
    return reader.read_root()


def dump(
    tag: TagCompound,
    file_path: str,
    compression: Optional[str] = None,
    little_endian: bool = False,
):
    """
    Save NBT data to a file.

    Args:
        tag: The root TagCompound to save
        file_path: Path to save the NBT file
        compression: Compression type ('gzip', 'zlib', or None)
        little_endian: Whether to use little-endian byte order (Bedrock Edition)
    """
    data = dumps(tag, compression, little_endian)

    with open(file_path, "wb") as f:
        f.write(data)


def dumps(
    tag: TagCompound, compression: Optional[str] = None, little_endian: bool = False
) -> bytes:
    """
    Serialize NBT data to bytes.

    Args:
        tag: The root TagCompound to serialize
        compression: Compression type ('gzip', 'zlib', or None)
        little_endian: Whether to use little-endian byte order (Bedrock Edition)

    Returns:
        Serialized NBT binary data
    """
    writer = NBTWriter(little_endian)
    writer.write_root(tag)
    data = writer.get_data()

    if compression == "gzip":
        data = gzip.compress(data)
    elif compression == "zlib":
        data = zlib.compress(data)
    elif compression is not None:
        raise NBTWriteError(f"Unknown compression type: {compression}")

    return data


# Convenience functions for creating tags from Python values
def from_dict(data: Dict[str, Any], name: str = "") -> TagCompound:
    """
    Create a TagCompound from a Python dictionary.

    Args:
        data: Dictionary to convert
        name: Name for the root compound

    Returns:
        TagCompound representation
    """
    compound = TagCompound(name)

    for key, value in data.items():
        if isinstance(value, bool):
            compound[key] = TagByte(key, int(value))
        elif isinstance(value, int):
            if -128 <= value <= 127:
                compound[key] = TagByte(key, value)
            elif -32768 <= value <= 32767:
                compound[key] = TagShort(key, value)
            elif -2147483648 <= value <= 2147483647:
                compound[key] = TagInt(key, value)
            elif -9223372036854775808 <= value <= 9223372036854775807:
                compound[key] = TagLong(key, value)
            else:
                # If the integer is too large for a long, convert to string
                compound[key] = TagString(key, str(value))
        elif isinstance(value, float):
            compound[key] = TagDouble(key, value)
        elif isinstance(value, str):
            compound[key] = TagString(key, value)
        elif isinstance(value, list):
            if not value:
                compound[key] = TagList(key, TagType.TAG_End, [])
            elif all(isinstance(x, int) and -128 <= x <= 127 for x in value):
                compound[key] = TagByteArray(key, value)
            elif all(
                isinstance(x, int) and -2147483648 <= x <= 2147483647 for x in value
            ):
                compound[key] = TagIntArray(key, value)
            elif all(isinstance(x, int) for x in value):
                compound[key] = TagLongArray(key, value)
            else:
                # Create a generic list
                tag_list = TagList(key)
                for item in value:
                    if isinstance(item, dict):
                        tag_list.append(from_dict(item))
                    else:
                        # Convert to appropriate tag type
                        tag_list.append(_value_to_tag(item))
                compound[key] = tag_list
        elif isinstance(value, dict):
            compound[key] = from_dict(value, key)
        else:
            raise NBTWriteError(f"Unsupported type for NBT conversion: {type(value)}")

    return compound


def to_dict(tag: TagCompound) -> Dict[str, Any]:
    """
    Convert a TagCompound to a Python dictionary.

    Args:
        tag: TagCompound to convert

    Returns:
        Dictionary representation
    """
    result = {}

    for key, child_tag in tag.items():
        result[key] = _tag_to_value(child_tag)

    return result


def _value_to_tag(value: Any) -> NBTTag:
    """Convert a Python value to an appropriate NBT tag."""
    if isinstance(value, bool):
        return TagByte(None, int(value))
    elif isinstance(value, int):
        if -128 <= value <= 127:
            return TagByte(None, value)
        elif -32768 <= value <= 32767:
            return TagShort(None, value)
        elif -2147483648 <= value <= 2147483647:
            return TagInt(None, value)
        else:
            return TagLong(None, value)
    elif isinstance(value, float):
        return TagDouble(None, value)
    elif isinstance(value, str):
        return TagString(None, value)
    elif isinstance(value, dict):
        return from_dict(value)
    else:
        raise NBTWriteError(f"Unsupported type for NBT conversion: {type(value)}")


def _tag_to_value(tag: NBTTag) -> Any:
    """Convert an NBT tag to a Python value."""
    if isinstance(tag, (TagByte, TagShort, TagInt, TagLong)):
        return tag.value
    elif isinstance(tag, (TagFloat, TagDouble)):
        return tag.value
    elif isinstance(tag, TagString):
        return tag.value
    elif isinstance(tag, (TagByteArray, TagIntArray, TagLongArray)):
        return tag.value
    elif isinstance(tag, TagList):
        return [_tag_to_value(item) for item in tag.value]
    elif isinstance(tag, TagCompound):
        return to_dict(tag)
    else:
        return tag.value


# Example usage and testing
if __name__ == "__main__":
    # Create a simple NBT structure
    root = TagCompound("hello world")
    root["name"] = TagString("name", "Bananrama")

    # Serialize to binary
    data = dumps(root)
    print(f"Serialized {len(data)} bytes")

    # Deserialize back
    loaded = loads(data)
    print(f"Loaded: {loaded}")
    print(f"Name value: {loaded['name'].value}")

    # Test dictionary conversion
    test_dict = {
        "name": "Test Player",
        "level": 42,
        "health": 20.0,
        "inventory": [1, 2, 3, 4, 5],
        "position": {"x": 100.5, "y": 64.0, "z": -200.25},
    }

    nbt_from_dict = from_dict(test_dict, "TestData")
    dict_from_nbt = to_dict(nbt_from_dict)
    print(f"Original dict: {test_dict}")
    print(f"Converted back: {dict_from_nbt}")
