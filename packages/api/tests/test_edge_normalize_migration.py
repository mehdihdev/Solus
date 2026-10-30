"""The frozen sibling behind a32000000001 (SOLUSDEV-320): graph_edge normalisation."""

from __future__ import annotations

import sys
import uuid
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import pytest
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Team, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

API_DIR = Path(__file__).resolve().parents[1]


def _module() -> Any:
    name = "solus_edge_normalize_320_test"
    spec = spec_from_file_location(name, API_DIR / "migrations" / "edge_normalize.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _edge(project_id: uuid.UUID, src: GraphEntity, dst: GraphEntity, **kw: Any) -> GraphEdge:
    values: dict[str, Any] = {
        "project_id": project_id,
        "src_id": src.id,
        "dst_id": dst.id,
        "relation_type": "references",
        "domain_pair": "x",
        "origin": "manual",
        "attrs": {},
    }
    values.update(kw)
    return GraphEdge(**values)


async def _seed(db: AsyncSession) -> dict[str, GraphEdge]:
    team = Team(name="edge-normalize")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="edge-normalize")
    db.add(project)
    await db.flush()

    def entity(domain: Domain) -> GraphEntity:
        return GraphEntity(
            project_id=project.id, kind="thing", domain=domain, origin="manual", name="n"
        )

    plan, robot, brain, code_a, code_b = (
        entity(Domain.RUNTIME),
        entity(Domain.PROJECT),
        entity(Domain.ELECTRICAL),
        entity(Domain.CODE),
        entity(Domain.CODE),
    )
    db.add_all([plan, robot, brain, code_a, code_b])
    await db.flush()
    rows = {
        "colon": _edge(project.id, plan, brain, domain_pair="runtime:runtime", origin="system"),
        "reversed": _edge(
            project.id,
            robot,
            brain,
            domain_pair="project<->electrical",
            attrs={"evidence": [{"kind": "config", "ref": "user"}]},
        ),
        "legacy_evidence": _edge(
            project.id,
            robot,
            brain,
            relation_type="hardware_topology_member",
            domain_pair="electrical<->electrical",
            attrs={"managed_by": "m", "evidence": [{"by": "user", "source": "s"}]},
        ),
        "linking": _edge(
            project.id,
            code_a,
            code_b,
            relation_type="same_as",
            domain_pair="code<->code",
            origin="linking",
            confidence=0.9,
        ),
        "derived_tombstone": _edge(
            project.id,
            code_a,
            code_b,
            relation_type="clone_of",
            domain_pair="code<->code",
            origin="derived",
            deleted_at=utcnow(),
        ),
    }
    db.add_all(rows.values())
    await db.flush()
    return rows


async def test_normalize_edges_rewrites_pairs_evidence_and_origins(db: AsyncSession) -> None:
    module = _module()
    seeded = await _seed(db)

    def run(session: Session) -> dict[str, int]:
        return dict(module.normalize_edges(session.connection()))

    counts = await db.run_sync(run)
    assert counts == {
        "rows": 5,
        "pairs_rewritten": 3,
        "colon_before": 1,
        "evidence_added": 3,
        "evidence_converted": 1,
        "origins_rewritten": 2,
    }
    ids = {key: row.id for key, row in seeded.items()}
    db.expire_all()
    rows: dict[str, GraphEdge] = {}
    for key, edge_id in ids.items():
        row = await db.scalar(select(GraphEdge).where(GraphEdge.id == edge_id))
        assert row is not None, key
        rows[key] = row
    assert rows["colon"].domain_pair == "electrical<->runtime"
    assert rows["reversed"].domain_pair == "electrical<->project"
    assert rows["reversed"].attrs["evidence"] == [{"kind": "config", "ref": "user"}]
    assert rows["legacy_evidence"].domain_pair == "electrical<->project"
    assert rows["legacy_evidence"].attrs["evidence"] == [
        {"kind": "config", "ref": "user", "detail": "s"}
    ]
    assert rows["legacy_evidence"].attrs["managed_by"] == "m"
    assert rows["linking"].origin == "fingerprint"
    assert rows["derived_tombstone"].origin == "system"
    assert rows["derived_tombstone"].deleted_at is not None
    for row in rows.values():
        assert row.attrs["evidence"] is not None and "<->" in row.domain_pair

    again = await db.run_sync(run)
    assert again == {
        "rows": 5,
        "pairs_rewritten": 0,
        "colon_before": 0,
        "evidence_added": 0,
        "evidence_converted": 0,
        "origins_rewritten": 0,
    }


def test_dangling_endpoint_raises_naming_the_edge() -> None:
    module = _module()
    edge_id = uuid.uuid4()

    class _Result:
        def __init__(self, rows: list[Any]) -> None:
            self._rows = rows

        def all(self) -> list[Any]:
            return self._rows

        def scalar(self) -> Any:
            return self._rows[0]

    class _Connection:
        def execute(self, statement: Any, *args: Any, **kwargs: Any) -> _Result:
            text = str(statement)
            if "IS NULL" in text and "graph_entity" in text:
                return _Result([(edge_id,)])
            return _Result([0])

    with pytest.raises(RuntimeError, match=str(edge_id)):
        module.normalize_edges(_Connection())
