"""Server-sent resource pack that ships Proxhy's invisible tab-alignment glyphs.

Instead of injecting font assets into the user's installed resource packs (the
approach moonfish takes), Proxhy builds a tiny resource pack and *serves* it to
the client over a localhost HTTP server. When the client joins the proxy it is
offered this pack via the clientbound Resource Pack Send packet (0x48); once
applied, the private-use codepoints ``U+FFF0`` (1px advance) and ``U+FFF1``
(2px advance) become invisible fixed-width spacers, which the tab-list renderer
uses to pad every column to a pixel-perfect width.

The pack is built from two vanilla 1.8.9 font files bundled under
``assets/font``:

* ``glyph_sizes.bin`` - the 65536-byte glyph advance table. Only the two
  padding codepoints are overridden; every other glyph keeps its vanilla width
  so unicode symbols (stars, etc.) still measure/render correctly.
* ``unicode_page_ff.png`` - page 0xFF of the unicode font. The ``U+FFF0``/
  ``U+FFF1`` tiles are already fully transparent in vanilla (they live in the
  unassigned Specials block), so no image editing is required - a transparent
  tile plus a non-zero advance renders as pure invisible padding.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import zipfile
from importlib.resources import files

logger = logging.getLogger("proxhy")

# Private-use codepoints used as invisible padding glyphs. Must match the values
# in proxhy/tablist.py.
PIXEL_PADDING_CHAR = "￰"
DOUBLE_PIXEL_PADDING_CHAR = "￱"

# glyph_sizes.bin encodes each glyph's advance as one byte: (start << 4) | end,
# where the rendered width is (end + 1 - start) / 2 + 1. See MC 1.8 FontRenderer.
#   0x10 -> start=1,end=0 -> (0 + 1 - 1)/2 + 1 = 1  (1px advance)
#   0x01 -> start=0,end=1 -> (1 + 1 - 0)/2 + 1 = 2  (2px advance)
_GLYPH_ADVANCE_BYTES = {
    ord(PIXEL_PADDING_CHAR): 0x10,
    ord(DOUBLE_PIXEL_PADDING_CHAR): 0x01,
}

PACK_MCMETA = (
    b'{\n  "pack": {\n    "pack_format": 1,\n'
    b'    "description": "Proxhy tab alignment glyphs"\n  }\n}\n'
)
UNICODE_PAGE_MCMETA = b'{"texture":{"blur":false,"clamp":true}}\n'

# A fixed timestamp so the produced zip is byte-for-byte reproducible and the
# client can cache it by hash across restarts.
_ZIP_DATE = (2020, 1, 1, 0, 0, 0)

_PACK_NAME = "proxhy.zip"


def _load_font_asset(name: str) -> bytes:
    with files("assets").joinpath("font", name).open("rb") as f:
        return f.read()


def _build_glyph_sizes() -> bytes:
    data = bytearray(_load_font_asset("glyph_sizes.bin"))
    for codepoint, value in _GLYPH_ADVANCE_BYTES.items():
        if 0 <= codepoint < len(data):
            data[codepoint] = value
    return bytes(data)


def build_pack_bytes() -> bytes:
    """Build the resource pack zip (deterministic bytes)."""
    entries = {
        "pack.mcmeta": PACK_MCMETA,
        "assets/minecraft/font/glyph_sizes.bin": _build_glyph_sizes(),
        "assets/minecraft/textures/font/unicode_page_ff.png": _load_font_asset(
            "unicode_page_ff.png"
        ),
        "assets/minecraft/textures/font/unicode_page_ff.png.mcmeta": UNICODE_PAGE_MCMETA,
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, payload in entries.items():
            info = zipfile.ZipInfo(path, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return buffer.getvalue()


class ResourcePackServer:
    """Process-wide singleton HTTP server that serves the resource pack.

    A single instance is shared by every proxy connection in the process; it is
    started lazily on the running event loop the first time a client needs the
    pack URL.
    """

    _instance: ResourcePackServer | None = None

    def __init__(self) -> None:
        self._pack_bytes = build_pack_bytes()
        self.sha1 = hashlib.sha1(self._pack_bytes).hexdigest()
        self._server: asyncio.Server | None = None
        self._port: int | None = None
        self._start_lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> ResourcePackServer:
        if cls._instance is None:
            cls._instance = ResourcePackServer()
        return cls._instance

    async def ensure_started(self) -> None:
        if self._server is not None:
            return
        async with self._start_lock:
            if self._server is not None:
                return
            server = await asyncio.start_server(self._handle_connection, "127.0.0.1", 0)
            self._server = server
            self._port = server.sockets[0].getsockname()[1]
            logger.info(
                f"Resource pack server listening on 127.0.0.1:{self._port} "
                f"(sha1={self.sha1})"
            )

    async def url(self) -> str:
        await self.ensure_started()
        return f"http://127.0.0.1:{self._port}/{_PACK_NAME}"

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            # Read (and discard) the request line + headers. The client sends a
            # simple GET; we always respond with the pack regardless of path.
            try:
                await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
            except TimeoutError, asyncio.IncompleteReadError:
                pass

            body = self._pack_bytes
            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/zip\r\n"
                f"Content-Length: {len(body)}\r\n"
                'Content-Disposition: attachment; filename="proxhy.zip"\r\n'
                "Connection: close\r\n"
                "\r\n"
            ).encode("ascii")
            writer.write(headers + body)
            await writer.drain()
        except ConnectionResetError, BrokenPipeError, OSError:
            pass
        finally:
            try:
                writer.close()
            except OSError:
                pass
