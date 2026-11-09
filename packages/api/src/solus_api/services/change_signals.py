"""SOLUSDEV-321 P8 — each source's change token: the design signals of a decision.

`snapshot_signals` reads, for every source of a project, the token its connector leaves on
`Source.cursor` after a sync: a code host's commit `sha`, a design export's `content_sha`, a folder
scan's `digest`, else sha1 of the whole cursor. Together they say which version of the design a
decision was made against, so an outcome can later be read beside the changes that followed it.
A revision snapshot (a source standing in for an older commit of another) is left out, since its
base source already carries the design's position, and so is a source that has never synced. A
value is always a hex digest: other cursor text is hashed, never copied, so nothing a connector
keeps beside its token rides along.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import Source

#: The cursor keys whose value already is the source's change token, in order of preference.
TOKEN_KEYS: Final = ("sha", "content_sha", "digest")
_HEX: Final = re.compile(r"[0-9a-f]{1,128}")


def cursor_signal(cursor: Mapping[str, Any] | None) -> str | None:
    """A source's change token from its sync cursor; None before its first sync."""
    if not cursor:
        return None
    for key in TOKEN_KEYS:
        value = cursor.get(key)
        if isinstance(value, str) and _HEX.fullmatch(value):
            return value
    canonical = json.dumps(cursor, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode(), usedforsecurity=False).hexdigest()


async def snapshot_signals(session: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    """Source id → change token, for every synced source of the project but its snapshots."""
    rows = await session.execute(
        select(Source.id, Source.cursor).where(
            Source.project_id == project_id, Source.revision_base_source_id.is_(None)
        )
    )
    return {str(source): signal for source, cursor in rows if (signal := cursor_signal(cursor))}
