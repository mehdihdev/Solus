"""Private file access capability for an authenticated, loaded local runner only.

Callers supply server-verified project/user IDs. Never construct this capability
for a cloud request; opaque source references alone confer no file authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from solus_contracts.hardware_local_state import (
    HARDWARE_LOCAL_STATE_MAX_BYTES,
    HardwareLocalAccount,
    HardwareLocalState,
)

_REF = re.compile(r"source:([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\Z")
_FORMATS = {".json", ".yaml", ".yml", ".toml", ".py"}
MAX_SOURCE_BYTES = 256 * 1024


class LocalSourceError(Exception):
    """Portable failure code: native paths and parser input never enter errors."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VerifiedHardwareSource:
    source_ref: str
    suffix: str
    content: bytes = field(repr=False)


def _read_regular(path: Path, limit: int) -> bytes:
    """Use one bounded descriptor; refuse symlinks and changes during the read."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise LocalSourceError("relink_required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise LocalSourceError("relink_required")
        chunks = []
        size = 0
        while size <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = path.lstat()
        if (
            size > limit
            or not stat.S_ISREG(after.st_mode)
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            or path.resolve(strict=True) != path
        ):
            raise LocalSourceError("relink_required")
        content = b"".join(chunks)
        content.decode("utf-8", errors="strict")
        return content
    finally:
        os.close(descriptor)


class LocalHardwareSources:
    def __init__(self, home: Path) -> None:
        self._home = home

    @classmethod
    def for_local_runner(
        cls, runner: object | None, *, home: Path | None = None
    ) -> LocalHardwareSources:
        if runner is None:
            raise LocalSourceError("source_unavailable")
        return cls(home if home is not None else Path.home())

    def _account(self, project: uuid.UUID, account: uuid.UUID) -> HardwareLocalAccount | None:
        if not isinstance(project, uuid.UUID) or not isinstance(account, uuid.UUID):
            raise LocalSourceError("invalid")
        path = self._home / ".solus" / "projects" / str(project) / "hardware.json"
        try:
            content = _read_regular(path, HARDWARE_LOCAL_STATE_MAX_BYTES)
            document = json.loads(content)
            if isinstance(document, dict):
                version = document.get("schema_version")
                if type(version) is int and version > 1:
                    raise LocalSourceError("newer")
            state = HardwareLocalState.model_validate(document)
            return state.accounts.get(str(account))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            raise LocalSourceError("relink_required") from None

    def read_source(
        self, project_id: uuid.UUID, account_id: uuid.UUID, source_ref: str
    ) -> VerifiedHardwareSource:
        match = _REF.fullmatch(source_ref)
        if match is None:
            raise LocalSourceError("invalid")
        account = self._account(project_id, account_id)
        source = account.sources.get(match[1]) if account is not None else None
        if source is None:
            raise LocalSourceError("not_found")
        path = Path(source.path)
        if path.suffix.lower() not in _FORMATS:
            raise LocalSourceError("relink_required")
        try:
            content = _read_regular(path, MAX_SOURCE_BYTES)
        except (OSError, ValueError):
            raise LocalSourceError("relink_required") from None
        if hashlib.sha256(content).hexdigest() != source.content_sha256:
            raise LocalSourceError("source_changed")
        return VerifiedHardwareSource(source_ref, path.suffix.lower(), content)

    def binding_hint(
        self, project_id: uuid.UUID, account_id: uuid.UUID, entry_id: uuid.UUID
    ) -> str | None:
        if not isinstance(entry_id, uuid.UUID):
            raise LocalSourceError("invalid")
        account = self._account(project_id, account_id)
        binding = account.bindings.get(str(entry_id)) if account is not None else None
        return binding.last_seen_path if binding is not None else None
