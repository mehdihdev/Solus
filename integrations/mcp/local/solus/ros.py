"""Bounded ROS package texts for `scan_folder` (docs/api/local-folder.md §4, SOLUSDEV-321 P6).

One record per ROS package — a directory holding `package.xml` — carrying ONLY the texts the
cloud's ROS reader needs (R135): the manifest, the launch files (`*.launch.py` and
`*.launch.xml` up to MAX_DEPTH levels down, `launch/*.yaml|yml`), the setup files that name its
executables (`setup.py`, `setup.cfg`), and the Python modules of its own module directory
(`<package>/<name>/`, the ament_python layout, where its nodes create their publishers and
subscriptions), each `{parts, text}`, launch and setup files first so a cap keeps them. Nothing
on a hidden or a test path ships, and nothing whose name reads like a credential (`SECRET_NAME`).
The manifest's `<name>` is read (stdlib etree, any DTD refused first, as `deps.py` does) and
nothing is imported or run; the cloud parses the rest once. Every read goes through
`arduino._read` (descriptor-confined, `O_NOFOLLOW`, regular files only), the listing skips links,
skip-listed directories and nested packages, and a cap — files per package, bytes per file,
bytes in all — leaves its package `incomplete` rather than silently short. The part as the frame
encodes it stays within ROS_FRAME_BUDGET_BYTES too: the first package past it keeps its manifest
and the leading files that fit, marked `incomplete`, and the packages after it are dropped, so the
rest of the scan never fails because of `ros`.

A colcon workspace (a `src/<pkg>/package.xml` beside an `install/` or `build/` directory) counts
only the packages under `src/`: `install/` holds a share copy of every manifest and launch file.
"""

import json
import logging
import os
import re
import stat
from pathlib import Path
from typing import Any

from .arduino import _read
from .toolmap import SKIP_DIRS

logger = logging.getLogger("solus.local.ros")

MAX_PACKAGES = 32
MAX_FILES = 32  # per package, its manifest not counted
MAX_FILE_BYTES = 32 * 1024
MAX_TOTAL_BYTES = 256 * 1024
#: The `ros` part's share of the `scan_folder` answer, measured as the companion's frame encodes
#: it (`json.dumps`, ASCII-escaped and compact: `solus_companion/frames.py`), so a character that
#: escapes to `\uXXXX` costs what it costs (P6 fix 1, m9). The cloud refuses a tool_result frame
#: over 1 MiB (`bridge_tool_result_max_bytes`, 1,048,576 B). 2000 file entries
#: (`toolmap.MAX_FILES`) at about 300 B each (a 200-character path) are 600,000 B; with this
#: budget, 262,144 B, that is 862,144 B, which leaves 186,432 B for the dependencies, the
#: sketches, git and the frame's envelope.
ROS_FRAME_BUDGET_BYTES = 256 * 1024
MAX_DEPTH = 3
#: Directory entries one package's listing examines at most.
MAX_LISTED = 4096
MANIFEST = "package.xml"
LAUNCH_SUFFIXES = (".launch.py", ".launch.xml")
YAML_SUFFIXES = (".yaml", ".yml")
#: The entry-point files that name a package's executables (R135).
SETUP_FILES = ("setup.py", "setup.cfg")
COLCON_PRODUCTS = ("install", "build")
#: A path with ANY component that reads like a credential never ships and is never walked,
#: whatever it holds (R135 and its follow-up). Defence in depth: the module-directory allowlist
#: (`_wanted`) is the primary bound.
SECRET_NAME = re.compile(
    r"secret|credential|token|passw|apikey|api_key|private|auth|id_rsa|id_ed25519"
    r"|\.env|\.pem|\.key|\.p12|\.pfx",
    re.IGNORECASE,
)
#: A path through one of these components is a test, never a fact about the running graph.
TEST_DIRS = frozenset({"test", "tests"})
#: The ROS package-name rule, as `deps.py` and the cloud's manifest parser hold it.
_ROS_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _shippable(parts: list[str]) -> bool:
    """No hidden, test or credential-shaped component anywhere on the path (R135): a directory
    that fails is never walked into, and a file that fails never ships."""
    return not any(
        part.startswith(".") or part.lower() in TEST_DIRS or SECRET_NAME.search(part)
        for part in parts
        if part
    )


def _manifest_name(text: str) -> str | None:
    """The `<name>` of a manifest the caller already refused a DTD for (`deps.py`'s guard): it
    names the package's own module directory, the only one whose modules ship."""
    from xml.etree.ElementTree import fromstring  # noqa: S405 — DTDs refused by the caller

    try:
        root = fromstring(text)  # noqa: S314 — DTDs refused by the caller
    except Exception:  # noqa: BLE001 - a hostile manifest names nothing, never a crash
        return None
    name = (root.findtext("name") or "").strip() if root.tag == "package" else ""
    return name if _ROS_NAME.match(name) else None


def _regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _real_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def is_colcon(root: Path) -> bool:
    """A colcon workspace: a `src/<pkg>/package.xml`, and `install/` or `build/` beside `src/`."""
    src = root / "src"
    if not _real_dir(src):
        return False
    try:
        children = sorted(os.scandir(src), key=lambda entry: entry.name)[:256]
    except OSError:
        return False
    packaged = any(
        entry.is_dir(follow_symlinks=False) and _regular(Path(entry.path) / MANIFEST)
        for entry in children
    )
    return packaged and any(_real_dir(root / name) for name in COLCON_PRODUCTS)


def _launch_like(rel: list[str]) -> bool:
    """A launch file or a setup file: shipped before the package's modules."""
    name = rel[-1].lower()
    if name.endswith(LAUNCH_SUFFIXES) or (len(rel) == 1 and name in SETUP_FILES):
        return True
    return len(rel) == 2 and rel[0] == "launch" and name.endswith(YAML_SUFFIXES)


def _wanted(rel: list[str], module_dir: str | None) -> bool:
    """What the reader needs and nothing more (R135): the launch and setup files, and the Python
    modules of the package's own module directory (`<package>/<name>/`, the ament_python layout,
    where its nodes create their publishers and subscriptions)."""
    if not _shippable(rel):
        return False
    own_module = module_dir is not None and len(rel) > 1 and rel[0] == module_dir
    return _launch_like(rel) or (own_module and rel[-1].lower().endswith(".py"))


def _walks_into(entry: os.DirEntry[str], rel: list[str]) -> bool:
    """Whether the listing walks into this directory: not a link, not skipped, hidden or a test,
    within the depth, and not a nested package (that one is its own record)."""
    return (
        entry.is_dir(follow_symlinks=False)
        and entry.name not in SKIP_DIRS
        and _shippable([*rel, ""])
        and len(rel) < MAX_DEPTH
        and not _regular(Path(entry.path) / MANIFEST)
    )


def _ordered(found: list[list[str]]) -> list[list[str]]:
    return sorted(found, key=lambda rel: (not _launch_like(rel), rel))


def _package_files(directory: Path, module_dir: str | None) -> tuple[list[list[str]], bool]:
    """The package's wanted files, relative to it, launch and setup files first; True when the
    listing stopped at MAX_LISTED."""
    found: list[list[str]] = []
    pending: list[list[str]] = [[]]
    examined = 0
    while pending:
        rel_dir = pending.pop()
        try:
            entries = sorted(os.scandir(directory.joinpath(*rel_dir)), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            examined += 1
            if examined > MAX_LISTED:
                return _ordered(found), True
            rel = [*rel_dir, entry.name]
            if _walks_into(entry, rel):
                pending.append(rel)
            elif entry.is_file(follow_symlinks=False) and _wanted(rel, module_dir):
                found.append(rel)
    return _ordered(found), False


def _read_bounded_text(root: Path, parts: list[str]) -> str | None:
    """The file's text when it is a regular file of at most MAX_FILE_BYTES, else None."""
    try:
        text = _read(root, parts)
    except (OSError, ValueError, UnicodeError):
        return None
    return text if len(text.encode("utf-8")) <= MAX_FILE_BYTES else None


def _package(root: Path, manifest: list[str], budget: list[int]) -> dict[str, Any] | None:
    """One package's record, spending `budget[0]` bytes at most; None when its manifest cannot
    be shipped (unreadable, oversized, over the budget, declaring a DTD, or on a hidden or test
    path)."""
    text = _read_bounded_text(root, manifest) if _shippable(manifest) else None
    if text is None or "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    if len(text.encode("utf-8")) > budget[0]:
        return None
    budget[0] -= len(text.encode("utf-8"))
    directory = manifest[:-1]
    listed, incomplete = _package_files(root.joinpath(*directory), _manifest_name(text))
    files: list[dict[str, Any]] = []
    for rel in listed:
        content = _read_bounded_text(root, [*directory, *rel])
        size = len(content.encode("utf-8")) if content is not None else 0
        if content is None or len(files) == MAX_FILES or size > budget[0]:
            incomplete = True
            continue
        budget[0] -= size
        files.append({"parts": [*directory, *rel], "text": content})
    return {"manifest": {"parts": manifest, "text": text}, "files": files, "incomplete": incomplete}


def collect_ros_packages(root: Path, manifests: list[list[str]]) -> list[dict[str, Any]]:
    """One record per ROS package among the scan's manifests (their parts), at most MAX_PACKAGES
    within MAX_TOTAL_BYTES, and as encoded within ROS_FRAME_BUDGET_BYTES. Never raises: a
    package that cannot be read is left out."""
    found = sorted(parts for parts in manifests if parts and parts[-1].lower() == MANIFEST)
    if is_colcon(root):
        found = [parts for parts in found if parts[0] == "src"]
    if len(found) > MAX_PACKAGES:
        logger.warning("ros packages capped at %d of %d", MAX_PACKAGES, len(found))
    budget = [MAX_TOTAL_BYTES]
    packages: list[dict[str, Any]] = []
    for parts in found[:MAX_PACKAGES]:
        package = _package(root, parts, budget)
        if package is not None:
            packages.append(package)
    return _fit_frame(packages)


def _encoded(value: Any) -> int:
    """What `value` costs in the frame: its ASCII-escaped, compact JSON."""
    return len(json.dumps(value, separators=(",", ":")))


def _fit_frame(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`packages`, in order, within ROS_FRAME_BUDGET_BYTES as the frame encodes them. The first
    that does not fit keeps its manifest and the leading files that do (launch and setup files
    lead), marked `incomplete`, and the packages after it are dropped. Each text is measured
    once."""
    kept: list[dict[str, Any]] = []
    room = ROS_FRAME_BUDGET_BYTES - 2  # the list's brackets
    for package in packages:
        size = _encoded(package) + 1  # and its comma
        if size <= room:
            kept.append(package)
            room -= size
            continue
        cut = _cut(package, room)
        if cut is not None:
            kept.append(cut)
        elif kept:  # not even its manifest fits: the last kept one says the part was cut
            kept[-1] = {**kept[-1], "incomplete": True}
        logger.warning("ros part cut at its frame budget after %d packages", len(kept))
        break
    return kept


def _cut(package: dict[str, Any], room: int) -> dict[str, Any] | None:
    """`package` as its manifest and the leading files that fit in `room`, marked `incomplete`;
    None when not even its manifest fits."""
    files: list[dict[str, Any]] = []
    spent = _encoded({**package, "files": [], "incomplete": True}) + 1
    for item in package["files"]:
        size = _encoded(item) + 1
        if spent + size > room:
            break
        files.append(item)
        spent += size
    return {**package, "files": files, "incomplete": True} if spent <= room else None
