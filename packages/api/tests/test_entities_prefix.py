"""`external_ref` prefix filtering — SOLUS-A7-01.

The Onshape panel knows only what Onshape tells it: a document id and an element
id. Graph entities are keyed `{document_id}:{element_id}:{occurrence_path}`
(`connectors/mechanical.py`), so that prefix is the ONLY join the panel has —
there is no face-level key, deliberately.

Without this filter a panel would have to page the whole project's entities over
the wire and filter client-side, which is both slow and a quiet
over-disclosure: it would ship parts from documents the panel is not looking at.

The prefix is matched with LIKE, so it is escaped: an `external_ref` is
Onshape-derived and a `%` in one would otherwise widen the query to the whole
project — the same class of bug as an unescaped search term.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import Domain, GraphEntity
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(db: AsyncSession, project_id: uuid.UUID, refs: list[str]) -> None:
    for ref in refs:
        db.add(
            GraphEntity(
                project_id=project_id,
                kind="part",
                domain=Domain.MECHANICAL,
                name=ref.rsplit(":", 1)[-1],
                external_ref=ref,
                origin="connector",
            )
        )
    await db.commit()


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project_id: str = (await create_project(client, headers, team["id"]))["id"]
    return project_id


async def _list(
    client: AsyncClient, headers: dict[str, str], project: str, **params: str
) -> list[dict[str, Any]]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    resp = await client.get(f"/api/v1/projects/{project}/entities?{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    rows: list[dict[str, Any]] = resp.json()["data"]
    return rows


async def test_prefix_selects_only_that_document_and_element(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    await _seed(
        db,
        uuid.UUID(project),
        [
            "docA:elem1:Rover/Bracket",
            "docA:elem1:Rover/Peg[0]",
            "docA:elem2:Other/Thing",
            "docB:elem1:Rover/Bracket",
        ],
    )

    rows = await _list(client, alice_headers, project, external_ref_prefix="docA:elem1:")

    assert {r["source_key"] for r in rows} == {
        "docA:elem1:Rover/Bracket",
        "docA:elem1:Rover/Peg[0]",
    }


async def test_a_wildcard_in_the_prefix_is_literal_not_a_widening_match(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """An unescaped `%` would return the whole project — over-disclosure to a
    panel that asked about one document."""
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["docA:elem1:Rover/Bracket", "docB:elem9:Other/Thing"])

    rows = await _list(client, alice_headers, project, external_ref_prefix="%")

    assert rows == []


async def test_an_underscore_is_literal_too(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """`_` is LIKE's single-character wildcard; `doc_` must not match `docA`."""
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["docA:elem1:Rover/Bracket"])

    assert await _list(client, alice_headers, project, external_ref_prefix="doc_") == []


async def test_it_anchors_at_the_start(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """A PREFIX filter, not a substring search — `elem1:` must not match a ref
    whose element appears mid-key."""
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["docA:elem1:Rover/Bracket"])

    assert await _list(client, alice_headers, project, external_ref_prefix="elem1:") == []


async def test_it_composes_with_the_other_filters(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["docA:elem1:Rover/Bracket"])

    assert await _list(
        client, alice_headers, project, external_ref_prefix="docA:elem1:", type="part"
    )
    assert (
        await _list(
            client, alice_headers, project, external_ref_prefix="docA:elem1:", type="cad_body"
        )
        == []
    )


async def test_another_teams_document_is_never_returned(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """Tenant scoping is unchanged by the new filter — the highest-severity
    invariant, and a prefix filter is exactly the shape that could bypass it if
    it were applied before the project scope."""
    alice_project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(alice_project), ["docA:elem1:Rover/Secret"])

    resp = await client.get(
        f"/api/v1/projects/{alice_project}/entities?external_ref_prefix=docA:elem1:",
        headers=bob_headers,
    )

    assert resp.status_code == 404


@pytest.mark.parametrize("prefix", ["", " "])
async def test_a_blank_prefix_is_ignored_rather_than_matching_everything(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, prefix: str
) -> None:
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["docA:elem1:Rover/Bracket"])

    rows = await _list(client, alice_headers, project, external_ref_prefix=prefix)

    assert len(rows) == 1
