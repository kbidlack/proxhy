"""Pixel-accurate Minecraft 1.8 text measurement + invisible column padding.

Ported from moonfish's tab-list renderer. Used to pad tab-list columns to a
constant pixel width so they line up into a clean table. Padding is done with
the invisible ``U+FFF0`` (1px advance) glyph shipped by Proxhy's server-sent
resource pack (see :mod:`proxhy.respack`); if the client has not applied that
pack the padding characters simply render as nothing and columns fall back to
being left-aligned but unpadded.
"""

from __future__ import annotations

import math

from proxhy._font_widths import UNICODE_ADVANCES, WIDTHS

# Invisible padding glyphs (private-use codepoints). Must match proxhy/respack.py.
PIXEL_PADDING_CHAR = "￰"  # 1px advance
DOUBLE_PIXEL_PADDING_CHAR = "￱"  # 2px advance

# Advances for our own padding glyphs, mirroring the resource pack.
_PADDING_ADVANCES = {
    PIXEL_PADDING_CHAR: 1,
    DOUBLE_PIXEL_PADDING_CHAR: 2,
}


def get_char_width(char: str) -> int:
    """Bitmap width of a glyph, excluding the 1px inter-character advance."""
    width = WIDTHS.get(char)
    if width is not None:
        return width
    # Unicode font pages default to a 7px glyph; ASCII default font is 5px.
    return 7 if ord(char) > 127 else 5


def get_advance_width(char: str) -> float:
    """Total horizontal advance of a single glyph, in pixels."""
    pad = _PADDING_ADVANCES.get(char)
    if pad is not None:
        return pad
    unicode_advance = UNICODE_ADVANCES.get(char)
    if unicode_advance is not None:
        return unicode_advance
    return get_char_width(char) + 1


def get_string_width(text: str) -> float:
    """Rendered pixel width of a legacy §-formatted string.

    Section-sign color/format codes are not drawn; ``§l`` (bold) adds 1px to
    every subsequent drawn glyph until ``§r`` (matching MC 1.8 FontRenderer:
    color codes do NOT reset bold).
    """
    if not text:
        return 0
    width: float = 0
    bold = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "§" and i + 1 < n:  # § code
            code = text[i + 1].lower()
            if code == "l":
                bold = True
            elif code == "r":
                bold = False
            i += 2
            continue
        advance = get_advance_width(ch)
        width += advance + (1 if bold and advance > 0 else 0)
        i += 1
    return width


def _padding_for(missing: float) -> str:
    """Invisible 1px padding characters covering ``missing`` pixels."""
    if missing <= 0:
        return ""
    return PIXEL_PADDING_CHAR * math.ceil(missing - 1e-9)


def pad_right(text: str, target_width: float) -> str:
    """Append invisible padding so ``text`` occupies ``target_width`` pixels."""
    return text + _padding_for(target_width - get_string_width(text))
