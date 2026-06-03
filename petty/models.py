import re
from dataclasses import dataclass
from typing import Literal, Optional, overload

import orjson

from petty.assets import item_mapping


@dataclass
class Pos:
    """Integer block position"""

    x: int = 0
    y: int = 0
    z: int = 0


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


class SlotData:
    __slots__ = ("item", "count", "damage", "nbt")

    @overload
    def __init__(self, item: None = None) -> None: ...
    @overload
    def __init__(
        self, item: Item, count: int = 1, damage: int = 0, nbt: bytes = b""
    ) -> None: ...

    def __init__(
        self,
        item: Optional[Item] = None,
        count: int = 1,
        damage: int = 0,
        nbt: bytes = b"",
    ):
        self.item = item
        if item is None:
            self.count = 0
            self.damage = 0
            self.nbt = b""
        else:
            self.count = count
            self.damage = damage
            self.nbt = nbt


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
                    first["extra"] = data[1:]
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
        return f"TextComponent({orjson.dumps(self.data).decode()})"

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

    def click_event(
        self,
        action: Literal[
            "open_url",
            "run_command",
            "suggest_command",
            "change_page",
            # "copy_to_clipboard", # does not seem to work in 1.8
        ],
        value: str,
    ) -> TextComponent:
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
        return TextComponent(orjson.loads(orjson.dumps(self.data)))

    def to_dict(self) -> dict:
        """Get the underlying dictionary representation"""
        return self.data.copy()

    def to_json(self) -> str:
        """Convert to JSON string"""
        return orjson.dumps(self.data).decode()

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
                    first["extra"] = component[1:]
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

    _REVERSE_COLORS: dict[str, str] = {v: k for k, v in COLOR_CODES.items()}
    _REVERSE_FORMATS: dict[str, str] = {
        v: k for k, v in FORMAT_CODES.items() if v != "reset"
    }

    def to_legacy(self) -> str:
        """Convert this TextComponent to a legacy §-formatted string."""
        parts: list[str] = []
        self._build_legacy(self.data, parts)
        return "".join(parts)

    @classmethod
    def _build_legacy(cls, data: dict | str | list, parts: list[str]) -> None:
        if isinstance(data, str):
            parts.append(data)
            return
        if isinstance(data, list):
            for item in data:
                cls._build_legacy(item, parts)
            return

        prefix = ""
        color = data.get("color")
        if color and color in cls._REVERSE_COLORS:
            prefix += f"§{cls._REVERSE_COLORS[color]}"
        for fmt, code in cls._REVERSE_FORMATS.items():
            if data.get(fmt):
                prefix += f"§{code}"

        text = data.get("text", "")
        if text or prefix:
            parts.append(f"{prefix}{text}")

        for child in data.get("extra", []):
            cls._build_legacy(child, parts)
