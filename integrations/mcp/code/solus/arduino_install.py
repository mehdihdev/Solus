"""Pinned archive download, validation and private toolchain publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any

from .arduino_manifest import (
    ARCHIVES,
    CLI_SHA256,
    REVIEWED_LINKS,
    Archive,
    canonical_bytes,
    empty_library_index,
    frozen_package_index,
    manifest_sha256,
)
from .arduino_process import check_deadline, closed_environment, run_bounded, sandbox_argv
from .arduino_toolchain import ArduinoError

_DIRECTORY_FDS: ContextVar[frozenset[int]] = ContextVar(
    "arduino_owned_directories", default=frozenset()
)

MAX_FILES = 100_000
MAX_TREE_BYTES = 2 * 1024**3
MAX_ARCHIVE_BYTES = 128 * 1024**2


@dataclass(frozen=True, slots=True)
class Entry:
    kind: str
    size: int = 0
    sha256: str = ""
    mode: int = 0
    target: str = ""


def open_directory(path: Path) -> int:
    if not path.is_absolute():
        raise ArduinoError("integrity_mismatch")
    parts = path.parts[1:]
    if parts[:3] == ("proc", "self", "fd") and len(parts) >= 4 and parts[3].isdecimal():
        descriptor_number = int(parts[3])
        if descriptor_number not in _DIRECTORY_FDS.get():
            raise ArduinoError("integrity_mismatch")
        descriptor = os.dup(descriptor_number)
        parts = parts[4:]
    else:
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_fd
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def held_descriptor(descriptor: int) -> Iterator[tuple[Path, int]]:
    """Make an owned directory descriptor an internal-only stable path anchor."""
    token = _DIRECTORY_FDS.set(_DIRECTORY_FDS.get() | {descriptor})
    try:
        yield Path(f"/proc/self/fd/{descriptor}"), descriptor
    finally:
        _DIRECTORY_FDS.reset(token)
        os.close(descriptor)


@contextmanager
def held_directory(path: Path) -> Iterator[tuple[Path, int]]:
    with held_descriptor(open_directory(path)) as handle:
        yield handle


@contextmanager
def regular_file(path: Path) -> Iterator[IO[bytes]]:
    directory = open_directory(path.parent)
    try:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ArduinoError("integrity_mismatch")
        yield source


def read_bounded(path: Path, cap: int) -> bytes:
    try:
        with regular_file(path) as source:
            before = os.fstat(source.fileno())
            if before.st_size > cap:
                raise ArduinoError("resource_limit")
            value = source.read(cap + 1)
            after = os.fstat(source.fileno())
            if len(value) > cap or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ArduinoError("integrity_mismatch")
            return value
    except OSError:
        raise ArduinoError("integrity_mismatch") from None


def digest_file(path: Path, size: int, deadline: float) -> str:
    try:
        with regular_file(path) as source:
            if os.fstat(source.fileno()).st_size != size:
                raise ArduinoError("integrity_mismatch")
            result = _hash_stream(source, size, deadline)
            if os.fstat(source.fileno()).st_size != size:
                raise ArduinoError("integrity_mismatch")
            return result
    except OSError:
        raise ArduinoError("integrity_mismatch") from None


def _hash_stream(source: IO[bytes], size: int, deadline: float) -> str:
    total, digest = 0, hashlib.sha256()
    while True:
        check_deadline(deadline)
        chunk = source.read(min(1024 * 1024, size + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > size:
            raise ArduinoError("integrity_mismatch")
        digest.update(chunk)
    if total != size:
        raise ArduinoError("integrity_mismatch")
    return digest.hexdigest()


def _member_path(name: str) -> str:
    if not name or name.startswith("/") or "\\" in name or any(ord(c) < 32 for c in name):
        raise ArduinoError("integrity_mismatch")
    parts = name.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ArduinoError("integrity_mismatch")
    return "/".join(parts[1:])


def archive_contents(path: Path, archive: Archive, *, deadline: float) -> dict[str, Entry]:
    """Derive expected installed bytes from a fully verified archive, never a receipt."""
    if archive.size_bytes > MAX_ARCHIVE_BYTES:
        raise ArduinoError("resource_limit")
    try:
        with regular_file(path) as source:
            before = os.fstat(source.fileno())
            if _hash_stream(source, archive.size_bytes, deadline) != archive.sha256:
                raise ArduinoError("integrity_mismatch")
            source.seek(0)
            with tarfile.open(fileobj=source, mode="r:*") as package:
                result = _archive_entries(package, archive, deadline)
            after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ArduinoError("integrity_mismatch")
            return result
    except (OSError, tarfile.TarError, EOFError):
        raise ArduinoError("integrity_mismatch") from None


def _archive_entries(
    package: tarfile.TarFile, archive: Archive, deadline: float
) -> dict[str, Entry]:
    entries: dict[str, Entry] = {}
    expanded, count = 0, 0
    prefix: str | None = None
    for member in package:
        check_deadline(deadline)
        count += 1
        path = _member_path(member.name)
        member_prefix = member.name.split("/")[0]
        if prefix is not None and member_prefix != prefix:
            raise ArduinoError("integrity_mismatch")
        prefix = member_prefix
        if count > MAX_FILES or member.mode & 0o7000:
            raise ArduinoError("resource_limit")
        if not path:
            if not member.isdir():
                raise ArduinoError("integrity_mismatch")
            continue
        if path in entries:
            raise ArduinoError("integrity_mismatch")
        entry = _member_entry(package, member, archive, deadline)
        expanded += entry.size
        if expanded > MAX_TREE_BYTES:
            raise ArduinoError("resource_limit")
        entries[path] = entry
    return _complete_entries(entries)


def _member_entry(
    package: tarfile.TarFile, member: tarfile.TarInfo, archive: Archive, deadline: float
) -> Entry:
    if member.isdir():
        return Entry("directory")
    if member.isfile():
        if not 0 <= member.size <= MAX_TREE_BYTES:
            raise ArduinoError("resource_limit")
        stream = package.extractfile(member)
        if stream is None:
            raise ArduinoError("integrity_mismatch")
        with stream:
            digest = _hash_stream(stream, member.size, deadline)
        return Entry("file", member.size, digest, member.mode & 0o777)
    if member.issym() or member.islnk():
        kind = "symbolic" if member.issym() else "hard"
        if (archive.filename, member.name, member.linkname, kind) not in REVIEWED_LINKS:
            raise ArduinoError("integrity_mismatch")
        target = member.linkname if kind == "symbolic" else _member_path(member.linkname)
        return Entry(kind, target=target)
    raise ArduinoError("integrity_mismatch")


def _complete_entries(entries: dict[str, Entry]) -> dict[str, Entry]:
    for path in tuple(entries):
        for parent in PurePosixPath(path).parents:
            if str(parent) != ".":
                if str(parent) in entries and entries[str(parent)].kind != "directory":
                    raise ArduinoError("integrity_mismatch")
                entries.setdefault(str(parent), Entry("directory"))
    for path, entry in entries.items():
        if entry.kind in {"symbolic", "hard"}:
            target = (
                str(PurePosixPath(path).parent / entry.target)
                if entry.kind == "symbolic"
                else entry.target
            )
            if target not in entries or entries[target].kind != "file":
                raise ArduinoError("integrity_mismatch")
    return entries


@contextmanager
def operation_lock(venv: Path) -> Iterator[None]:
    import fcntl

    try:
        directory = open_directory(venv)
        try:
            descriptor = os.open(
                "arduino.operation.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
        finally:
            os.close(directory)
    except OSError:
        raise ArduinoError("operation_busy") from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ArduinoError("operation_busy")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ArduinoError("operation_busy") from None
        yield
    finally:
        os.close(descriptor)


def destination(root: Path, archive: Archive) -> Path:
    category = "hardware" if archive.name == "avr" else "tools"
    return root / "data/packages" / archive.package / category / archive.name / archive.version


def _inventory(root: Path, *, deadline: float) -> dict[str, os.stat_result]:
    result: dict[str, os.stat_result] = {}
    pending = [root]
    total = 0
    while pending:
        check_deadline(deadline)
        directory = pending.pop()
        descriptor = open_directory(directory)
        try:
            with os.scandir(descriptor) as children:
                _scan_children(root, directory, children, result, pending)
        finally:
            os.close(descriptor)
        total = sum(info.st_size for info in result.values() if stat.S_ISREG(info.st_mode))
        if total > MAX_TREE_BYTES:
            raise ArduinoError("resource_limit")
    return result


def _scan_children(
    root: Path,
    directory: Path,
    children: Iterator[os.DirEntry[str]],
    result: dict[str, os.stat_result],
    pending: list[Path],
) -> None:
    for child in children:
        info = child.stat(follow_symlinks=False)
        path = directory / child.name
        result[str(path.relative_to(root))] = info
        if len(result) > MAX_FILES:
            raise ArduinoError("resource_limit")
        if stat.S_ISDIR(info.st_mode):
            pending.append(path)
        elif not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise ArduinoError("integrity_mismatch")


def _verify_entries(
    root: Path, entries: dict[str, Entry], deadline: float, *, allow_installed: bool = False
) -> None:
    inventory = _inventory(root, deadline=deadline)
    allowed = set(entries) | ({"installed.json"} if allow_installed else set())
    if set(inventory) != allowed:
        raise ArduinoError("integrity_mismatch")
    for path, entry in entries.items():
        info = inventory[path]
        if entry.kind == "directory":
            if not stat.S_ISDIR(info.st_mode):
                raise ArduinoError("integrity_mismatch")
        elif entry.kind == "symbolic":
            if not stat.S_ISLNK(info.st_mode) or os.readlink(root / path) != entry.target:
                raise ArduinoError("integrity_mismatch")
        else:
            target = entries[entry.target] if entry.kind == "hard" else entry
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o777 != target.mode:
                raise ArduinoError("integrity_mismatch")
            if digest_file(root / path, target.size, deadline) != target.sha256:
                raise ArduinoError("integrity_mismatch")
            if entry.kind == "hard" and (info.st_dev, info.st_ino) != (
                inventory[entry.target].st_dev,
                inventory[entry.target].st_ino,
            ):
                raise ArduinoError("integrity_mismatch")


def _installed_metadata() -> dict[str, Any]:
    package = json.loads(frozen_package_index())["packages"][0]
    package["websiteUrl"] = package.pop("websiteURL")
    # CLI 1.5.1 records this fixed upstream origin in installed platform metadata.
    package["url"] = "https://downloads.arduino.cc/packages/package_index.tar.bz2"
    platform = package["platforms"][0]
    platform.update(
        {
            "deprecated": False,
            "discoveryDependencies": [],
            "monitorDependencies": [],
            "libraryDependencies": [],
        }
    )
    return {"packages": [package], "IsTrusted": False, "version": 2}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(read_bounded(path, 128 * 1024))
    except (ValueError, UnicodeError):
        raise ArduinoError("integrity_mismatch") from None


def _verify_installed_metadata(path: Path) -> None:
    actual, expected = _read_json(path), _installed_metadata()
    # CLI serializes its tool map in nondeterministic order. Normalize only this
    # collection; full records and duplicate cardinality remain strictly checked.
    for value in (actual, expected):
        try:
            collection = value["packages"][0]["tools"]
            if not isinstance(collection, list):
                raise TypeError
            value["packages"][0]["tools"] = sorted(collection, key=canonical_bytes)
        except (KeyError, IndexError, TypeError):
            raise ArduinoError("integrity_mismatch") from None
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise ArduinoError("integrity_mismatch")


def _same_json(path: Path, expected: object) -> None:
    actual = _read_json(path)
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise ArduinoError("integrity_mismatch")


def verify_runtime(root: Path, config: dict[str, Any], *, deadline: float) -> str:
    """Rehash the pinned archives and installed closure on every readiness decision."""
    try:
        directory = open_directory(root)
        os.close(directory)
        _same_json(root / "ready.json", {"schema_version": 1, "manifest_sha256": manifest_sha256()})
        _verify_runtime_content(root, config, deadline)
    except (OSError, ValueError):
        raise ArduinoError("toolchain_unavailable") from None
    return manifest_sha256()


def _receipt_absent(root: Path) -> None:
    for name in ("ready.json", "ready.pending"):
        try:
            (root / name).lstat()
        except FileNotFoundError:
            continue
        raise ArduinoError("toolchain_unavailable")


def _identity(descriptor: int) -> tuple[int, int]:
    info = os.fstat(descriptor)
    return info.st_dev, info.st_ino


def recoverable_runtime(root: Path, config: dict[str, Any], *, deadline: float) -> tuple[int, int]:
    """Read-only eligibility: the entire pinned closure exists, only its receipt is absent."""
    try:
        with held_directory(root) as (anchor, descriptor):
            _receipt_absent(anchor)
            _verify_runtime_content(anchor, config, deadline)
            with held_directory(root) as (_, current):
                if _identity(current) != _identity(descriptor):
                    raise ArduinoError("stale_state")
            return _identity(descriptor)
    except OSError:
        raise ArduinoError("toolchain_unavailable") from None


def finalize_runtime(
    root: Path,
    cli: Path,
    config: dict[str, Any],
    *,
    identity: tuple[int, int],
    deadline: float,
) -> dict[str, Any]:
    """Under the approval operation lock, publish only a freshly verified missing receipt."""
    try:
        with held_directory(root) as (anchor, descriptor):
            if _identity(descriptor) != identity:
                raise ArduinoError("stale_state")
            _receipt_absent(anchor)
            verify_cli(cli)
            _verify_runtime_content(anchor, config, deadline)
            verify_cli(cli)
            with held_directory(root) as (_, current):
                if _identity(current) != identity:
                    raise ArduinoError("stale_state")
            check_deadline(deadline)
            _receipt_absent(anchor)
            receipt = canonical_bytes({"schema_version": 1, "manifest_sha256": manifest_sha256()})
            with (anchor / "ready.pending").open("xb") as output:
                output.write(receipt)
                output.flush()
                os.link(anchor / "ready.pending", anchor / "ready.json", follow_symlinks=False)
                published = (anchor / "ready.json").lstat()
                if (published.st_dev, published.st_ino) != _identity(output.fileno()):
                    raise ArduinoError("stale_state")
                pending = (anchor / "ready.pending").lstat()
                if (pending.st_dev, pending.st_ino) != _identity(output.fileno()):
                    raise ArduinoError("stale_state")
                (anchor / "ready.pending").unlink()
            return {
                "ok": True,
                "changed": True,
                "action": "finalize_ready",
                "manifest_sha256": manifest_sha256(),
                "dependencies": [
                    {"id": a.id, "version": a.version, "sha256": a.sha256} for a in ARCHIVES
                ],
            }
    except OSError:
        raise ArduinoError("toolchain_unavailable") from None


def _verify_runtime_content(root: Path, config: dict[str, Any], deadline: float) -> None:
    _same_json(root / "arduino-cli.json", config)
    if read_bounded(root / "data/package_index.json", 128 * 1024) != frozen_package_index():
        raise ArduinoError("integrity_mismatch")
    if read_bounded(root / "data/library_index.json", 1024) != empty_library_index():
        raise ArduinoError("integrity_mismatch")
    inventory = read_bounded(root / "data/inventory.yaml", 512)
    if not re.fullmatch(
        rb"installation:\n    id: [0-9a-f-]{36}\n    secret: [0-9a-f-]{36}\n", inventory
    ):
        raise ArduinoError("integrity_mismatch")
    for archive in ARCHIVES:
        entries = archive_contents(
            root / "downloads/packages" / archive.filename, archive, deadline=deadline
        )
        target = destination(root, archive)
        _verify_entries(target, entries, deadline, allow_installed=archive.name == "avr")
        if archive.name == "avr":
            _verify_installed_metadata(target / "installed.json")
    _verify_runtime_layout(root)


def _verify_runtime_layout(root: Path) -> None:
    expected_top = {
        "arduino-cli.json",
        "ready.json",
        "data",
        "downloads",
        "home",
        "tmp",
        "user",
        "libraries",
        "cache",
        "builds",
    }
    for name in expected_top - {"arduino-cli.json", "ready.json"}:
        directory = open_directory(root / name)
        os.close(directory)
    if {p.name for p in root.iterdir()} - expected_top:
        raise ArduinoError("integrity_mismatch")
    if {p.name for p in (root / "data").iterdir()} != {
        "packages",
        "inventory.yaml",
        "package_index.json",
        "library_index.json",
        "tmp",
    }:
        raise ArduinoError("integrity_mismatch")
    directory = open_directory(root / "data/tmp")
    try:
        if os.listdir(directory):
            raise ArduinoError("integrity_mismatch")
    finally:
        os.close(directory)
    if {p.name for p in (root / "downloads/packages").iterdir()} != {a.filename for a in ARCHIVES}:
        raise ArduinoError("integrity_mismatch")
    # Shared caches/user libraries could inject build inputs; compile uses isolated jobs.
    for name in ("home", "tmp", "user", "libraries", "cache"):
        if any((root / name).iterdir()):
            raise ArduinoError("integrity_mismatch")
    _verify_package_layout(root)


def _verify_package_layout(root: Path) -> None:
    expected_packages: set[str] = set()
    for archive in ARCHIVES:
        relative = destination(root, archive).relative_to(root / "data/packages")
        expected_packages.add(str(relative))
        expected_packages.update(str(p) for p in relative.parents if str(p) != ".")
    for package in (root / "data/packages").iterdir():
        if package.name not in {a.package for a in ARCHIVES}:
            raise ArduinoError("integrity_mismatch")
    # Every directory up to a version must be exactly one of the frozen prefixes.
    for path in expected_packages:
        base = root / "data/packages" / path
        directory = open_directory(base)
        os.close(directory)
        if len(PurePosixPath(path).parts) < 4:
            if any(
                str(p.relative_to(root / "data/packages")) not in expected_packages
                for p in base.iterdir()
            ):
                raise ArduinoError("integrity_mismatch")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise ArduinoError("installation_failed")


def download_archive(path: Path, archive: Archive, *, deadline: float) -> None:
    """Only reviewed HTTPS endpoints, no inherited proxy or redirects."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    check_deadline(deadline)
    try:
        with opener.open(
            archive.url, timeout=min(10, max(0.1, deadline - time.monotonic()))
        ) as response:
            with path.open("xb") as output:
                total, digest = 0, hashlib.sha256()
                while True:
                    check_deadline(deadline)
                    data = response.read(min(1024 * 1024, archive.size_bytes + 1 - total))
                    if not data:
                        break
                    total += len(data)
                    if total > min(archive.size_bytes, MAX_ARCHIVE_BYTES):
                        raise ArduinoError("resource_limit")
                    digest.update(data)
                    output.write(data)
                if total != archive.size_bytes or digest.hexdigest() != archive.sha256:
                    raise ArduinoError("integrity_mismatch")
    except (OSError, urllib.error.URLError):
        raise ArduinoError("installation_failed") from None


def install_runtime(
    root: Path, cli: Path, config: dict[str, Any], argv: tuple[str, ...], *, deadline: float
) -> dict[str, Any]:
    """Called only under the approved operation lock; never repair an existing root."""
    with held_directory(root.parent) as (_, parent_fd):
        try:
            os.mkdir(root.name, mode=0o700, dir_fd=parent_fd)
            descriptor = os.open(
                root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
        except OSError:
            raise ArduinoError("toolchain_unavailable") from None
        with held_descriptor(descriptor) as (anchor, root_fd):
            return _install_into(anchor, root, root_fd, cli, config, argv, deadline)


def _install_into(
    root: Path,
    canonical_root: Path,
    root_fd: int,
    cli: Path,
    config: dict[str, Any],
    argv: tuple[str, ...],
    deadline: float,
) -> dict[str, Any]:
    for name in (
        "data",
        "downloads/packages",
        "home",
        "tmp",
        "user",
        "libraries",
        "cache",
        "builds",
    ):
        (root / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    (root / "arduino-cli.json").write_bytes(canonical_bytes(config))
    (root / "data/package_index.json").write_bytes(frozen_package_index())
    (root / "data/library_index.json").write_bytes(empty_library_index())
    for archive in ARCHIVES:
        path = root / "downloads/packages" / archive.filename
        download_archive(path, archive, deadline=deadline)
        archive_contents(path, archive, deadline=deadline)
    verify_cli(cli)
    result = run_bounded(
        sandbox_argv(cli, canonical_root, argv, writable_fd=root_fd),
        cwd=root,
        env=closed_environment(canonical_root),
        deadline=deadline,
    )
    if not result["ok"]:
        raise ArduinoError("installation_failed")
    verify_cli(cli)
    _verify_runtime_content(root, config, deadline)
    check_deadline(deadline)
    receipt = canonical_bytes({"schema_version": 1, "manifest_sha256": manifest_sha256()})
    (root / "ready.pending").write_bytes(receipt)
    os.link(root / "ready.pending", root / "ready.json", follow_symlinks=False)
    (root / "ready.pending").unlink()
    return {
        "ok": True,
        "changed": True,
        "manifest_sha256": manifest_sha256(),
        "dependencies": [{"id": a.id, "version": a.version, "sha256": a.sha256} for a in ARCHIVES],
    }


def verify_cli(path: Path) -> None:
    from .arduino_toolchain import _regular_digest

    if _regular_digest(path) != CLI_SHA256:
        raise ArduinoError("cli_unavailable")
