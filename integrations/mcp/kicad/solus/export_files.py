"""Descriptor-confined output handling for owned KiCad exports."""

import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from solus.development.models import DevelopmentError
from solus.workspace import ARTIFACT_DIR_NAME, WorkspaceNotConfiguredError, workspace_root


@contextmanager
def _root_directory() -> Iterator[tuple[Path, int]]:
    try:
        root = workspace_root()
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except (OSError, WorkspaceNotConfiguredError) as exc:
        raise DevelopmentError("path_escapes_workspace") from exc
    try:
        yield root, descriptor
    finally:
        os.close(descriptor)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _directory_matches(parent: int, name: str, descriptor: int) -> bool:
    try:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        return stat.S_ISDIR(current.st_mode) and _same_inode(current, os.fstat(descriptor))
    except OSError:
        return False


def _verify_directory(root: Path, root_fd: int, name: str, directory: int) -> None:
    current = os.stat(root, follow_symlinks=False)
    if not _same_inode(current, os.fstat(root_fd)) or not _directory_matches(
        root_fd, name, directory
    ):
        raise DevelopmentError("path_escapes_workspace")


def read_regular_at(directory: int, name: str, maximum: int) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError("output is not a regular file")
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise DevelopmentError("file_too_large")
    return data


def _unlink_at(directory: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        pass


def publish_artifact(filename: str, data: bytes) -> str:
    """Stage/replace/read back through one directory descriptor, never path aliases."""
    if (
        not filename
        or Path(filename).name != filename
        or "\\" in filename
        or filename.startswith(".")
    ):
        raise DevelopmentError("path_escapes_workspace")
    with _root_directory() as (root, root_fd):
        try:
            os.mkdir(ARTIFACT_DIR_NAME, mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        directory = os.open(
            ARTIFACT_DIR_NAME, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
        temporary = ".solus-publish-" + secrets.token_hex(12)
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            _verify_directory(root, root_fd, ARTIFACT_DIR_NAME, directory)
            os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            _verify_directory(root, root_fd, ARTIFACT_DIR_NAME, directory)
            if read_regular_at(directory, filename, len(data)) != data:
                raise DevelopmentError("mutation_unverified")
            return f"{ARTIFACT_DIR_NAME}/{filename}"
        except OSError as exc:
            raise DevelopmentError("path_escapes_workspace") from exc
        finally:
            try:
                _unlink_at(directory, temporary)
            finally:
                os.close(directory)
