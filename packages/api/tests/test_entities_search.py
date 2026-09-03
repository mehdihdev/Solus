"""Entity name search — the `q` filter on `GET /projects/{id}/entities`.

`q` is the join the SOL composer's `@`-mention typeahead uses to turn what a
person is typing into a concrete graph entity, so it is now a user-facing search
box rather than an internal convenience.

It is matched with ILIKE, so it is escaped for exactly the reason
`external_ref_prefix` is (`test_entities_prefix.py`): an unescaped `%` collapses
the filter into "everything in the project". That is milder here than on the
prefix filter — `q` is already a substring search, and the rows stay
project-scoped either way — but it is still a search box that silently stops
filtering, which is both wrong and a quiet over-disclosure across the documents
a person was not asking about.
"""

from __future__ import annotations

import uuid
from typing import Any

from conftest import create_project, create_team, me
from httpx import AsyncClient
from solus_api.models import Domain, GraphEntity
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed(db: AsyncSession, project_id: uuid.UUID, names: list[str]) -> None:
    for name in names:
        db.add(
            GraphEntity(
                project_id=project_id,
                kind="part",
                domain=Domain.MECHANICAL,
                name=name,
                external_ref=f"docA:elem1:{name}",
                origin="connector",
            )
        )
    await db.commit()


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    await me(client, headers)
    team = await create_team(client, headers)
    project_id: str = (await create_project(client, headers, team["id"]))["id"]
    return project_id


async def _names(
    client: AsyncClient, headers: dict[str, str], project: str, **params: str
) -> set[str]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    resp = await client.get(f"/api/v1/projects/{project}/entities?{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    rows: list[dict[str, Any]] = resp.json()["data"]
    return {r["name"] for r in rows}


async def test_q_matches_a_name_substring_case_insensitively(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """The behaviour the typeahead rests on, which had no test at all."""
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["Camera Bracket", "Motor Mount", "bracket_lower"])

    assert await _names(client, alice_headers, project, q="brack") == {
        "Camera Bracket",
        "bracket_lower",
    }


async def test_a_wildcard_in_the_search_term_is_literal(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """An unescaped `%` turns the filter into "everything in the project" — the
    search box silently stops filtering."""
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["Camera Bracket", "Motor Mount"])

    assert await _names(client, alice_headers, project, q="%") == set()


async def test_an_underscore_is_literal_too(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """`_` is LIKE's single-character wildcard; `Brac_et` must not match
    `Bracket`, but must still match a name that really contains one."""
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["Bracket", "Brac_et"])

    assert await _names(client, alice_headers, project, q="Brac_et") == {"Brac_et"}


async def test_a_backslash_is_literal(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """The escape character itself must not be able to escape the escaping."""
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), [r"Brack\et", "Bracket"])

    assert await _names(client, alice_headers, project, q=r"Brack\et") == {r"Brack\et"}


async def test_search_is_project_scoped(
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    """A mention typeahead must never surface another team's part names."""
    alice_project = await _project(client, alice_headers)
    bob_project = await _project(client, bob_headers)
    await _seed(db, uuid.UUID(alice_project), ["Alice Bracket"])
    await _seed(db, uuid.UUID(bob_project), ["Bob Bracket"])

    assert await _names(client, alice_headers, alice_project, q="bracket") == {"Alice Bracket"}
    assert await _names(client, bob_headers, bob_project, q="bracket") == {"Bob Bracket"}


async def test_q_composes_with_the_other_filters(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    project = await _project(client, alice_headers)
    await _seed(db, uuid.UUID(project), ["Camera Bracket"])

    assert await _names(client, alice_headers, project, q="brack", type="part") == {
        "Camera Bracket"
    }
    assert await _names(client, alice_headers, project, q="brack", type="cad_body") == set()
