"""Bounded text plans and descriptor-confined publication; no process execution."""

import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from solus_companion.machine.actions import WRITE_CAP_BYTES, MachineActionError

_PRIVATE = {".git", ".ssh", ".aws", ".azure", ".config", ".gnupg", ".kube"}
_PRIVATE_MARKERS = ("secret", "credential", "private_key", "private-key", "id_rsa", "id_ed25519")
_FINGERPRINT = re.compile(r"(?:[0-9a-f]{16}:){3}[0-9a-f]{16}")


def _parts(path: str) -> tuple[str, ...]:
    parts = tuple(path.split("/"))
    if (
        not path
        or len(path) > 400
        or len(parts) > 32
        or "\\" in path
        or ":" in path
        or any(ord(c) < 32 for c in path)
        or any(p in {"", ".", ".."} for p in parts)
        or any(
            p.lower().startswith(".env")
            or p.lower() in _PRIVATE
            or any(m in p.lower() for m in _PRIVATE_MARKERS)
            for p in parts
        )
    ):
        raise MachineActionError("Unsafe or sensitive workspace-relative write path")
    return parts


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (*_identity(value), value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@dataclass
class Directory:
    descriptors: list[int]
    edges: list[tuple[int, str, int]]
    missing: list[str]

    @property
    def fd(self) -> int:
        return self.descriptors[-1]

    def validate(self) -> None:
        for parent, name, opened in self.edges:
            if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _identity(
                os.fstat(opened)
            ):
                raise MachineActionError("Workspace directory changed; request a new preview")

    def create(self) -> None:
        for name in self.missing:
            self.validate()
            parent = self.fd
            os.mkdir(name, mode=0o700, dir_fd=parent)
            opened = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            self.descriptors.append(opened)
            self.edges.append((parent, name, opened))
        self.missing.clear()


@contextmanager
def _directory(workspace: Path, parts: tuple[str, ...]) -> Iterator[Directory]:
    if (
        os.open not in os.supports_dir_fd
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
    ):
        raise MachineActionError("Secure file writes are unavailable on this platform")
    root = workspace.absolute()
    directory = Directory([], [], [])
    try:
        directory.descriptors.append(
            os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        )
        names = (*root.parts[1:], *parts[:-1])
        for index, name in enumerate(names):
            parent = directory.fd
            try:
                opened = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                if index < len(root.parts) - 1:
                    raise MachineActionError("Linked workspace is unavailable") from None
                directory.missing = list(names[index:])
                break
            directory.descriptors.append(opened)
            directory.edges.append((parent, name, opened))
        directory.validate()
        yield directory
    except OSError:
        raise MachineActionError("File path is unavailable or contains a symlink") from None
    finally:
        for descriptor in reversed(directory.descriptors):
            os.close(descriptor)


def _read(parent: int, name: str) -> tuple[bytes | None, tuple[int, ...] | None]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        return None, None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > WRITE_CAP_BYTES:
            raise MachineActionError("A bounded regular UTF-8 file is required")
        chunks = []
        remaining = WRITE_CAP_BYTES + 1
        while remaining:
            part = os.read(fd, min(remaining, 65536))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        if not remaining or _file_identity(info) != _file_identity(os.fstat(fd)):
            raise MachineActionError("File changed or exceeds the write limit")
        return b"".join(chunks), _file_identity(info)
    finally:
        os.close(fd)


def _text(data: bytes) -> str:
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError:
        raise MachineActionError("Complete previews require UTF-8 text") from None
    if any(ord(c) < 32 and c not in "\t\n\r" for c in value):
        raise MachineActionError("Binary text is not supported for file writes")
    return value


@dataclass(frozen=True)
class Plan:
    before: bytes | None
    identity: tuple[int, ...] | None
    data: bytes
    fingerprint: str
    preview: list[dict[str, Any]]


def _plan(directory: Directory, parts: tuple[str, ...], content: str, create_dirs: bool) -> Plan:
    data = content.encode("utf-8")
    if len(data) > WRITE_CAP_BYTES:
        raise MachineActionError("write_file is capped at 200 KB")
    _text(data)
    if directory.missing and not create_dirs:
        raise MachineActionError("Parent directory does not exist; request create_dirs")
    before, identity = (None, None) if directory.missing else _read(directory.fd, parts[-1])
    old = None if before is None else _text(before)
    state = {
        "path": parts,
        "content": content,
        "before": old,
        "file": identity,
        "directories": [_identity(os.fstat(fd)) for fd in directory.descriptors],
        "missing": directory.missing,
        "create_dirs": create_dirs,
    }
    digest = hashlib.sha256(
        json.dumps(state, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    fingerprint = ":".join(digest[i : i + 16] for i in range(0, 64, 16))
    rows = [
        {"label": "File", "before": None, "after": "/".join(parts)},
        {"label": "File state fingerprint", "before": None, "after": fingerprint},
    ]
    if directory.missing:
        rows.append(
            {"label": "Create directories", "before": None, "after": "/".join(directory.missing)}
        )
    for index in range(max(1, (max(len(old or ""), len(content)) + 399) // 400)):
        start = index * 400
        rows.append(
            {
                "label": f"Content {index + 1}",
                "before": None if old is None else old[start : start + 400],
                "after": content[start : start + 400],
            }
        )
    if len(rows) > 40:
        raise MachineActionError("Complete file contents exceed preview limits")
    directory.validate()
    return Plan(before, identity, data, fingerprint, rows)


def preview(workspace: Path, path: str, content: str, *, create_dirs: bool) -> dict[str, Any]:
    parts = _parts(path)
    with _directory(workspace, parts) as directory:
        plan = _plan(directory, parts, content, create_dirs)
        return {
            "ok": True,
            "dry_run": True,
            "fingerprint": plan.fingerprint,
            "preview": plan.preview,
        }


def _publish(directory: Directory, name: str, plan: Plan) -> None:
    temporary = ".solus-write-" + uuid.uuid4().hex
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory.fd
    )
    info = os.fstat(fd)
    published = False
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(plan.data)
            handle.flush()
            os.fsync(fd)
        if plan.identity is not None:
            os.fchmod(fd, stat.S_IMODE(plan.identity[2]) & 0o777)
        directory.validate()
        if _read(directory.fd, name) != (plan.before, plan.identity):
            raise MachineActionError("File changed since its preview")
        if _identity(os.stat(temporary, dir_fd=directory.fd, follow_symlinks=False)) != _identity(
            info
        ):
            raise MachineActionError("Temporary file changed")
        published = True  # A failing publication call may still have changed the directory.
        if plan.before is None:
            os.link(
                temporary,
                name,
                src_dir_fd=directory.fd,
                dst_dir_fd=directory.fd,
                follow_symlinks=False,
            )
        else:
            os.replace(temporary, name, src_dir_fd=directory.fd, dst_dir_fd=directory.fd)
        directory.validate()
        observed, observed_id = _read(directory.fd, name)
        if observed != plan.data or observed_id is None or observed_id[:2] != _identity(info):
            raise MachineActionError("Published file did not match")
        os.fsync(directory.fd)
        directory.validate()
    except (OSError, MachineActionError) as exc:
        if published:
            raise MachineActionError(
                "mutation_unverified: file may have been written; inspect it before retrying"
            ) from exc
        raise
    finally:
        os.close(fd)
        try:
            if _identity(
                os.stat(temporary, dir_fd=directory.fd, follow_symlinks=False)
            ) == _identity(info):
                os.unlink(temporary, dir_fd=directory.fd)
        except FileNotFoundError:
            pass


def write(
    workspace: Path, path: str, content: str, *, create_dirs: bool, expected_fingerprint: str | None
) -> dict[str, Any]:
    if not isinstance(expected_fingerprint, str) or not _FINGERPRINT.fullmatch(
        expected_fingerprint
    ):
        raise MachineActionError("A complete file preview fingerprint is required")
    parts = _parts(path)
    with _directory(workspace, parts) as directory:
        plan = _plan(directory, parts, content, create_dirs)
        if plan.fingerprint != expected_fingerprint:
            raise MachineActionError("File changed since its preview")
        if directory.missing:
            directory.create()
        if plan.before != plan.data:
            _publish(directory, parts[-1], plan)
        return {
            "path": "/".join(parts),
            "bytes_written": len(plan.data),
            "changed": plan.before != plan.data,
            "verified": True,
        }
