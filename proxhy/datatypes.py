from __future__ import annotations

import json
import re
import struct
import uuid
from abc import ABC, abstractmethod
from io import BytesIO
from typing import TYPE_CHECKING

from .mcmodels import Pos

if TYPE_CHECKING:
    from _typeshed import SupportsRead


class Buffer(BytesIO):
    def unpack[T](self, kind: type[DataType[T]]) -> T:
        return kind.unpack(self)


class DataType[T](ABC):
    def __new__(cls, value: T) -> bytes:
        return cls.pack(value)

    @staticmethod
    @abstractmethod
    def pack(value: T) -> bytes:
        pass

    @staticmethod
    @abstractmethod
    def unpack(buff: SupportsRead[bytes]) -> T:
        pass


class VarInt(DataType[int]):
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
    async def unpack_stream(stream: SupportsRead[bytes]) -> int:
        total = 0
        shift = 0
        val = 0x80

        while (val & 0x80) and (data := await stream.read(1)):
            val = struct.unpack("B", data)[0]
            total |= (val & 0x7F) << shift
            shift += 7

        return total - (1 << 32) if total & (1 << 31) else total


class String(DataType[str]):
    @staticmethod
    def pack(value: str) -> bytes:
        bvalue = value.encode("utf-8")
        return VarInt(len(bvalue)) + bvalue

    @staticmethod
    def unpack(buff) -> str:
        length = VarInt.unpack(buff)
        return buff.read(length).decode("utf-8")


class UnsignedShort(DataType[int]):
    @staticmethod
    def pack(value: int) -> bytes:
        return struct.pack(">H", value)

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">H", buff.read(2))[0]


class Short(DataType[int]):
    @staticmethod
    def pack(value: int) -> bytes:
        return struct.pack(">h", value)

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">h", buff.read(2))[0]


class Long(DataType[int]):
    @staticmethod
    def pack(value: int) -> bytes:
        return struct.pack(">q", value)

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">q", buff.read(8))[0]


class Byte(DataType[bytes]):
    # could unpack >b (to int)
    @staticmethod
    def pack(value: bytes | int | float) -> bytes:
        if isinstance(value, (int, float)):
            return struct.pack(">b", int(value))
        return value

    @staticmethod
    def unpack(buff) -> bytes:
        return buff.read(1)


class UnsignedByte(DataType[int]):
    @staticmethod
    def pack(value: bytes | int | float) -> bytes:
        if isinstance(value, (int, float)):
            try:
                return struct.pack(">B", int(value))
            except struct.error:
                print(value)
        return value

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">B", buff.read(1))[0]


class ByteArray(DataType[bytes]):
    @staticmethod
    def pack(value: bytes) -> bytes:
        return VarInt(len(value)) + value

    @staticmethod
    def unpack(buff) -> bytes:
        length = VarInt.unpack(buff)
        return buff.read(length)


# temporary solution
class Chat(DataType[str]):
    """Chat message from the server"""

    @staticmethod
    def pack(value: str) -> bytes:
        return String(json.dumps({"text": value}))

    @staticmethod
    def pack_msg(value: str) -> bytes:
        return String(json.dumps({"text": value})) + b"\x00"

    @staticmethod
    def unpack(buff) -> str:
        # https://github.com/barneygale/quarry/blob/master/quarry/types/chat.py#L86-L107
        data = json.loads(buff.unpack(String))

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


class UUID(DataType[uuid.UUID]):
    @staticmethod
    def pack(_uuid: uuid.UUID) -> bytes:
        return _uuid.bytes

    @staticmethod
    def unpack(buff) -> uuid.UUID:
        return uuid.UUID(bytes=buff.read(16))


class Boolean(DataType[bool]):
    @staticmethod
    def pack(val: bool) -> bytes:
        return b"\x01" if val else b"\x00"

    @staticmethod
    def unpack(buff) -> bool:
        return bool(buff.read(1)[0])


class Int(DataType[int]):
    @staticmethod
    def pack(value: int) -> bytes:
        return struct.pack(">i", int(value))

    @staticmethod
    def unpack(buff) -> int:
        return struct.unpack(">i", buff.read(4))[0]


class Position(DataType[Pos]):
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


class Double(DataType[float]):
    @staticmethod
    def pack(value: float) -> bytes:
        return struct.pack(">d", value)

    @staticmethod
    def unpack(buff) -> float:
        return struct.unpack(">d", buff.read(8))[0]


class Float(DataType[float]):
    @staticmethod
    def pack(value: float) -> bytes:
        return struct.pack(">f", value)

    @staticmethod
    def unpack(buff) -> float:
        return struct.unpack(">f", buff.read(4))[0]


class Angle(DataType[float]):
    @staticmethod
    def pack(value: float) -> bytes:
        return UnsignedByte(int(256 * ((value % 360) / 360)))
        # return struct.pack(">B", int(value * 256 / 360) & 0xFF)

    @staticmethod
    def unpack(buff: Buffer) -> float:
        return 360 * buff.unpack(UnsignedByte) / 256
        return (struct.unpack(">B", buff.read(1))[0] * 360) / 256
