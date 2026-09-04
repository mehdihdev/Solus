"""The pure extension-bundle validator (SOLUSDEV-235 / ADR-035 §5).

Two inspectors over the same zip bytes, sharing every guard:

* :func:`inspect_bundle_structure` — the REQUEST-PATH gate (publish route).
  Zip guards, the root ``extension.toml`` (the ONLY member it inflates, ≤ 64
  KiB), manifest parse, and reference presence / size checks from the central
  directory's header sizes alone. Cheap and bounded by construction.
* :func:`inspect_bundle` — the FULL review (ARQ job, future CLI): all of the
  above plus every text member (≤ 512 KiB each), icon / screenshot sniffing
  and the static checks.

Every member read draws on ONE cumulative decompression budget for the whole
inspection (Phase 4 H1): the moment it is spent the inspection aborts with a
single problem, so a lying archive can never turn a 25 MiB upload into
gigabytes of CPU. Bytes in, report out — nothing is written to disk and no
member is ever executed.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Callable
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
#: Entries at or under this size are exempt from the ratio guard: DEFLATE's
#: fixed overhead makes a tiny member's ratio meaningless, and the total cap
#: bounds it regardless. Phase 4 H1: this was 16 KiB — room enough to hide a
#: bomb-shaped member — so every entry above 1 KiB is now checked.
RATIO_FLOOR_BYTES = 1024
#: Header-level ceiling on any single entry.
MAX_ENTRY_BYTES = LIMITS.bundle_bytes
#: Any single member the FULL inspection inflates (view entries, text members).
MAX_TEXT_MEMBER_BYTES = 512 * 1024
#: The root manifest — the only member the request path ever inflates.
MAX_MANIFEST_BYTES = 64 * 1024
#: Cumulative decompressed bytes ONE inspection may produce across every read.
INFLATE_BUDGET_BYTES = LIMITS.bundle_bytes
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


class InflationBudgetError(BundleError):
    """The inspection's cumulative decompression budget is spent — abort everything."""


class _InflationBudget:
    """Mutable by necessity: one counter shared by every read of one inspection."""

    __slots__ = ("limit", "remaining")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.remaining = limit

    def draw(self, size: int) -> None:
        self.remaining -= size
        if self.remaining < 0:
            raise InflationBudgetError(
                f"bundle: decompressed more than {self.limit} bytes in total; inspection aborted"
            )


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

    @property
    def is_text(self) -> bool:
        return self.path.lower().endswith(_TEXT_SUFFIXES)


@dataclass(frozen=True)
class _Structure:
    """What the header-only pass learned; `infos` is empty when it stopped early."""

    problems: list[str]
    manifest: ExtensionManifest | None
    infos: dict[str, zipfile.ZipInfo]


_Stage = Callable[[zipfile.ZipFile, _InflationBudget], tuple[_Structure, list[BundleAsset]]]


# ---------------------------------------------------------------- zip guards
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


def _ratio_exceeded(info: zipfile.ZipInfo) -> bool:
    """Header sizes only (they may lie; the budget catches that). Every entry
    above the floor is checked — a zero `compress_size` with a non-trivial
    `file_size` is a bomb-shaped header by definition."""
    if info.file_size <= RATIO_FLOOR_BYTES:
        return False
    return info.file_size > MAX_COMPRESSION_RATIO * max(info.compress_size, 1)


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
    if _ratio_exceeded(info):
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


def _read_bounded(
    zf: zipfile.ZipFile, name: str, max_bytes: int, budget: _InflationBudget
) -> bytes:
    """Stream a member, aborting the instant the running total exceeds `max_bytes`
    (the header's file_size can lie; the bytes cannot) or the inspection's
    cumulative budget is spent. Never asks the inflater for more than the cap
    can still admit."""
    chunks: list[bytes] = []
    total = 0
    with zf.open(name) as fh:
        while chunk := fh.read(min(_READ_CHUNK_BYTES, max_bytes - total + 1)):
            total += len(chunk)
            budget.draw(len(chunk))
            if total > max_bytes:
                raise BundleError(f"{name}: exceeds {max_bytes} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


# ------------------------------------------------------------- the manifest
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
            refs.append(_Ref(f"views.{kind}.entry", view.entry, MAX_TEXT_MEMBER_BYTES, None))
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


def _reference_header_problems(
    manifest: ExtensionManifest, infos: dict[str, zipfile.ZipInfo]
) -> list[str]:
    """Presence and declared size of every referenced file — no inflation."""
    problems: list[str] = []
    for ref in _references(manifest):
        info = infos.get(ref.path)
        if info is None:
            problems.append(f"{ref.field}: references {ref.path}, which is not in the bundle")
        elif info.file_size > ref.max_bytes:
            problems.append(f"{ref.path}: exceeds {ref.max_bytes} bytes")
    return problems


def _structure_stage(zf: zipfile.ZipFile, budget: _InflationBudget) -> _Structure:
    problems = _structure_problems(zf)
    if problems:
        return _Structure(problems, None, {})
    infos = {info.filename: info for info in zf.infolist()}
    if EXTENSION_MANIFEST_FILENAME not in infos:
        return _Structure([_manifest_problem(set(infos))], None, {})
    try:
        raw = _read_bounded(zf, EXTENSION_MANIFEST_FILENAME, MAX_MANIFEST_BYTES, budget)
        text = raw.decode("utf-8")
    except InflationBudgetError:
        raise
    except BundleError as exc:
        return _Structure([str(exc)], None, {})
    except UnicodeDecodeError:
        return _Structure([f"{EXTENSION_MANIFEST_FILENAME}: not valid UTF-8 text"], None, {})
    if manifest_problems := manifest_text_problems(text):
        return _Structure(manifest_problems, None, {})
    manifest = load_manifest(text)
    return _Structure(_reference_header_problems(manifest, infos), manifest, infos)


# ---------------------------------------------------------- content (review)
def _content_problems(ref: _Ref, data: bytes) -> list[str]:
    if ref.media_type == "image/png" and not data.startswith(_PNG_MAGIC):
        return [f"{ref.path}: not a PNG image (signature mismatch)"]
    if ref.media_type == "image/webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return [f"{ref.path}: not a WebP image (signature mismatch)"]
    if ref.media_type == "image/svg+xml":
        return [f"{ref.path}: {p}" for p in svg_problems(data, ref.max_bytes)]
    return []


def _text_members(
    zf: zipfile.ZipFile, infos: dict[str, zipfile.ZipInfo], budget: _InflationBudget
) -> tuple[dict[str, bytes], list[str]]:
    """Every text member, read ONCE (≤ 512 KiB each); the references below
    reuse these bytes rather than inflating a member twice."""
    files: dict[str, bytes] = {}
    problems: list[str] = []
    for name in sorted(n for n in infos if n.lower().endswith(_TEXT_SUFFIXES)):
        try:
            files[name] = _read_bounded(zf, name, MAX_TEXT_MEMBER_BYTES, budget)
        except InflationBudgetError:
            raise
        except BundleError as exc:
            problems.append(str(exc))
    return files, problems


def _referenced_bytes(
    zf: zipfile.ZipFile, ref: _Ref, files: dict[str, bytes], budget: _InflationBudget
) -> bytes | None:
    """The bytes of one present, header-sized reference — from the text-member
    cache when it is text (its own read problem is already reported), else a
    bounded read. None when there is nothing further to check."""
    if ref.is_text:
        data = files.get(ref.path)
        if data is not None and len(data) > ref.max_bytes:
            raise BundleError(f"{ref.path}: exceeds {ref.max_bytes} bytes")
        return data
    return _read_bounded(zf, ref.path, ref.max_bytes, budget)


def _reference_problems(
    zf: zipfile.ZipFile,
    manifest: ExtensionManifest,
    infos: dict[str, zipfile.ZipInfo],
    files: dict[str, bytes],
    budget: _InflationBudget,
) -> tuple[list[str], list[BundleAsset]]:
    problems: list[str] = []
    assets: list[BundleAsset] = []
    for ref in _references(manifest):
        info = infos.get(ref.path)
        if info is None or info.file_size > ref.max_bytes:
            continue  # already reported by the structure stage
        try:
            data = _referenced_bytes(zf, ref, files, budget)
        except InflationBudgetError:
            raise
        except BundleError as exc:
            problems.append(str(exc))
            continue
        if data is None:
            continue
        problems.extend(_content_problems(ref, data))
        if ref.media_type is not None:
            assets.append(BundleAsset(ref.path, ref.media_type, len(data)))
    return problems, assets


def _full_stage(
    zf: zipfile.ZipFile, budget: _InflationBudget
) -> tuple[_Structure, list[BundleAsset]]:
    structure = _structure_stage(zf, budget)
    if structure.manifest is None:
        return structure, []
    files, problems = _text_members(zf, structure.infos, budget)
    ref_problems, assets = _reference_problems(
        zf, structure.manifest, structure.infos, files, budget
    )
    problems.extend(ref_problems)
    problems.extend(static_checks(structure.manifest, files))
    return _Structure(structure.problems + problems, structure.manifest, structure.infos), assets


def _structure_only(
    zf: zipfile.ZipFile, budget: _InflationBudget
) -> tuple[_Structure, list[BundleAsset]]:
    return _structure_stage(zf, budget), []


# ------------------------------------------------------------- entry points
def _inspect(data: bytes, stage: _Stage) -> BundleReport:
    digest = hashlib.sha256(data).hexdigest()
    size = len(data)
    if size > LIMITS.bundle_bytes:
        problem = f"bundle size {size} exceeds {LIMITS.bundle_bytes} bytes"
        return BundleReport(False, [problem], None, digest, size)
    if not data.startswith(_ZIP_MAGIC):
        return BundleReport(False, ["not a zip archive"], None, digest, size)
    budget = _InflationBudget(INFLATE_BUDGET_BYTES)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            structure, assets = stage(zf, budget)
    except InflationBudgetError as exc:
        return BundleReport(False, [str(exc)], None, digest, size)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError) as exc:
        return BundleReport(False, [f"not a readable zip archive: {exc}"], None, digest, size)
    problems = structure.problems
    return BundleReport(not problems, problems, structure.manifest, digest, size, assets)


def inspect_bundle_structure(data: bytes) -> BundleReport:
    """The request-path inspection: zip guards, the root manifest (the only
    member inflated, ≤ 64 KiB), and reference presence/size from header sizes
    alone. `assets` is always empty — sizes come from the review's real reads.
    Never raises on bad input."""
    return _inspect(data, _structure_only)


def inspect_bundle(data: bytes) -> BundleReport:
    """Validate a whole bundle from its zip bytes (the review job); never raises
    on bad input."""
    return _inspect(data, _full_stage)


def read_member(data: bytes, path: str, *, max_bytes: int = MAX_ENTRY_BYTES) -> bytes:
    """Bounded read of one member of an already-inspected bundle (the review job
    extracts store assets with this); :class:`BundleError` on anything unsafe."""
    if not is_safe_bundle_path(path, ALLOWED_SUFFIXES):
        raise BundleError(f"{path}: not a safe bundle path")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if path not in zf.namelist():
                raise BundleError(f"{path}: not in the bundle")
            return _read_bounded(zf, path, max_bytes, _InflationBudget(INFLATE_BUDGET_BYTES))
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        raise BundleError(f"not a readable zip archive: {exc}") from exc
