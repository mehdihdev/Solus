"""`services/local_links.py` (SOLUSDEV-249) — the derived `clone_of` edge between a
local clone and the project's matching GitHub/GitLab repo node. Real DB."""

from __future__ import annotations

import uuid
from typing import Any

from solus_api.connectors.code_host import REPO_ROOT_KEY
from solus_api.connectors.contracts import Domain, EntityOut, RelationOut, SyncResult
from solus_api.connectors.local_folder import CLONE_KEY
from solus_api.connectors.runtime import apply_sync_result
from solus_api.models import (
    GraphEdge,
    Membership,
    Project,
    Role,
    Source,
    SourceStatus,
    SourceType,
    Team,
    User,
)
from solus_api.services.local_links import CLONE_OF, DERIVED_ORIGIN, reconcile_local_links
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _project(db: AsyncSession) -> Project:
    user = User(supabase_user_id=f"sub-{uuid.uuid4().hex[:8]}", email="links@example.com")
    team = Team(name="Links")
    db.add_all([user, team])
    await db.flush()
    db.add(Membership(team_id=team.id, user_id=user.id, role=Role.OWNER))
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.flush()
    return project


async def _source(db: AsyncSession, project: Project, kind: SourceType, **config: Any) -> Source:
    source = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=kind,
        name=kind.value,
        status=SourceStatus.CONNECTED,
        config=config,
        cursor={},
    )
    db.add(source)
    await db.flush()
    return source


async def _land_repo(db: AsyncSession, source: Source) -> None:
    await apply_sync_result(
        db,
        source,
        SyncResult(
            entities=[
                EntityOut(
                    source_key=REPO_ROOT_KEY, type="code_repo", domain=Domain.CODE, name="rover"
                )
            ]
        ),
    )


async def _land_clone(db: AsyncSession, source: Source, remote: str | None, host: str) -> None:
    await apply_sync_result(
        db,
        source,
        SyncResult(
            entities=[
                EntityOut(source_key=CLONE_KEY, type="local_clone", domain=Domain.CODE, name="r"),
                EntityOut(
                    source_key="python:", type="python_code", domain=Domain.CODE, name="r (py)"
                ),
            ],
            relations=[RelationOut(from_key=CLONE_KEY, to_key="python:", type="contains")],
        ),
    )
    source.cursor = {"remote": remote, "host": host}
    await db.flush()


async def _clone_edges(db: AsyncSession, project: Project) -> list[GraphEdge]:
    rows = await db.scalars(
        select(GraphEdge).where(
            GraphEdge.project_id == project.id,
            GraphEdge.relation_type == CLONE_OF,
            GraphEdge.deleted_at.is_(None),
        )
    )
    return list(rows.all())


async def test_clone_links_to_matching_repo(db: AsyncSession) -> None:
    project = await _project(db)
    github = await _source(db, project, SourceType.GITHUB, repo="Org/Rover-FW", branch="main")
    local = await _source(db, project, SourceType.LOCAL, machine_id="a" * 32)
    await _land_repo(db, github)
    await _land_clone(db, local, "org/rover-fw", "github")  # case-folded match

    await reconcile_local_links(db, project.id)
    await db.commit()

    edges = await _clone_edges(db, project)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.origin == DERIVED_ORIGIN
    assert edge.source_id == local.id
    assert edge.domain_pair == "code<->code"
    assert edge.confidence == 1.0


async def test_no_matching_repo_means_no_edge(db: AsyncSession) -> None:
    project = await _project(db)
    github = await _source(db, project, SourceType.GITHUB, repo="org/other")
    local = await _source(db, project, SourceType.LOCAL, machine_id="a" * 32)
    await _land_repo(db, github)
    await _land_clone(db, local, "org/rover-fw", "github")

    await reconcile_local_links(db, project.id)
    assert await _clone_edges(db, project) == []


async def test_host_must_match(db: AsyncSession) -> None:
    project = await _project(db)
    gitlab = await _source(db, project, SourceType.GITLAB, repo="org/rover-fw")
    local = await _source(db, project, SourceType.LOCAL, machine_id="a" * 32)
    await _land_repo(db, gitlab)
    await _land_clone(db, local, "org/rover-fw", "github")

    await reconcile_local_links(db, project.id)
    assert await _clone_edges(db, project) == []


async def test_edge_survives_a_resync_and_goes_when_remote_changes(db: AsyncSession) -> None:
    project = await _project(db)
    github = await _source(db, project, SourceType.GITHUB, repo="org/rover-fw")
    local = await _source(db, project, SourceType.LOCAL, machine_id="a" * 32)
    await _land_repo(db, github)
    await _land_clone(db, local, "org/rover-fw", "github")
    await reconcile_local_links(db, project.id)
    await db.commit()
    (edge,) = await _clone_edges(db, project)

    # A plain re-sync of the local source must not tombstone the derived edge.
    await _land_clone(db, local, "org/rover-fw", "github")
    await reconcile_local_links(db, project.id)
    await db.commit()
    (again,) = await _clone_edges(db, project)
    assert again.id == edge.id

    # The remote moved elsewhere: the link is withdrawn, not left lying.
    await _land_clone(db, local, "org/elsewhere", "github")
    await reconcile_local_links(db, project.id)
    await db.commit()
    assert await _clone_edges(db, project) == []


async def test_repo_arriving_after_the_clone_links_on_the_repo_sync(db: AsyncSession) -> None:
    project = await _project(db)
    local = await _source(db, project, SourceType.LOCAL, machine_id="a" * 32)
    await _land_clone(db, local, "org/rover-fw", "github")
    await reconcile_local_links(db, project.id)
    assert await _clone_edges(db, project) == []

    github = await _source(db, project, SourceType.GITHUB, repo="org/rover-fw")
    await _land_repo(db, github)
    await reconcile_local_links(db, project.id)
    assert len(await _clone_edges(db, project)) == 1


async def test_two_machines_two_clones_one_repo(db: AsyncSession) -> None:
    project = await _project(db)
    github = await _source(db, project, SourceType.GITHUB, repo="org/rover-fw")
    a = await _source(db, project, SourceType.LOCAL, machine_id="a" * 32)
    b = await _source(db, project, SourceType.LOCAL, machine_id="b" * 32)
    await _land_repo(db, github)
    await _land_clone(db, a, "org/rover-fw", "github")
    await _land_clone(db, b, "org/rover-fw", "github")

    await reconcile_local_links(db, project.id)
    edges = await _clone_edges(db, project)
    assert {e.source_id for e in edges} == {a.id, b.id}


async def test_other_projects_are_untouched(db: AsyncSession) -> None:
    p1 = await _project(db)
    p2 = await _project(db)
    github = await _source(db, p2, SourceType.GITHUB, repo="org/rover-fw")
    local = await _source(db, p1, SourceType.LOCAL, machine_id="a" * 32)
    await _land_repo(db, github)
    await _land_clone(db, local, "org/rover-fw", "github")

    await reconcile_local_links(db, p1.id)
    assert await _clone_edges(db, p1) == []
    assert await _clone_edges(db, p2) == []
