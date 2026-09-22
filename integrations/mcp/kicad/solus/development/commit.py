"""Confined no-follow publication with stale checks and verified read-back."""

import os
import secrets
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from solus.development.models import (
    MAX_SCHEMATIC_BYTES,
    DevelopmentError,
    fingerprint,
    schematic_path,
)
from solus.development.plan import MutationPlan

_LOCK = threading.RLock()


@contextmanager
def parent_directory(root: Path, relative: str) -> Iterator[tuple[int, str]]:
    parts = schematic_path(relative).split("/")
    descriptors = []
    try:
        if not root.is_absolute() or root.resolve() != root:
            raise DevelopmentError("path_escapes_workspace")
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
        yield fd, parts[-1]
    except OSError as exc:
        raise DevelopmentError("path_escapes_workspace") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def read_at(directory: int, name: str) -> bytes | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise DevelopmentError("path_escapes_workspace")
        data = handle.read(MAX_SCHEMATIC_BYTES + 1)
    if len(data) > MAX_SCHEMATIC_BYTES:
        raise DevelopmentError("file_too_large")
    return data


def read_schematic(root: Path, relative: str) -> bytes:
    with parent_directory(root, relative) as (directory, name):
        data = read_at(directory, name)
        if data is None:
            raise DevelopmentError("path_escapes_workspace")
        return data


def commit_plan(root: Path, plan: MutationPlan) -> str:
    with (
        _LOCK,
        parent_directory(root, plan.path) as (directory, name),
        _writer_lock(directory, name),
    ):
        temp = ".solus-" + secrets.token_hex(12) + ".tmp"
        published = False
        try:
            _check_editor_lock(directory, name)
            current = read_at(directory, name)
            if plan.original is None and current is not None:
                raise DevelopmentError("already_exists")
            if current != plan.original:
                raise DevelopmentError("stale_plan")
            mode = (
                0o600
                if current is None
                else stat.S_IMODE(os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode)
            )
            fd = os.open(
                temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=directory
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(plan.proposed)
                handle.flush()
                os.fsync(handle.fileno())
            _verify_parent(root, plan.path, directory)
            _check_editor_lock(directory, name)
            if read_at(directory, name) != plan.original:
                raise DevelopmentError("stale_plan")
            published = True
            if plan.original is None:
                try:
                    os.link(
                        temp,
                        name,
                        src_dir_fd=directory,
                        dst_dir_fd=directory,
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    raise DevelopmentError("already_exists") from exc
            else:
                os.replace(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            if read_at(directory, name) != plan.proposed:
                raise DevelopmentError("mutation_unverified")
            _verify_parent(root, plan.path, directory)
            return fingerprint(plan.proposed)
        except (OSError, DevelopmentError) as exc:
            raise _publication_error(exc, published) from exc
        finally:
            try:
                os.unlink(temp, dir_fd=directory)
            except FileNotFoundError:
                pass


def _publication_error(exc: OSError | DevelopmentError, published: bool) -> DevelopmentError:
    if published:
        return DevelopmentError("mutation_unverified")
    return exc if isinstance(exc, DevelopmentError) else DevelopmentError("guard_failed")


def _check_editor_lock(directory: int, name: str) -> None:
    for lock_name in ("~" + name + ".lck", name + ".lck"):
        try:
            os.stat(lock_name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise DevelopmentError("stale_plan")


def _verify_parent(root: Path, relative: str, opened: int) -> None:
    with parent_directory(root, relative) as (current, _name):
        before, now = os.fstat(opened), os.fstat(current)
        if (before.st_dev, before.st_ino) != (now.st_dev, now.st_ino):
            raise DevelopmentError("path_escapes_workspace")


@contextmanager
def _writer_lock(directory: int, name: str) -> Iterator[None]:
    # A persistent inode coordinates separate companion processes. Never unlink
    # it: a waiter must not lock an old inode while a new writer locks another.
    try:
        import fcntl
    except ImportError as exc:
        raise DevelopmentError("guard_failed") from exc
    lock_name = ".solus-" + fingerprint(name.encode()).replace(":", "") + ".lock"
    fd = os.open(
        lock_name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory
    )
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise DevelopmentError("path_escapes_workspace")
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DevelopmentError("stale_plan") from None
                time.sleep(0.01)
        yield
    finally:
        os.close(fd)
