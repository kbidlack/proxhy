# Enhanced TextComponent Implementation

This enhanced implementation provides a comprehensive Minecraft text component system that adheres to the [official Minecraft Text Component Format](https://minecraft.wiki/w/Text_component_format/Before_Java_Edition_1.21.5) while maintaining backward compatibility with the existing codebase.

## Features

### ✅ Complete Minecraft Text Component Support
- **Content Types**: text, translate, score, selector, keybind, nbt
- **Formatting**: color, font, bold, italic, underlined, strikethrough, obfuscated, shadow_color
- **Interactivity**: click events, hover events, insertion text
- **Structure**: nested components with `extra` array support

### ✅ Dictionary-like Access
The `TextComponent` class provides both method-based and direct dictionary access:
```python
# Method-based (recommended)
comp = TextComponent("Hello").color("red").bold()

# Dictionary-like access
comp.data["color"] = "blue"
comp.data["italic"] = True
```

### ✅ Backward Compatibility
All existing `Chat` methods continue to work:
```python
# Old methods still work
Chat.pack("simple message")
Chat.unpack(buffer)

# New enhanced methods
Chat.pack(TextComponent("enhanced").color("green"))
Chat.unpack_component(buffer)  # Returns TextComponent
```

## Usage Examples

### Basic Text Components

```python
from proxhy.datatypes import TextComponent, Chat

# Simple text
simple = TextComponent("Hello World!")
print(simple.to_json())  # {"text":"Hello World!","type":"text"}
```

### Formatting

```python
# Chained formatting
formatted = (TextComponent("Important Message")
             .color("red")
             .bold()
             .underlined())

# Multiple components
rainbow = (TextComponent("Rainbow")
           .append(TextComponent(" Text").color("orange"))
           .append(TextComponent(" Message").color("yellow").bold()))
```


### Interactive Components

```py
# Clickable URL
clickable = (TextComponent("Visit Wiki")
             .color("blue")
             .underlined()
             .click_event("open_url", "https://minecraft.wiki")
             .hover_text("Opens Minecraft Wiki"))

# Command suggestion
command_btn = (TextComponent("[Help]")
               .color("green")
               .click_event("suggest_command", "/help")
               .hover_text("Click to run help"))

# Server welcome message
welcome = (TextComponent("[Server] ")
           .color("gray")
           .append(TextComponent("Welcome ").color("yellow"))
           .append(TextComponent("Player123").color("white").bold())
           .append(TextComponent(" to the server!").color("yellow")))

# Achievement notification
achievement = (TextComponent("🏆 ").color("gold")
               .append(TextComponent("Achievement: ").color("yellow"))
               .append(TextComponent("First Diamond")
                       .color("aqua")
                       .bold()
                       .hover_text("Mine your first diamond!")))
```

## Class Structure

### TextComponent

The main class that represents a Minecraft text component:

#### Core Methods
- `__init__(data=None)` - Create from string, dict, list, or None
- `to_json()` - Export to JSON string
- `to_dict()` - Get underlying dictionary
- `copy()` - Create deep copy
- `is_empty()` - Check if component has content


#### Formatting Methods
- `color(color)` - Set text color (hex or name)
- `font(font)` - Set font resource location
- `bold(bool=True)` - Bold formatting
- `italic(bool=True)` - Italic formatting
- `underlined(bool=True)` - Underlined formatting
- `strikethrough(bool=True)` - Strikethrough formatting
- `obfuscated(bool=True)` - Obfuscated formatting
- `shadow_color(color)` - Text shadow color

#### Interactivity Methods
- `insertion(text)` - Shift-click insertion
- `click_event(action, value)` - Click events
- `hover_text(text)` - Hover tooltip with text

#### Child Component Methods
- `append(component)` - Add child component
- `extend(components)` - Add multiple children
- `prepend(component)` - Add child at beginning
- `remove_child(index)` - Remove child by index
- `replace_child(index, component)` - Replace child
- `clear_children()` - Remove all children
- `get_children()` - Get list of child components

### Chat (Enhanced)

Enhanced Chat class with TextComponent support:

#### Static Methods
- `pack(value)` - Pack TextComponent, dict, or string to bytes
- `pack_msg(value)` - Pack with null terminator
- `unpack(buff)` - Unpack to plain text string (legacy)
- `unpack_component(buff)` - Unpack to TextComponent object
- `create(text=None)` - Create new TextComponent
- `translate(key, with_args=None, fallback=None)` - Create translatable component
- `selector(selector, separator=None)` - Create selector component
- `keybind(keybind)` - Create keybind component
- `score(name, objective)` - Create score component
- `from_legacy(legacy_str: str)` - Create a TextComponent from a string color coded with the § symbol


### From Manual JSON Building

```python
old_json = {
    "text": "Click me!",
    "color": "blue",
    "clickEvent": {
        "action": "open_url",
        "value": "https://example.com"
    }
}

new_component = (TextComponent("Click me!")
                 .color("blue")
                 .click_event("open_url", "https://example.com"))

# Both can be used with Chat.pack()
Chat.pack(old_json)      # Still works
Chat.pack(new_component) # Enhanced
```
