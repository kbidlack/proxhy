Minecraft supports a wide variety of datatypes. Proxhy implements a complete type system for the Minecraft network protocol, providing type-safe serialization and deserialization of all Minecraft data types.

## Overview

The data type system in `datatypes.py` provides:
- **Type Safety**: Each data type has proper Python type hints
- **Automatic Serialization**: Convert Python objects to bytes for network transmission
- **Stream Parsing**: Read data types directly from network streams
- **Buffer Management**: Efficient byte manipulation with the Buffer class

## Core Architecture

### Base DataType Class


All data types inherit from the abstract `DataType` base class:

```python
class DataType[PT, UT](ABC):  # PT: pack type, UT: unpack type
    @staticmethod
    @abstractmethod
    def pack(value: PT) -> bytes:
        """Serialize Python value to bytes"""
        pass

    @staticmethod 
    @abstractmethod
    def unpack(buff: Buffer) -> UT:
        """Deserialize bytes to Python value"""
        pass

    def __new__(cls, value: PT) -> bytes:
        """Allow direct instantiation: VarInt(42) -> bytes"""
        return cls.pack(value)
```

There is a lot of complex Python typing present in this file. At it's core, though, PT and UT are generic types which represent the pack type and unpack type of the certain datatype.

One of the most important classes in this file, however, is the `Buffer` class, which inherits (and therefore acts very similarly to) the `BytesIO` class. 

However, there is a notable difference. The `Buffer` class has an `unpack` method that, given a datatype, will unpack that datatype from the Buffer:

```python
class Buffer(BytesIO):
    def unpack[T](self, kind: type[DataType[Any, T]]) -> T:
        """Unpack a data type from the buffer"""
        return kind.unpack(self)

# Usage
buff = Buffer(packet_data)
value = buff.unpack(VarInt)  # Returns an int (VarInt is Datatype[int, int])
remaining = buff.read()      # Read remaining bytes
```

For example, for a String:
```py
class String(DataType[str | TextComponent, str]):
    @staticmethod
    def pack(value: str | TextComponent) -> bytes:
        ...

    @staticmethod
    def unpack(buff) -> str:
        ...
```

This design allows both explicit packing/unpacking and direct instantiation:

```python
# Direct instantiation (returns bytes)
packet_data = VarInt(42) + String("hello") + Boolean(True)

# Explicit packing
bytes_data = VarInt.pack(42)

# Unpacking from buffer
buff = Buffer(packet_data)
number: int = buff.unpack(VarInt)
text: str = buff.unpack(String)
flag: bool = buff.unpack(Boolean)
```

The datatypes module also includes a TextComponent class, which is so extensive that it deserves its own file: [TextComponent.md](TextComponent.md)