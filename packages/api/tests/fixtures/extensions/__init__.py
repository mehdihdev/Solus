"""Programmatic extension-bundle fixtures (SOLUSDEV-235 / ADR-035).

Nothing binary is committed: every zip, PNG, WebP and SVG used by the
extension validator tests is built in memory by the helpers below, so the
fixtures stay reviewable as text and the tests can mutate them freely.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass

# The community fixtures publish as `bom-lite`: `bom` is a first-party capability id
# (SOLUSDEV-246 ST4) and the publish gate reserves it for Solus staff.
MINIMAL_MANIFEST_TOML = """\
schema_version = 1

[extension]
id = "bom-lite"
name = "BOM"
version = "1.0.0"
publisher = "Ada Lovelace"
summary = "Bill of materials from your EDA project."

[views]
widget = { entry = "widget.html", preferred = "wide" }

[store]
overview = "OVERVIEW.md"
"""

FULL_MANIFEST_TOML = """\
schema_version = 1

[extension]
id = "bom-lite"
name = "BOM"
version = "1.2.0"
publisher = "Ada Lovelace"
summary = "Bill of materials from your EDA project."
requires = [["eda"]]

[views]
widget = { entry = "widget.html", preferred = "wide", minimum = "standard" }
page = { entry = "page.html", icon = "icon.svg", label = "BOM" }
window = { entry = "window.html", title = "BOM", width = 960, height = 640 }

[permissions]
scopes = ["graph.read"]

[store]
overview = "OVERVIEW.md"
privacy_policy = "PRIVACY.md"
screenshots = ["shots/table.png", "shots/finding.webp"]

[[store.sections]]
title = "How it works"
body = "docs/HOW.md"
"""

VALID_ICON_SVG = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">'
    b"<title>BOM</title>"
    b'<g fill="none" stroke="#fff" stroke-width="2">'
    b'<path d="M4 4h16v16H4z" fill="#fff"/>'
    b'<circle cx="12" cy="12" r="3"/>'
    b"</g></svg>"
)

CLEAN_HTML = b'<!doctype html><html><body><script src="app.js"></script></body></html>'
CLEAN_JS = b"window.addEventListener('message', (e) => { console.log(e.data); });"
CLEAN_MD = b"# Overview\n\nA bill of materials for your EDA project.\n"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_bytes(size: int = 64) -> bytes:
    """A byte string carrying the PNG signature, padded to `size` bytes."""
    return (PNG_MAGIC + b"\0" * size)[: max(size, len(PNG_MAGIC))]


def webp_bytes(size: int = 64) -> bytes:
    """A byte string carrying the RIFF/WEBP signature, padded to `size` bytes."""
    payload = b"WEBP" + b"VP8 " + b"\0" * max(size - 12, 0)
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def minimal_files() -> dict[str, bytes]:
    """The smallest valid bundle: manifest, one widget entry, one overview."""
    return {
        "extension.toml": MINIMAL_MANIFEST_TOML.encode(),
        "widget.html": CLEAN_HTML,
        "app.js": CLEAN_JS,
        "OVERVIEW.md": CLEAN_MD,
    }


def full_files() -> dict[str, bytes]:
    """A valid bundle exercising every store-facing reference."""
    return {
        "extension.toml": FULL_MANIFEST_TOML.encode(),
        "widget.html": CLEAN_HTML,
        "page.html": CLEAN_HTML,
        "window.html": CLEAN_HTML,
        "app.js": CLEAN_JS,
        "styles.css": b"body { color: red; }",
        "icon.svg": VALID_ICON_SVG,
        "OVERVIEW.md": CLEAN_MD,
        "PRIVACY.md": b"# Privacy\n\nNothing leaves your machine.\n",
        "docs/HOW.md": b"# How it works\n",
        "shots/table.png": png_bytes(),
        "shots/finding.webp": webp_bytes(),
    }


def build_zip(
    files: Mapping[str, bytes],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    extra: list[tuple[zipfile.ZipInfo, bytes]] | None = None,
) -> bytes:
    """Zip `files` in memory; `extra` appends raw ZipInfo entries (symlinks, odd names)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        for info, data in extra or []:
            zf.writestr(info, data)
    return buf.getvalue()


def symlink_entry(name: str, target: str) -> tuple[zipfile.ZipInfo, bytes]:
    """A zip entry whose Unix mode marks it as a symbolic link."""
    info = zipfile.ZipInfo(name)
    info.external_attr = 0o120777 << 16
    return info, target.encode()


def with_manifest(files: Mapping[str, bytes], toml_text: str) -> dict[str, bytes]:
    return {**files, "extension.toml": toml_text.encode()}


def without(files: Mapping[str, bytes], *names: str) -> dict[str, bytes]:
    return {k: v for k, v in files.items() if k not in names}


# --- hand-rolled archives (zip-bomb shapes the stdlib writer cannot produce) ----
ZIP_DEFLATE_METHOD = 8


@dataclass(frozen=True)
class RawEntry:
    """One member written with EXACTLY these header fields — `file_size`,
    `compress_size` and `crc` may lie about `compressed`."""

    name: str
    compressed: bytes
    file_size: int
    crc: int
    compress_size: int | None = None
    method: int = ZIP_DEFLATE_METHOD

    @property
    def declared_compress_size(self) -> int:
        return len(self.compressed) if self.compress_size is None else self.compress_size


def deflate_raw(data: bytes, level: int = 9) -> bytes:
    """A raw DEFLATE stream (no zlib header) — what a zip member carries."""
    compressor = zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


def raw_entry(name: str, data: bytes, *, file_size: int | None = None) -> RawEntry:
    """A deflated member of `data` whose header optionally UNDERSTATES `file_size`
    (the CRC stays that of the real stream, as a lying archive would ship it)."""
    return RawEntry(
        name=name,
        compressed=deflate_raw(data),
        file_size=len(data) if file_size is None else file_size,
        crc=zlib.crc32(data) & 0xFFFFFFFF,
    )


def raw_zip(entries: list[RawEntry]) -> bytes:
    """Assemble local headers, central directory and EOCD by hand."""
    out = io.BytesIO()
    central: list[bytes] = []
    for entry in entries:
        name = entry.name.encode()
        offset = out.tell()
        fields = (entry.method, 0, 0x21, entry.crc, entry.declared_compress_size, entry.file_size)
        out.write(struct.pack("<4sHHHHHIIIHH", b"PK\x03\x04", 20, 0, *fields, len(name), 0))
        out.write(name)
        out.write(entry.compressed)
        central.append(
            struct.pack(
                "<4sHHHHHHIIIHHHHHII",
                b"PK\x01\x02",
                20,
                20,
                0,
                *fields,
                len(name),
                0,
                0,
                0,
                0,
                0,
                offset,
            )  # fmt: skip
            + name
        )
    cd_offset = out.tell()
    for record in central:
        out.write(record)
    cd_size = out.tell() - cd_offset
    out.write(
        struct.pack(
            "<4sHHHHIIH", b"PK\x05\x06", 0, 0, len(central), len(central), cd_size, cd_offset, 0
        )
    )
    return out.getvalue()
