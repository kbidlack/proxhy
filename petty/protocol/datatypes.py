import re
import struct
import uuid
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any, Protocol

import orjson

from petty import nbt
from petty.models import Item, Pos, SlotData, TextComponent


class AsyncReader[T](Protocol):
    async def read(self, n: int = -1) -> T: ...


class Buffer(BytesIO):
    def unpack[T](self, kind: type[DataType[Any, T]]) -> T:
        return kind.unpack(self)

    def clone(self) -> Buffer:
        return Buffer(self.getvalue())


class DataType[PT, UT](ABC):  # UT: unpack type, PT: pack type
    value: PT | UT

    def __new__(cls, value: PT) -> bytes:
        return cls.pack(value)

    @staticmethod
    @abstractmethod
    def pack(value: PT) -> bytes:
        pass

    @staticmethod
    @abstractmethod
    def unpack(buff: Buffer) -> UT:
        pass


class VarInt(DataType[int, int]):
    def __repr__(self) -> str:
        return str(self.value)

    # https://gist.github.com/nickelpro/7312782
    @staticmethod
    def pack(value: int) -> bytes:
        total = b""
        val = (1 << 32) + value if value < 0 else value

        while val >= 0x80:
            bits = val & 0x7F
            val >>= 7
            total += struct.pack("B", (0x80 | bits))

        bits = val & 0x7F
        total += struct.pack("B", bits)
        return total

    @staticmethod
    def unpack(buff) -> int:
        total = 0
        shift = 0
        val = 0x80

        while val & 0x80:
            val = struct.unpack("B", buff.read(1))[0]
            total |= (val & 0x7F) << shift
            shift += 7
        return total - (1 << 32) if total & (1 << 31) else total

    @staticmethod
    async def unpack_stream(stream: AsyncReader[bytes]) -> int:
        total = 0
        shift = 0
        val = 0x80

        while (val & 0x80) and (data := await stream.read(1)):
            val = struct.unpack("B", data)[0]
            total |= (val & 0x7F) << shift
            shift += 7

        return total - (1 << 32) if total & (1 << 31) else total


class UnsignedShort(DataType[int, int]):
    @staticmethod
    def pack(value: int) -> bytes:
        return struct.pack(">H", value)

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">H", buff.read(2))[0]


class Short(DataType[int, int]):
    @staticmethod
    def pack(value: int) -> bytes:
        return struct.pack(">h", value)

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">h", buff.read(2))[0]


class Long(DataType[int, int]):
    @staticmethod
    def pack(value: int) -> bytes:
        return struct.pack(">q", value)

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">q", buff.read(8))[0]


class Byte(DataType[bytes | int | float, int]):
    @staticmethod
    def pack(value: bytes | int | float) -> bytes:
        if isinstance(value, (int, float)):
            return struct.pack(">b", int(value))
        return value

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">b", buff.read(1))[0]


class UnsignedByte(DataType[int, int]):
    @staticmethod
    def pack(value: bytes | int | float) -> bytes:
        if isinstance(value, (int, float)):
            return struct.pack(">B", int(value))
        return value

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">B", buff.read(1))[0]


class ByteArray(DataType[bytes, bytes]):
    @staticmethod
    def pack(value: bytes) -> bytes:
        return VarInt.pack(len(value)) + value

    @staticmethod
    def unpack(buff) -> bytes:
        length = VarInt.unpack(buff)
        return buff.read(length)


class Chat(DataType[str, str]):
    """Chat message from the server - enhanced with TextComponent support"""

    @staticmethod
    def pack(value: str | TextComponent | dict) -> bytes:
        """Pack a text component or string to bytes"""
        if isinstance(value, TextComponent):
            return String.pack(value.to_json())
        elif isinstance(value, str):
            return String.pack(orjson.dumps({"text": value}).decode())
        elif isinstance(value, dict):
            return String.pack(orjson.dumps(value).decode())
        else:
            return String.pack(orjson.dumps({"text": str(value)}).decode())

    @staticmethod
    def pack_msg(value: str | TextComponent | dict) -> bytes:
        """Pack a text component or string with field set to chat message (0)"""
        return Chat.pack(value) + b"\x00"

    @staticmethod
    def unpack(buff) -> str:
        """Unpack to plain text string (legacy behavior)"""
        # https://github.com/barneygale/quarry/blob/master/quarry/types/chat.py#L86-L107
        data = orjson.loads(buff.unpack(String))

        def parse(data):
            text = ""
            if isinstance(data, str):
                return data
            if isinstance(data, list):
                return "".join((parse(e) for e in data))

            if "translate" in data:
                text += data["translate"]
                if "with" in data:
                    args = ", ".join((parse(e) for e in data["with"]))
                    text += "{%s}" % args
            if "text" in data:
                text += data["text"]
            if "extra" in data:
                text += parse(data["extra"])
            return text

        return re.sub("\u00a7.", "", parse(data))

    @staticmethod
    def unpack_component(buff) -> TextComponent:
        """Unpack to TextComponent object"""
        data = orjson.loads(buff.unpack(String))
        return TextComponent(data)


class String(DataType[str | TextComponent, str]):
    @staticmethod
    def pack(value: str | TextComponent) -> bytes:
        bvalue = str(value).encode("utf-8")
        return VarInt.pack(len(bvalue)) + bvalue

    @staticmethod
    def unpack(buff) -> str:
        length = VarInt.unpack(buff)
        return buff.read(length).decode("utf-8")


class UUID(DataType[uuid.UUID, uuid.UUID]):
    @staticmethod
    def pack(value: uuid.UUID) -> bytes:
        return value.bytes

    @staticmethod
    def unpack(buff) -> uuid.UUID:
        return uuid.UUID(bytes=buff.read(16))


class Boolean(DataType[bool, bool]):
    @staticmethod
    def pack(value: bool) -> bytes:
        return b"\x01" if value else b"\x00"

    @staticmethod
    def unpack(buff) -> bool:
        return bool(buff.read(1)[0])


class Int(DataType[int, int]):
    @staticmethod
    def pack(value: int) -> bytes:
        return struct.pack(">i", int(value))

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">i", buff.read(4))[0]


class Position(DataType[Pos, Pos]):
    @staticmethod
    def pack(value: tuple[int, int, int] | Pos) -> bytes:
        if isinstance(value, Pos):
            value = value.x, value.y, value.z

        x, y, z = value
        x &= 0x3FFFFFF
        y &= 0xFFF
        z &= 0x3FFFFFF
        return struct.pack(">Q", (x << 38) | (y << 26) | z)

    @staticmethod
    def unpack(buff) -> Pos:
        # decode position (rewrite function):
        value = struct.unpack(">Q", buff.read(8))[0]
        x = value >> 38
        y = (value >> 26) & 0xFFF
        z = value & 0x3FFFFFF
        if x >= 2**25:
            x -= 2**26
        if y >= 2**11:
            y -= 2**12
        if z >= 2**25:
            z -= 2**26
        return Pos(x, y, z)


class Double(DataType[float, float]):
    @staticmethod
    def pack(value: float) -> bytes:
        return struct.pack(">d", value)

    @staticmethod
    def unpack(buff) -> float:
        return struct.unpack(">d", buff.read(8))[0]


class Float(DataType[float, float]):
    @staticmethod
    def pack(value: float) -> bytes:
        return struct.pack(">f", value)

    @staticmethod
    def unpack(buff) -> float:
        return struct.unpack(">f", buff.read(4))[0]


class Angle(DataType[float, float]):
    @staticmethod
    def pack(value: float) -> bytes:
        return UnsignedByte.pack(int(256 * ((value % 360) / 360)))
        # return struct.pack(">B", int(value * 256 / 360) & 0xFF)

    @staticmethod
    def unpack(buff: Buffer) -> float:
        return 360 * buff.unpack(UnsignedByte) / 256


class Slot(DataType[SlotData, SlotData]):
    @staticmethod
    def pack(value: SlotData) -> bytes:
        if value.item is None:
            return Short.pack(-1)

        if not value.nbt:
            return (
                Short.pack(value.item.id)
                + Byte.pack(value.count)
                + Short.pack(value.damage)
                + Byte.pack(0)
            )
        else:
            return (
                Short.pack(value.item.id)
                + Byte.pack(value.count)
                + Short.pack(value.damage)
                + value.nbt
            )

    @staticmethod
    def unpack(buff: Buffer) -> SlotData:
        item_id = buff.unpack(Short)
        if item_id == -1:
            return SlotData()

        count = buff.unpack(Byte)
        damage = buff.unpack(Short)

        nbt_data = Slot._read_nbt(buff)

        return SlotData(Item.from_id(item_id), count, damage, nbt_data)

    @staticmethod
    def _read_nbt(buff: Buffer) -> bytes:
        """Read NBT data from buffer and return the raw bytes"""
        start_pos = buff.tell()

        # Peek at tag type
        tag_type_byte = buff.read(1)
        if not tag_type_byte or tag_type_byte[0] == 0:
            # TAG_End or empty - no NBT data
            return b""

        # Reset to start and read the full NBT structure using the nbt library
        buff.seek(start_pos)

        # Read enough bytes to parse the NBT - we'll use the NBTReader to determine the size
        # First, get all remaining bytes from current position
        remaining_data = buff.read()
        buff.seek(start_pos)

        if not remaining_data:
            return b""

        try:
            # Use NBTReader to parse and determine exact size
            reader = nbt.NBTReader(remaining_data)
            reader.read_root()  # This will parse the NBT structure

            # The reader's internal BytesIO position tells us how many bytes were consumed
            bytes_consumed = reader.data.tell()

            # Now read exactly that many bytes from the original buffer
            nbt_data = buff.read(bytes_consumed)
            return nbt_data

        except (nbt.NBTError, Exception):
            # If parsing fails, assume no NBT data
            buff.seek(start_pos)
            buff.read(1)  # Consume the tag type byte we already read
            return b""
