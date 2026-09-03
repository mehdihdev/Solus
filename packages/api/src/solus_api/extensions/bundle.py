"""The pure extension-bundle validator (SOLUSDEV-235 / ADR-035 §5).

``inspect_bundle(zip_bytes)`` is everything the ARQ review job (and a future
CLI) needs to decide whether a published version may become visible: zip
structure and zip-bomb guards, path safety, the suffix allowlist, the root
``extension.toml``, every file the manifest references (present, capped,
correctly typed), the reduced icon, and the static content checks. Bytes in,
report out — nothing is written to disk and no member is ever executed.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, field

from solus_contracts.extension_manifest import (
    EXTENSION_MANIFEST_FILENAME,
    LIMITS,
    ExtensionManifest,
    is_safe_bundle_path,
)

from solus_api.extensions.checks import static_checks
from solus_api.extensions.manifest import load_manifest, manifest_text_problems
from solus_api.extensions.svg import svg_problems

ALLOWED_SUFFIXES: tuple[str, ...] = (
    ".html", ".js", ".css", ".json", ".svg", ".png", ".webp", ".woff2", ".md", ".toml",
)  # fmt: skip
MAX_ENTRIES = 2000
MAX_COMPRESSION_RATIO = 100
#: Below this the ratio is meaningless (a 2 KiB JSON of repeated keys deflates
#: past 100:1); the total-uncompressed cap still bounds every such entry.
RATIO_FLOOR_BYTES = 16 * 1024
MAX_ENTRY_BYTES = LIMITS.bundle_bytes
_ZIP_MAGIC = b"PK"
_READ_CHUNK_BYTES = 64 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_TEXT_SUFFIXES = (".html", ".js", ".md")
_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webp": "image/webp",
}


class BundleError(ValueError):
    """A member could not be read safely (missing, unsafe path, over cap, not a zip)."""


@dataclass(frozen=True)
class BundleAsset:
    """A store-facing file the review job extracts once the bundle is accepted."""

    path: str
    media_type: str
    size_bytes: int


@dataclass(frozen=True)
class BundleReport:
    ok: bool
    problems: list[str]
    manifest: ExtensionManifest | None
    content_hash: str
    size_bytes: int
    assets: list[BundleAsset] = field(default_factory=list)


@dataclass(frozen=True)
class _Ref:
    """One manifest → file reference with the cap and media type that govern it."""

    field: str
    path: str
    max_bytes: int
    media_type: str | None  # None: not a store asset (view entries)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _entry_name_problem(name: str) -> str | None:
    if name.startswith("/"):
        return f"{name}: absolute paths are not allowed"
    if "\\" in name:
        return f"{name}: backslashes are not allowed in paths"
    segments = name.rstrip("/").split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        return f"{name}: path traversal or empty segment"
    if name.endswith("/"):
        return None
    if not any(name.lower().endswith(s) for s in ALLOWED_SUFFIXES):
        return f"{name}: not an allowed file type ({', '.join(ALLOWED_SUFFIXES)})"
    if not is_safe_bundle_path(name, ALLOWED_SUFFIXES):
        return f"{name}: path is not a safe bundle path (characters or length)"
    return None


def _entry_problems(info: zipfile.ZipInfo, seen: set[str]) -> list[str]:
    name = info.filename
    problems = [p for p in (_entry_name_problem(name),) if p is not None]
    if _is_symlink(info):
        problems.append(f"{name}: symlink entries are not allowed")
    if info.flag_bits & 0x1:
        problems.append(f"{name}: encrypted entries are not allowed")
    if name.lower() in seen:
        problems.append(f"{name}: duplicate entry (case-insensitive)")
    seen.add(name.lower())
    if info.file_size > MAX_ENTRY_BYTES:
        problems.append(f"{name}: uncompressed size {info.file_size} exceeds {MAX_ENTRY_BYTES}")
    if info.file_size > RATIO_FLOOR_BYTES and (
        info.compress_size == 0 or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
    ):
        problems.append(f"{name}: compression ratio exceeds {MAX_COMPRESSION_RATIO}:1")
    return problems


def _structure_problems(zf: zipfile.ZipFile) -> list[str]:
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        return [f"bundle has {len(infos)} entries; the maximum is {MAX_ENTRIES}"]
    seen: set[str] = set()
    problems: list[str] = []
    for info in infos:
        problems.extend(_entry_problems(info, seen))
    total = sum(info.file_size for info in infos)
    if total > LIMITS.bundle_bytes:
        problems.append(f"total uncompressed size {total} exceeds {LIMITS.bundle_bytes}")
    return problems


def _read_bounded(zf: zipfile.ZipFile, name: str, max_bytes: int) -> bytes:
    """Stream a member, aborting the instant the running total exceeds `max_bytes`
    (the header's file_size can lie; the bytes cannot)."""
    chunks: list[bytes] = []
    total = 0
    with zf.open(name) as fh:
        while chunk := fh.read(_READ_CHUNK_BYTES):
            total += len(chunk)
            if total > max_bytes:
                raise BundleError(f"{name}: exceeds {max_bytes} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


def _manifest_problem(names: set[str]) -> str:
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    for top in sorted(tops):
        if f"{top}/{EXTENSION_MANIFEST_FILENAME}" in names:
            return (
                f"{EXTENSION_MANIFEST_FILENAME}: must be at the bundle root, "
                f"found inside '{top}/' — zip the folder's contents, not the folder"
            )
    return f"{EXTENSION_MANIFEST_FILENAME}: missing from the bundle root"


def _references(manifest: ExtensionManifest) -> list[_Ref]:
    refs: list[_Ref] = []
    for kind in ("widget", "page", "window"):
        view = getattr(manifest.views, kind)
        if view is not None:
            refs.append(_Ref(f"views.{kind}.entry", view.entry, MAX_ENTRY_BYTES, None))
    if manifest.views.page is not None:
        refs.append(
            _Ref("views.page.icon", manifest.views.page.icon, LIMITS.icon_bytes, "image/svg+xml")
        )
    store = manifest.store
    refs.append(_Ref("store.overview", store.overview, LIMITS.overview_bytes, "text/markdown"))
    if store.privacy_policy is not None:
        refs.append(
            _Ref(
                "store.privacy_policy", store.privacy_policy, LIMITS.overview_bytes, "text/markdown"
            )
        )
    for i, section in enumerate(store.sections):
        refs.append(
            _Ref(f"store.sections.{i}.body", section.body, LIMITS.section_bytes, "text/markdown")
        )
    for i, shot in enumerate(store.screenshots):
        media = _MEDIA_TYPES[".png" if shot.lower().endswith(".png") else ".webp"]
        refs.append(_Ref(f"store.screenshots.{i}", shot, LIMITS.screenshot_bytes, media))
    return refs


def _content_problems(ref: _Ref, data: bytes) -> list[str]:
    if ref.media_type == "image/png" and not data.startswith(_PNG_MAGIC):
        return [f"{ref.path}: not a PNG image (signature mismatch)"]
    if ref.media_type == "image/webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return [f"{ref.path}: not a WebP image (signature mismatch)"]
    if ref.media_type == "image/svg+xml":
        return [f"{ref.path}: {p}" for p in svg_problems(data, ref.max_bytes)]
    return []


def _reference_problems(
    zf: zipfile.ZipFile, manifest: ExtensionManifest, names: set[str]
) -> tuple[list[str], list[BundleAsset]]:
    problems: list[str] = []
    assets: list[BundleAsset] = []
    for ref in _references(manifest):
        if ref.path not in names:
            problems.append(f"{ref.field}: references {ref.path}, which is not in the bundle")
            continue
        try:
            data = _read_bounded(zf, ref.path, ref.max_bytes)
        except BundleError as exc:
            problems.append(str(exc))
            continue
        problems.extend(_content_problems(ref, data))
        if ref.media_type is not None:
            assets.append(BundleAsset(ref.path, ref.media_type, len(data)))
    return problems, assets


def _text_members(zf: zipfile.ZipFile, names: set[str]) -> tuple[dict[str, bytes], list[str]]:
    files: dict[str, bytes] = {}
    problems: list[str] = []
    for name in sorted(n for n in names if n.lower().endswith(_TEXT_SUFFIXES)):
        try:
            files[name] = _read_bounded(zf, name, MAX_ENTRY_BYTES)
        except BundleError as exc:
            problems.append(str(exc))
    return files, problems


def _inspect(zf: zipfile.ZipFile) -> tuple[list[str], ExtensionManifest | None, list[BundleAsset]]:
    problems = _structure_problems(zf)
    if problems:
        return problems, None, []
    names = {info.filename for info in zf.infolist()}
    if EXTENSION_MANIFEST_FILENAME not in names:
        return [_manifest_problem(names)], None, []
    try:
        text = _read_bounded(zf, EXTENSION_MANIFEST_FILENAME, MAX_ENTRY_BYTES).decode("utf-8")
    except UnicodeDecodeError:
        return [f"{EXTENSION_MANIFEST_FILENAME}: not valid UTF-8 text"], None, []
    if manifest_problems := manifest_text_problems(text):
        return manifest_problems, None, []
    manifest = load_manifest(text)
    problems, assets = _reference_problems(zf, manifest, names)
    files, read_problems = _text_members(zf, names)
    problems.extend(read_problems)
    problems.extend(static_checks(manifest, files))
    return problems, manifest, assets


def inspect_bundle(data: bytes) -> BundleReport:
    """Validate a whole bundle from its zip bytes; never raises on bad input."""
    digest = hashlib.sha256(data).hexdigest()
    size = len(data)
    if size > LIMITS.bundle_bytes:
        problem = f"bundle size {size} exceeds {LIMITS.bundle_bytes} bytes"
        return BundleReport(False, [problem], None, digest, size)
    if not data.startswith(_ZIP_MAGIC):
        return BundleReport(False, ["not a zip archive"], None, digest, size)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            problems, manifest, assets = _inspect(zf)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError) as exc:
        return BundleReport(False, [f"not a readable zip archive: {exc}"], None, digest, size)
    return BundleReport(not problems, problems, manifest, digest, size, assets)


def read_member(data: bytes, path: str, *, max_bytes: int = MAX_ENTRY_BYTES) -> bytes:
    """Bounded read of one member of an already-inspected bundle (the review job
    extracts store assets with this); :class:`BundleError` on anything unsafe."""
    if not is_safe_bundle_path(path, ALLOWED_SUFFIXES):
        raise BundleError(f"{path}: not a safe bundle path")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if path not in zf.namelist():
                raise BundleError(f"{path}: not in the bundle")
            return _read_bounded(zf, path, max_bytes)
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        raise BundleError(f"not a readable zip archive: {exc}") from exc
