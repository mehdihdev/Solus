"""Confined, read-only saved source text; independent of generic machine.read_file.

POSIX directory descriptors pin each component during traversal. Platforms
without no-follow descriptor-relative open fail closed rather than relying on
racy resolve/check/open sequences. Workspace contents are never executed.
"""

import os
import stat
from pathlib import Path, PurePosixPath

from solus_companion.machine.actions import MachineActionError

MAX_CODE_BYTES = 128 * 1024
_CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".ino",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".swift",
        ".sh",
        ".bash",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".md",
        ".rst",
        ".xml",
        ".urdf",
        ".xacro",
        ".cmake",
        ".css",
        ".html",
        ".sql",
        ".proto",
    }
)
_CODE_NAMES = frozenset({"makefile", "cmakelists.txt", "dockerfile", "requirements.txt"})
_PRIVATE_MARKERS = ("secret", "credential", "private_key", "private-key", "id_rsa", "id_ed25519")
_PRIVATE_DIRS = frozenset({".git", ".ssh", ".aws", ".azure", ".config", ".gnupg", ".kube"})


def _parts(path: str) -> tuple[str, ...]:
    if not path or len(path) > 4096 or "\\" in path or ":" in path or "\x00" in path:
        raise MachineActionError("Invalid workspace-relative code path")
    parts = tuple(path.split("/"))
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(path).is_absolute():
        raise MachineActionError("Code path must stay inside the workspace")
    for part in parts:
        lowered = part.lower()
        if (
            lowered.startswith(".env")
            or lowered in _PRIVATE_DIRS
            or any(marker in lowered for marker in _PRIVATE_MARKERS)
        ):
            raise MachineActionError("Sensitive paths are not readable as code context")
    name = parts[-1].lower()
    if PurePosixPath(name).suffix not in _CODE_SUFFIXES and name not in _CODE_NAMES:
        raise MachineActionError("Only supported source text files are readable as code context")
    return parts


def _open_code(workspace: Path, parts: tuple[str, ...]) -> int:
    if (
        os.open not in os.supports_dir_fd
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
    ):
        raise MachineActionError("Secure saved-code reading is unavailable on this platform")
    # Open the configured root from the filesystem anchor as well: a symlink
    # anywhere in its ancestry is refused, not just in the user-supplied suffix.
    root = workspace.absolute()
    directory = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in (*root.parts[1:], *parts[:-1]):
            next_directory = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = next_directory
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)


def _read(fd: int) -> bytes:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise MachineActionError("Code context requires a regular file")
    remaining = MAX_CODE_BYTES + 1
    chunks: list[bytes] = []
    while remaining:
        chunk = os.read(fd, min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if remaining == 0:
        raise MachineActionError("Code file exceeds the 128 KiB context limit")
    return b"".join(chunks)


def read_code_file(workspace: Path, path: str) -> dict[str, object]:
    parts = _parts(path)  # Reject sensitive names before any filesystem access.
    try:
        fd = _open_code(workspace, parts)
        try:
            data = _read(fd)
        finally:
            os.close(fd)
    except OSError:
        raise MachineActionError("Code file is unavailable or contains a symlink") from None
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise MachineActionError("Code context requires UTF-8 text") from None
    if any(ord(char) < 32 and char not in "\t\n\r" for char in content):
        raise MachineActionError("Binary content is not readable as code context")
    return {
        "path": "/".join(parts),
        "content": content,
        "encoding": "utf-8",
        "size_bytes": len(data),
    }
