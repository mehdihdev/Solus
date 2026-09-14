"""Read the shipped platform restrictions without consulting the cloud host OS."""

import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from solus_api.core.config import REPO_ROOT


class PlatformMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    display_name: str = Field(
        min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._+-]*$"
    )
    supported_platforms: list[Literal["linux", "darwin", "win32"]] = Field(
        min_length=1, max_length=3
    )


def platform_fields(server: str, *, root: Path | None = None) -> dict[str, object]:
    """Missing metadata is unrestricted; invalid metadata returns an empty support set."""
    fallback: dict[str, object] = {
        "display_name": server.replace("_", " ").capitalize(),
        "supported_platforms": [],
    }
    root = (root or REPO_ROOT / "integrations" / "mcp").resolve()
    path = root / server / "platform.json"
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            return fallback
        if not path.exists() and not path.is_symlink():
            return {**fallback, "supported_platforms": None}
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            return fallback
        with resolved.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return fallback
        return PlatformMetadata.model_validate_json(raw).model_dump()
    except (OSError, ValueError):
        return fallback
