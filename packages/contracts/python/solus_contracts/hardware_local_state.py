"""ADR-034 private hardware paths/hints; wire twin of hardware-local-state.ts.

Desktop MAIN writes; an authenticated local runner reads its account's opaque
references. This document is never synced or included in model context. Bound
raw file bytes before decoding. Corrupt/newer files must not be overwritten.
"""

import json
import re
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

HARDWARE_LOCAL_STATE_SCHEMA_VERSION = 1
HARDWARE_LOCAL_STATE_FILENAME = "hardware.json"
HARDWARE_LOCAL_STATE_MAX_BYTES = 256 * 1024

_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_ABSOLUTE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)")
_Id = Annotated[
    str, StringConstraints(strict=True, min_length=36, max_length=36, pattern=_UUID_PATTERN)
]


class HardwareLocalSource(BaseModel):
    """A picker-authorized local source, referenced by opaque UUID in shared data."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    path: str = Field(min_length=1, max_length=4096)
    content_sha256: str = Field(
        alias="contentSha256", min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )

    @field_validator("path")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        if _CONTROL.search(value) or not _ABSOLUTE.match(value):
            raise ValueError("source path must be absolute and contain no control characters")
        return value


class HardwareLocalBinding(BaseModel):
    """A convenience hint only: never durable ambiguous-port consent."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    last_seen_path: str | None = Field(
        default=None, alias="lastSeenPath", min_length=1, max_length=512
    )

    @field_validator("last_seen_path", mode="before")
    @classmethod
    def _path_text(cls, value: object) -> object:
        if not isinstance(value, str) or _CONTROL.search(value):
            raise ValueError("port hint must be text without control characters")
        return value


class HardwareLocalAccount(BaseModel):
    """Sources and connection hints scoped to one authenticated user UUID."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    sources: dict[_Id, HardwareLocalSource] = Field(max_length=256)
    bindings: dict[_Id, HardwareLocalBinding] = Field(max_length=256)


class HardwareLocalState(BaseModel):
    """The complete projects/<projectId>/hardware.json private document."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1]
    accounts: dict[_Id, HardwareLocalAccount] = Field(max_length=16)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _integer_version(cls, value: object) -> object:
        # JSON's 1 and 1.0 become the same JS number in the TypeScript twin.
        if isinstance(value, float) and value == 1:
            return 1
        if type(value) is not int:
            raise ValueError("schema version must be an integer")
        return value

    @model_validator(mode="after")
    def _encoded_size(self) -> Self:
        wire = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        encoded = json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > HARDWARE_LOCAL_STATE_MAX_BYTES:
            raise ValueError("hardware local state exceeds the byte limit")
        return self
