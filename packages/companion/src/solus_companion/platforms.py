"""Solus-authored OS restrictions, independent of the tool allowlist."""

import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PLATFORM_NAMES = {"linux": "Linux", "darwin": "macOS", "win32": "Windows"}
INVALID_METADATA = "Platform availability is unavailable"


class PlatformMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    display_name: str = Field(
        min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._+-]*$"
    )
    supported_platforms: list[Literal["linux", "darwin", "win32"]] = Field(
        min_length=1, max_length=3
    )


def unavailable_reason(root: Path, server_dir: Path, platform: str) -> str | None:
    """Absent means unrestricted; present invalid metadata always refuses launch."""
    path = server_dir / "platform.json"
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            return INVALID_METADATA
        if not path.exists() and not path.is_symlink():
            return None
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            return INVALID_METADATA
        with resolved.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return INVALID_METADATA
        metadata = PlatformMetadata.model_validate_json(raw)
    except (OSError, ValueError, ValidationError):
        return INVALID_METADATA
    if platform in metadata.supported_platforms:
        return None
    host = PLATFORM_NAMES.get(platform, "this operating system")
    return f"{metadata.display_name} is not available on {host}"
