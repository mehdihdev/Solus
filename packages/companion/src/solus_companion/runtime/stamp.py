"""`solus-stamp.json` schema v1 — mcp-fork-runtime.md §4.

All fields required, unknown fields rejected, ≤ 4 KiB, never followed through
a symlink. A newer `schema_version` simply fails to parse and so reads as a
stamp mismatch (rebuild offered), never as something to overwrite silently."""

import hashlib
import os
import stat
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, ValidationError

from solus_companion.runtime.roots import FORK_NAME_PATTERN

STAMP_NAME = "solus-stamp.json"
MAX_STAMP_BYTES = 4096


def _absolute(value: str) -> str:
    if not (value.startswith("/") or PureWindowsPath(value).is_absolute()):
        raise ValueError("base.path must be absolute")
    return value


class StampBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    path: Annotated[str, Field(min_length=1, max_length=2048), AfterValidator(_absolute)]
    version: Annotated[str, Field(pattern=r"^3\.1[23]\.\d+$")]
    implementation: Literal["cpython"]
    managed: StrictBool


class Stamp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1]
    fork: Annotated[str, Field(pattern=FORK_NAME_PATTERN)]
    lock_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    base: StampBase
    created_at: Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")]


def lock_sha256(lock: Path) -> str:
    return hashlib.sha256(lock.read_bytes()).hexdigest()


def read_stamp(path: Path) -> Stamp | None:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STAMP_BYTES:
            return None
        with path.open("rb") as handle:
            raw = handle.read(MAX_STAMP_BYTES + 1)
        if len(raw) > MAX_STAMP_BYTES:
            return None
        return Stamp.model_validate_json(raw, strict=False)
    except (OSError, ValidationError, ValueError):
        return None


def write_stamp(env_dir: Path, stamp: Stamp) -> None:
    """Atomic: a temp file beside the target, then `os.replace`."""
    payload = stamp.model_dump_json(indent=2).encode("utf-8")
    fd, temp = tempfile.mkstemp(prefix=".stamp-", dir=env_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(temp, env_dir / STAMP_NAME)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
