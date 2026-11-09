"""SOLUSDEV-321 P8 — `snapshot_signals`: each source's change token at the moment of a decision.

One value per source of the project, keyed by the source's id: a code host's commit `sha`, a
design export's `content_sha`, a folder scan's `digest`, else sha1 of the whole cursor. A revision
snapshot (a source standing in for an older commit of another) is left out — its base already says
where the design is — and so is a source that has never synced. Only a hex digest reaches a value:
a cursor's other text is hashed, never copied.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from solus_api.models import Project, Source, SourceType, Team
from solus_api.services.change_signals import snapshot_signals
from sqlalchemy.ext.asyncio import AsyncSession


async def _team_project(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    team = Team(name="T")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="P")
    db.add(project)
    await db.flush()
    return team.id, project.id


async def _synced(
    db: AsyncSession,
    team_id: uuid.UUID,
    project_id: uuid.UUID,
    cursor: dict[str, Any],
    *,
    base: uuid.UUID | None = None,
) -> uuid.UUID:
    source = Source(
        project_id=project_id,
        team_id=team_id,
        type=SourceType.GITHUB,
        name="source",
        cursor=cursor,
        revision_base_source_id=base,
    )
    db.add(source)
    await db.flush()
    return source.id


def _sha1(cursor: dict[str, Any]) -> str:
    canonical = json.dumps(cursor, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode(), usedforsecurity=False).hexdigest()


async def test_snapshot_excludes_revision_sources(db: AsyncSession) -> None:
    team_id, project_id = await _team_project(db)
    other_team, elsewhere = await _team_project(db)
    commit = "a" * 40
    code = await _synced(db, team_id, project_id, {"branch": "main", "sha": commit})
    board = await _synced(db, team_id, project_id, {"content_sha": "b" * 64})
    folder = await _synced(db, team_id, project_id, {"digest": "c" * 64, "files": 3})
    cad_cursor = {"microversions": {"doc-1": "mv-7"}, "projection_version": 2}
    cad = await _synced(db, team_id, project_id, cad_cursor)
    # Text that is not a digest is hashed with the rest of its cursor, never copied.
    odd_cursor = {"sha": "ghp_not-a-digest", "etag": 'W/"x"'}
    odd = await _synced(db, team_id, project_id, odd_cursor)
    await _synced(db, team_id, project_id, {"sha": "d" * 40}, base=code)  # a revision snapshot
    await _synced(db, team_id, project_id, {})  # never synced: no token yet
    await _synced(db, other_team, elsewhere, {"sha": "e" * 40})  # another project's
    await db.commit()

    signals = await snapshot_signals(db, project_id)

    assert signals == {
        str(code): commit,
        str(board): "b" * 64,
        str(folder): "c" * 64,
        str(cad): _sha1(cad_cursor),
        str(odd): _sha1(odd_cursor),
    }
    assert not any("ghp_" in value for value in signals.values())
    assert await snapshot_signals(db, uuid.uuid4()) == {}
