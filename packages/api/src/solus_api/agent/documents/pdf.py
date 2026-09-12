"""PDF pages → PNG bytes (SOLUSDEV-252 P6), via pypdfium2.

The native library is imported INSIDE `render_pages`: a machine where the wheel
is missing or its shared object refuses to load gets a clear `DocumentError`,
never an import-time crash of the API. Input is capped before anything is
parsed, page count per call is capped, and every page is rendered to one fixed
width so a vision call never receives a poster-sized bitmap.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, NamedTuple

MAX_PDF_BYTES: Final = 40 * 1024 * 1024
MAX_PAGES_PER_CALL: Final = 12
RENDER_WIDTH: Final = 1400
_PDF_MAGIC: Final = b"%PDF-"
_TITLE_CAP: Final = 200


class DocumentError(ValueError):
    """The document could not be read; the message names WHY, never the bytes."""


@dataclass(frozen=True, slots=True)
class PageImage:
    """A dataclass, not a NamedTuple: `index` would shadow `tuple.index`."""

    index: int  # 1-based page number — the number a datasheet cites
    png: bytes
    width: int
    height: int


class Rendered(NamedTuple):
    pages: list[PageImage]
    page_count: int
    title: str | None  # document metadata: untrusted text, capped


def _png(rgb_rows: list[bytes], width: int, height: int) -> bytes:
    """Minimal PNG encoder (8-bit RGB, filter 0) — no imaging dependency."""

    def chunk(tag: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(tag + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + row for row in rgb_rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _render_page(page: Any, index: int, width: int) -> PageImage:
    page_width, _ = page.get_size()
    bitmap = page.render(scale=width / max(page_width, 1.0), rev_byteorder=True)
    try:
        if bitmap.mode != "RGB":
            raise DocumentError(f"unexpected bitmap mode {bitmap.mode}")
        buffer = bytes(bitmap.buffer)
        rows = [
            buffer[y * bitmap.stride : y * bitmap.stride + bitmap.width * 3]
            for y in range(bitmap.height)
        ]
        png = _png(rows, bitmap.width, bitmap.height)
        return PageImage(index, png, bitmap.width, bitmap.height)
    finally:
        bitmap.close()


def _selected(pages: Sequence[int] | None, page_count: int, max_pages: int) -> list[int]:
    wanted = range(1, page_count + 1) if pages is None else pages
    return [n for n in dict.fromkeys(wanted) if 1 <= n <= page_count][:max_pages]


def render_pages(
    pdf_bytes: bytes,
    *,
    pages: Sequence[int] | None = None,
    max_pages: int = MAX_PAGES_PER_CALL,
    width: int = RENDER_WIDTH,
) -> Rendered:
    """Rasterise the selected pages (1-based; `None` = from the start), at most
    `max_pages`, each scaled to `width` px. Out-of-range page numbers are
    dropped silently — the caller reports what was actually read."""
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise DocumentError(f"document exceeds {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not pdf_bytes.startswith(_PDF_MAGIC):
        raise DocumentError("document is not a PDF")
    try:
        # No py.typed marker upstream; the surface used here is typed at the call sites.
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001 — ImportError, or the native lib failing to load
        raise DocumentError(
            f"PDF rendering is unavailable on this machine ({type(exc).__name__})"
        ) from None
    try:
        document = pdfium.PdfDocument(pdf_bytes)
    except pdfium.PdfiumError as exc:
        raise DocumentError("document could not be opened as a PDF") from exc
    try:
        page_count = len(document)
        title = document.get_metadata_value("Title") or None
        rendered = [
            _render_page(document[n - 1], n, width)
            for n in _selected(pages, page_count, min(max_pages, MAX_PAGES_PER_CALL))
        ]
    except pdfium.PdfiumError as exc:
        raise DocumentError(f"page could not be rendered ({type(exc).__name__})") from None
    finally:
        document.close()
    return Rendered(rendered, page_count, title[:_TITLE_CAP] if title else None)


__all__ = [
    "MAX_PAGES_PER_CALL",
    "MAX_PDF_BYTES",
    "RENDER_WIDTH",
    "DocumentError",
    "PageImage",
    "Rendered",
    "render_pages",
]
