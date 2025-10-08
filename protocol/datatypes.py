import json
import re
import struct
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.resources import files  # noqa: F401
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional, Protocol

if TYPE_CHECKING:

    class AsyncReader[T](Protocol):
        async def read(self, n: int = -1) -> T: ...


@dataclass
class Pos:
    """integer block position"""

    x: int = 0
    y: int = 0
    z: int = 0


# TODO: fix this and others
# im_path = files("proxhy.assets").joinpath("item_mappings.json")

im_path = Path(__file__).parent.parent / "assets/item_mappings.json"

with im_path.open("r") as file:
    item_mapping = json.load(file)


@dataclass
class Item:
    id: int
    name: str
    display_name: str
    data: int

    @classmethod
    def from_name(cls, name: str):
        if not name.startswith("minecraft:"):
            name = f"minecraft:{name}"

        item = next((item for item in item_mapping if item.get("name") == name), None)
        return cls(**item) if item else None

    @classmethod
    def from_display_name(cls, display_name: str):
        item = next(
            (item for item in item_mapping if item.get("display_name") == display_name),
            None,
        )
        return cls(**item) if item else None

    @classmethod
    def from_id(cls, id: int):
        item = next((item for item in item_mapping if item.get("id") == id), None)
        return cls(**item) if item else None


@dataclass
class SlotData:
    item: Optional[Item] = None
    count: int = 1
    damage: int = 0
    nbt: bytes = b""


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
        return VarInt(len(value)) + value

    @staticmethod
    def unpack(buff) -> bytes:
        length = VarInt.unpack(buff)
        return buff.read(length)


# Minecraft text component implementation
class TextComponent:
    """
    Represents a Minecraft text component with full formatting support.
    """

    COLOR_CODES = {
        "0": "black",
        "1": "dark_blue",
        "2": "dark_green",
        "3": "dark_aqua",
        "4": "dark_red",
        "5": "dark_purple",
        "6": "gold",
        "7": "gray",
        "8": "dark_gray",
        "9": "blue",
        "a": "green",
        "b": "aqua",
        "c": "red",
        "d": "light_purple",
        "e": "yellow",
        "f": "white",
    }
    FORMAT_CODES = {
        "k": "obfuscated",
        "l": "bold",
        "m": "strikethrough",
        "n": "underlined",
        "o": "italic",
        "r": "reset",
    }

    def __init__(self, data=None):
        if data is None:
            data = {}
        elif isinstance(data, str):
            data = {"text": data}
        elif isinstance(data, list):
            # Convert array format to object with extra
            if data:
                first = data[0] if isinstance(data[0], dict) else {"text": str(data[0])}
                if len(data) > 1:
                    first["extra"] = data[1:]  # type: ignore
                data = first
            else:
                data = {}
        elif isinstance(data, TextComponent):
            data = data.data.copy()  # Use the internal data dict
        self.data: dict = data.copy() if isinstance(data, dict) else {}

        # Validate and auto-detect content type
        self._validate_and_normalize()

    def __repr__(self) -> str:
        """Return a string representation of the component"""
        return f"TextComponent({json.dumps(self.data, separators=(',', ':'))})"

    def _validate_and_normalize(self):
        """Validate component structure and auto-detect content type"""
        # Auto-detect content type if not specified
        if "type" not in self.data:
            content_types = ["text", "translate", "score", "selector", "keybind", "nbt"]
            for content_type in content_types:
                if content_type in self.data or (
                    content_type == "score" and "score" in self.data
                ):
                    self.data["type"] = content_type
                    break
            else:
                # Default to text type if no content is found
                if not any(ct in self.data for ct in content_types):
                    self.data["type"] = "text"

    # Content type methods
    def set_text(self, text: str) -> TextComponent:
        """Set plain text content"""
        self.data["text"] = text
        self.data["type"] = "text"
        self._remove_content_fields(except_field="text")
        return self

    def set_translate(self, key: str, with_args=None, fallback=None) -> TextComponent:
        """Set translatable text content"""
        self.data["translate"] = key
        self.data["type"] = "translatable"
        if with_args:
            self.data["with"] = [self._normalize_component(arg) for arg in with_args]
        if fallback:
            self.data["fallback"] = fallback
        self._remove_content_fields(except_field="translate")
        return self

    def set_score(self, name: str, objective: str) -> TextComponent:
        """Set scoreboard value content"""
        self.data["score"] = {"name": name, "objective": objective}
        self.data["type"] = "score"
        self._remove_content_fields(except_field="score")
        return self

    def set_selector(self, selector: str, separator=None) -> TextComponent:
        """Set entity selector content"""
        self.data["selector"] = selector
        self.data["type"] = "selector"
        if separator:
            self.data["separator"] = self._normalize_component(separator)
        self._remove_content_fields(except_field="selector")
        return self

    def set_keybind(self, keybind: str) -> TextComponent:
        """Set keybind content"""
        self.data["keybind"] = keybind
        self.data["type"] = "keybind"
        self._remove_content_fields(except_field="keybind")
        return self

    def set_nbt(
        self,
        nbt_path: str,
        source: str | None = None,
        block: str | None = None,
        entity: str | None = None,
        storage: str | None = None,
        interpret: bool = False,
        separator=None,
    ) -> TextComponent:
        """Set NBT content"""
        self.data["nbt"] = nbt_path
        self.data["type"] = "nbt"
        if source:
            self.data["source"] = source
        if block:
            self.data["block"] = block
        if entity:
            self.data["entity"] = entity
        if storage:
            self.data["storage"] = storage
        if interpret:
            self.data["interpret"] = interpret
        if separator:
            self.data["separator"] = self._normalize_component(separator)
        self._remove_content_fields(except_field="nbt")
        return self

    # Formatting methods
    def color(
        self,
        color: Literal[
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
    ) -> TextComponent:
        self.data["color"] = color
        return self

    def font(self, font: str) -> TextComponent:
        """Set font resource location"""
        self.data["font"] = font
        return self

    def bold(self, bold: bool = True) -> TextComponent:
        """Set bold formatting"""
        self.data["bold"] = bold
        return self

    def italic(self, italic: bool = True) -> TextComponent:
        """Set italic formatting"""
        self.data["italic"] = italic
        return self

    def underlined(self, underlined: bool = True) -> TextComponent:
        """Set underlined formatting"""
        self.data["underlined"] = underlined
        return self

    def strikethrough(self, strikethrough: bool = True) -> TextComponent:
        """Set strikethrough formatting"""
        self.data["strikethrough"] = strikethrough
        return self

    def obfuscated(self, obfuscated: bool = True) -> TextComponent:
        """Set obfuscated formatting"""
        self.data["obfuscated"] = obfuscated
        return self

    def shadow_color(self, color) -> TextComponent:
        """Set shadow color (int or [a,r,g,b] list)"""
        self.data["shadow_color"] = color
        return self

    # Interactivity methods
    def insertion(self, text: str) -> TextComponent:
        """Set shift-click insertion text"""
        self.data["insertion"] = text
        return self

    def click_event(self, action: str, value: str) -> TextComponent:
        """Set click event (open_url, run_command, suggest_command, etc.)"""
        self.data["clickEvent"] = {"action": action, "value": value}
        return self

    def hover_text(self, text) -> TextComponent:
        """Set hover tooltip with text"""
        self.data["hoverEvent"] = {
            "action": "show_text",
            "value": self._normalize_component(text),
        }
        return self

    # Child component methods
    def append(self, component) -> TextComponent:
        """Add a child component"""
        if "extra" not in self.data:
            self.data["extra"] = []
        self.data["extra"].append(self._normalize_component(component))
        return self

    def appends(self, component, separator=" ") -> TextComponent:
        "Add a child component with a separator (defaults to space)"
        component = TextComponent(self._normalize_component(component))
        if not component.data.get("text"):
            component.set_text(separator)
        else:
            component.data["text"] = f"{separator}{component.data.get('text', '')}"

        self.append(component)
        return self

    def extend(self, components) -> "TextComponent":
        """Add multiple child components"""
        for component in components:
            self.append(component)
        return self

    def prepend(self, component) -> TextComponent:
        """Add a child component at the beginning"""
        if "extra" not in self.data:
            self.data["extra"] = []
        self.data["extra"].insert(0, self._normalize_component(component))
        return self

    def remove_child(self, index: int) -> TextComponent:
        """Remove a child component by index"""
        if "extra" in self.data and 0 <= index < len(self.data["extra"]):
            del self.data["extra"][index]
            if not self.data["extra"]:
                del self.data["extra"]
        return self

    def replace_child(self, index: int, component) -> TextComponent:
        """Replace a child component"""
        if "extra" in self.data and 0 <= index < len(self.data["extra"]):
            self.data["extra"][index] = self._normalize_component(component)
        return self

    def clear_children(self) -> TextComponent:
        """Remove all child components"""
        if "extra" in self.data:
            del self.data["extra"]
        return self

    # Utility methods
    def copy(self) -> TextComponent:
        """Create a deep copy of this component"""
        return TextComponent(json.loads(json.dumps(self.data)))

    def to_dict(self) -> dict:
        """Get the underlying dictionary representation"""
        return self.data.copy()

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.data, separators=(",", ":"))

    def is_empty(self) -> bool:
        """Check if component has no content"""
        content_fields = {"text", "translate", "score", "selector", "keybind", "nbt"}
        return not any(field in self.data for field in content_fields)

    def get_children(self) -> list[TextComponent]:
        """Get list of child components"""
        return [TextComponent(child) for child in self.data.get("extra", [])]

    def flatten(self) -> TextComponent:
        """Flatten extras"""
        # Create a copy of this component without the extra field
        flattened_data = {k: v for k, v in self.data.items() if k != "extra"}
        flattened = TextComponent(flattened_data)

        # Recursively collect all child components
        def collect_children(component_data):
            children = []
            if "extra" in component_data:
                for child in component_data["extra"]:
                    # Add the child itself
                    child_component = TextComponent(child)
                    # Remove extra from the child for this level
                    child_data = {
                        k: v for k, v in child_component.data.items() if k != "extra"
                    }
                    children.append(child_data)

                    # Recursively collect grandchildren
                    children.extend(collect_children(child))
            return children

        # Collect all children and add them to the flattened component
        all_children = collect_children(self.data)
        if all_children:
            flattened.data["extra"] = all_children

        self.data = flattened.data.copy()
        return self

    def _normalize_component(self, component):
        """Convert various component formats to dict"""
        if isinstance(component, TextComponent):
            return component.data
        elif isinstance(component, str):
            return {"text": component}
        elif isinstance(component, dict):
            return component
        elif isinstance(component, list):
            if component:
                first = (
                    component[0]
                    if isinstance(component[0], dict)
                    else {"text": str(component[0])}
                )
                if len(component) > 1:
                    first["extra"] = component[1:]  # type: ignore
                return first
            return {}
        else:
            return {"text": str(component)}

    def _remove_content_fields(self, except_field=None):
        """Remove other content type fields when setting a new content type"""
        content_fields = {
            "text",
            "translate",
            "score",
            "selector",
            "keybind",
            "nbt",
            "with",
            "fallback",
            "separator",
            "interpret",
            "block",
            "entity",
            "storage",
            "source",
        }
        if except_field:
            content_fields.discard(except_field)
            # Keep related fields for specific content types
            if except_field == "translate":
                content_fields.discard("with")
                content_fields.discard("fallback")
            elif except_field == "selector":
                content_fields.discard("separator")
            elif except_field == "nbt":
                content_fields.discard("separator")
                content_fields.discard("interpret")
                content_fields.discard("block")
                content_fields.discard("entity")
                content_fields.discard("storage")
                content_fields.discard("source")

        for field in content_fields:
            self.data.pop(field, None)

    def __str__(self) -> str:
        """Convert to plain text (same as old Chat.unpack behavior)"""
        return self._parse_to_text(self.data)

    def _parse_to_text(self, data) -> str:
        """Parse component data to plain text (legacy behavior)"""
        text = ""
        if isinstance(data, str):
            return data
        if isinstance(data, list):
            return "".join((self._parse_to_text(e) for e in data))

        if "translate" in data:
            text += data["translate"]
            if "with" in data:
                args = ", ".join((self._parse_to_text(e) for e in data["with"]))
                text += "{%s}" % args
        if "text" in data:
            text += data["text"]
        if "extra" in data:
            text += self._parse_to_text(data["extra"])
        return re.sub("\u00a7.", "", text)

    @classmethod
    def from_legacy(cls, text: str) -> TextComponent:
        """
        Convert a string with Minecraft color codes (§) to a TextComponent.
        Supports color and formatting codes. Resets formatting on §r.
        """
        # Pattern: §[0-9a-frk-or]
        pattern = re.compile(r"(§[0-9a-frk-or])", re.IGNORECASE)
        parts = pattern.split(text)
        # Remove empty strings
        parts = [p for p in parts if p]

        # Formatting state
        current = {
            "color": None,
            "bold": False,
            "italic": False,
            "underlined": False,
            "strikethrough": False,
            "obfuscated": False,
        }
        root = cls("")
        current_component = root
        buffer = ""

        def apply_formatting(component, state):
            if state["color"]:
                component.color(state["color"])
            if state["bold"]:
                component.bold(True)
            if state["italic"]:
                component.italic(True)
            if state["underlined"]:
                component.underlined(True)
            if state["strikethrough"]:
                component.strikethrough(True)
            if state["obfuscated"]:
                component.obfuscated(True)
            return component

        for part in parts:
            if part.startswith("§"):
                # Flush buffer as a component with previous formatting
                if buffer:
                    comp = cls(buffer)
                    apply_formatting(comp, current)
                    current_component.append(comp)
                    buffer = ""
                code = part[1].lower()
                if code in cls.COLOR_CODES:
                    # Color code resets formatting except obfuscated
                    current = {
                        "color": cls.COLOR_CODES[code],
                        "bold": False,
                        "italic": False,
                        "underlined": False,
                        "strikethrough": False,
                        "obfuscated": current["obfuscated"],
                    }
                elif code in cls.FORMAT_CODES:
                    if code == "r":
                        # Reset all formatting
                        current = {
                            "color": None,
                            "bold": False,
                            "italic": False,
                            "underlined": False,
                            "strikethrough": False,
                            "obfuscated": False,
                        }
                    else:
                        field = cls.FORMAT_CODES[code]
                        current[field] = True
            else:
                buffer += part

        # Flush any remaining buffer
        if buffer:
            comp = cls(buffer)
            apply_formatting(comp, current)
            current_component.append(comp)

        # Remove the initial empty root if it has only one child
        if "extra" in root.data and len(root.data["extra"]) == 1:
            return cls(root.data["extra"][0])
        return root


class Chat(DataType[str, str]):
    """Chat message from the server - enhanced with TextComponent support"""

    @staticmethod
    def pack(value: str | TextComponent | dict) -> bytes:
        """Pack a text component or string to bytes"""
        if isinstance(value, TextComponent):
            return String(value.to_json())
        elif isinstance(value, str):
            return String(json.dumps({"text": value}))
        elif isinstance(value, dict):
            return String(json.dumps(value))
        else:
            return String(json.dumps({"text": str(value)}))

    @staticmethod
    def pack_msg(value: str | TextComponent | dict) -> bytes:
        """Pack a text component or string with field set to chat message (0)"""
        return Chat.pack(value) + b"\x00"

    @staticmethod
    def unpack(buff) -> str:
        """Unpack to plain text string (legacy behavior)"""
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

    @staticmethod
    def unpack_component(buff) -> TextComponent:
        """Unpack to TextComponent object"""
        data = json.loads(buff.unpack(String))
        return TextComponent(data)


class String(DataType[str | TextComponent, str]):
    @staticmethod
    def pack(value: str | TextComponent) -> bytes:
        bvalue = str(value).encode("utf-8")
        return VarInt(len(bvalue)) + bvalue

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
        return UnsignedByte(int(256 * ((value % 360) / 360)))
        # return struct.pack(">B", int(value * 256 / 360) & 0xFF)

    @staticmethod
    def unpack(buff: Buffer) -> float:
        return 360 * buff.unpack(UnsignedByte) / 256
        return (struct.unpack(">B", buff.read(1))[0] * 360) / 256


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

        rest_of_data = buff.read()
        nbt = b"" if not rest_of_data[0] else rest_of_data

        return SlotData(Item.from_id(item_id), count, damage, nbt)
