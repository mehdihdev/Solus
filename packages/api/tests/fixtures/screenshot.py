"""A tiny, valid PNG built in-process (SOLUSDEV-252 S3) — no binary fixture
to review, and every suite that needs a screenshot shares one shape."""

from __future__ import annotations

import base64
import struct
import zlib

from solus_api.agent.screen import ScreenshotBlock, ScreenshotSource, decode_screenshot

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


def _chunk(tag: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(tag + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", crc)


def tiny_png(width: int = 2, height: int = 2) -> bytes:
    """An 8-bit RGB PNG of solid red, `width` x `height`."""
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        PNG_MAGIC
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(rows))
        + _chunk(b"IEND", b"")
    )


def tiny_jpeg(width: int = 2, height: int = 2) -> bytes:
    """The smallest JPEG header a dims parser must accept: SOI, an APP0 segment,
    a baseline SOF0 carrying `height` x `width`, EOI. Not decodable — a header."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHH", 11, 8, height, width) + b"\x01\x01\x11\x00"
    return JPEG_MAGIC[:2] + app0 + sof0 + b"\xff\xd9"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def screenshot_body(
    data: bytes | None = None,
    *,
    media_type: str = "image/png",
    width: int | None = 2,
    height: int | None = 2,
    source: dict[str, str] | None = None,
    context: bytes | None = None,
) -> dict[str, object]:
    """The `MessageCreate.screenshot` request shape. `context` (the downscaled
    surrounding screen, sol-window.md §8) rides only when given."""
    body: dict[str, object] = {
        "media_type": media_type,
        "data": b64(tiny_png() if data is None else data),
        "width": width,
        "height": height,
        "source": {"app": "Onshape", "title": "bracket v3"} if source is None else source,
    }
    if context is not None:
        body["context"] = b64(context)
    return {k: v for k, v in body.items() if v is not None}


def context_png() -> bytes:
    """The context image: a different PNG from the crop, so a test can tell them apart."""
    return tiny_png(4, 3)


def screenshot_block(*, with_context: bool = False) -> ScreenshotBlock:
    """A decoded screenshot the way the route hands it to the runner."""
    return decode_screenshot(
        media_type="image/png",
        data=b64(tiny_png()),
        width=2,
        height=2,
        source=ScreenshotSource(app="Onshape", title="bracket v3"),
        context=b64(context_png()) if with_context else None,
    )
