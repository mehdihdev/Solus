"""Verify an explicitly pinned regular-file asset closure without path escape."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath


def verify_assets(root: Path, manifest: dict[str, str]) -> str:
    if not 1 <= len(manifest) <= 32:
        raise ValueError("asset count")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    total = 0
    try:
        for name, digest in sorted(manifest.items()):
            parts = PurePosixPath(name).parts
            if (
                not parts
                or name.startswith("/")
                or any(p in (".", "..") or not re.fullmatch("[A-Za-z0-9_.-]+", p) for p in parts)
                or not re.fullmatch("[0-9a-f]{64}", digest)
            ):
                raise ValueError("invalid asset path or digest")
            parent = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    os.close(parent)
                    parent = nxt
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode) or before.st_size > 20_000_000:
                        raise ValueError("invalid asset file")
                    total += before.st_size
                    if total > 32_000_000:
                        raise ValueError("asset closure too large")
                    calculated = _hash_fd(fd, before.st_size)
                    after = os.fstat(fd)
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ) or calculated != digest:
                        raise ValueError("asset integrity mismatch")
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
    except OSError as error:
        raise ValueError("asset unavailable or unsafe") from error
    finally:
        os.close(root_fd)
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def copy_verified_assets(root: Path, manifest: dict[str, str], destination: Path) -> str:
    """Copy through no-follow descriptors, then verify the private immutable input."""
    expected = verify_assets(root, manifest)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name, digest in manifest.items():
            parts = PurePosixPath(name).parts
            parent = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    next_fd = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                    )
                    os.close(parent)
                    parent = next_fd
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 20_000_000:
                        raise ValueError("invalid asset")
                    chunks = []
                    size = 0
                    while chunk := os.read(fd, 65536):
                        size += len(chunk)
                        if size > 20_000_000:
                            raise ValueError("asset changed size")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError("asset changed")
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
            target = destination / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(data)
            target.chmod(0o400)
    finally:
        os.close(root_fd)
    if verify_assets(destination, manifest) != expected:
        raise ValueError("copied asset mismatch")
    return expected


def _hash_fd(fd: int, maximum_size: int) -> str:
    calculated = hashlib.sha256()
    bytes_read = 0
    while chunk := os.read(fd, 65536):
        bytes_read += len(chunk)
        if bytes_read > maximum_size or bytes_read > 20_000_000:
            raise ValueError("asset grew during verification")
        calculated.update(chunk)
    return calculated.hexdigest()
