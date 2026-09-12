"""Impact focus and canonical seeds honor the personal revision graph view."""

import pytest
from solus_api.graph.read_scope import GraphReadScope, bind_scope
from solus_api.impact.engine import _canonical_siblings, _load_focus
from solus_api.models import Domain, GraphEntity, Project, Source, SourceType, Team
from sqlalchemy.ext.asyncio import AsyncSession


async def test_focus_and_canonical_siblings_respect_selected_revision(db: AsyncSession) -> None:
    team = Team(name="impact")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="robot")
    db.add(project)
    await db.flush()
    base = Source(project_id=project.id, team_id=team.id, type=SourceType.GITHUB, name="base")
    db.add(base)
    await db.flush()
    snapshot = Source(
        project_id=project.id,
        team_id=team.id,
        type=SourceType.GITHUB,
        name="revision",
        revision_base_source_id=base.id,
    )
    db.add(snapshot)
    await db.flush()
    canonical = GraphEntity(
        project_id=project.id,
        name="canonical",
        kind="canonical_part",
        origin="fingerprint",
        domain=Domain.CODE,
    )
    db.add(canonical)
    await db.flush()
    ordinary = GraphEntity(
        project_id=project.id,
        source_id=base.id,
        name="base",
        kind="code_file",
        domain=Domain.CODE,
        canonical_part_id=canonical.id,
    )
    hidden = GraphEntity(
        project_id=project.id,
        source_id=snapshot.id,
        name="revision",
        kind="code_file",
        domain=Domain.CODE,
        canonical_part_id=canonical.id,
    )
    db.add_all([ordinary, hidden])
    await db.flush()
    with pytest.raises(ValueError):
        await _load_focus(db, project.id, hidden.id)
    assert await _canonical_siblings(db, project.id, canonical) == [ordinary.id]
    with bind_scope(GraphReadScope(project.id, ((base.id, snapshot.id),))):
        assert await _load_focus(db, project.id, hidden.id) is hidden
        with pytest.raises(ValueError):
            await _load_focus(db, project.id, ordinary.id)
        assert await _canonical_siblings(db, project.id, canonical) == [hidden.id]
