"""Bounded immutable simulator revision publication through a workspace dirfd."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from typing import Any
from uuid import UUID, uuid4


class RevisionStore:
    def __init__(self, workspace_fd: int, session_id: str) -> None:
        if str(UUID(session_id)) != session_id:
            raise ValueError("invalid session")
        self.workspace_fd = workspace_fd
        self.session_id = session_id

    def relative_path(self, generation: int) -> str:
        if type(generation) is not int or not 1 <= generation <= 32:
            raise ValueError("revision limit")
        return f".solus/isaac/{self.session_id}-{generation}.json"

    def publish(self, generation: int, record: dict[str, Any]) -> dict[str, Any]:
        path = self.relative_path(generation)
        data = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(data) > 128 * 1024:
            raise ValueError("revision too large")
        solus_fd = self._directory(self.workspace_fd, ".solus")
        try:
            directory = self._directory(solus_fd, "isaac")
            try:
                fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._verify_namespace(solus_fd, directory)
                result = self._publish(directory, path, data)
                self._verify_namespace(solus_fd, directory)
                return result
            finally:
                os.close(directory)
        finally:
            os.close(solus_fd)

    def _verify_namespace(self, solus_fd: int, directory: int) -> None:
        for parent, name, descriptor in (
            (self.workspace_fd, ".solus", solus_fd),
            (solus_fd, "isaac", directory),
        ):
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            held = os.fstat(descriptor)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
                held.st_dev,
                held.st_ino,
            ):
                raise OSError("revision namespace changed")

    @staticmethod
    def _directory(parent: int, name: str) -> int:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)

    @staticmethod
    def _publish(directory: int, path: str, data: bytes) -> dict[str, Any]:
        temporary = ".pending-" + str(uuid4())
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        identity = os.fstat(fd)
        try:
            offset = 0
            while offset < len(data):
                offset += os.write(fd, data[offset:])
            os.fsync(fd)
            os.fchmod(fd, 0o400)
            os.link(
                temporary,
                path.rsplit("/", 1)[1],
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            os.fsync(directory)
            read_fd = os.open(path.rsplit("/", 1)[1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                observed = os.fstat(read_fd)
                if (observed.st_dev, observed.st_ino) != (identity.st_dev, identity.st_ino):
                    raise OSError("revision identity changed")
                if os.read(read_fd, 128 * 1024 + 1) != data:
                    raise OSError("revision readback mismatch")
            finally:
                os.close(read_fd)
        finally:
            os.close(fd)
            current = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                os.unlink(temporary, dir_fd=directory)
        return {
            "saved": True,
            "relative_path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
