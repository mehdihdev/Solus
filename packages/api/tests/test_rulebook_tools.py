"""SOLUSDEV-321 P3-T4 — `extract_rulebook` (`agent/tools/rulebook_tools.py`, R58).

A rulebook PDF filed in the project's `.solus` is read through `read_document`'s own extractor: the
rendered pages, one metered vision call a page with `purpose="extract"`, and page-cited proposals.
Each proposal that states a number, a unit and a bound becomes a candidate row
`{payload, text, page, quote}` in the tool's RESULT.

Nothing is written. A candidate becomes a constraint only when the person files its text and sets
its payload through `PATCH /solus/entries/{id}/payload`. Every model call here goes to a scripted
gateway; no provider is reached.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from conftest import create_project, create_team, me
from fixtures.datasheet import two_page_pdf
from solus_api.agent.documents.extract import DocumentProposal
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools.rulebook_tools import (
    EXTRACT_RULEBOOK_DESCRIPTOR,
    register_rulebook_tool,
    rulebook_rows,
)
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import SolusEntry, SolusSection
from solus_api.orchestration import gateway
from solus_api.services.artifacts import create_artifact
from solus_api.services.solus_config import add_artifact_entry, add_text_entry
from solus_api.storage import LocalArtifactStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def _rule_line(kind: str, name: str, value: str, unit: str | None, quote: str) -> str:
    return json.dumps({"kind": kind, "name": name, "value": value, "unit": unit, "quote": quote})


PAGE_ONE: Final = "\n".join(
    [
        _rule_line("rating", "Maximum accumulator voltage", "600", "V", "must not exceed 600 V DC"),
        _rule_line("dimension", "Minimum wall thickness", "1.2", "mm", "walls of at least 1.2 mm"),
        _rule_line("other", "part", "FSAE", None, "Formula SAE rules"),
        _rule_line("rating", "supply voltage", "1.71 to 3.6", "V", "VDD 1.71 V to 3.6 V"),
    ]
)
PAGE_TWO: Final = _rule_line("timing", "maximum brake response", "100", "ms", "no more than 100 ms")


class _Completion:
    def __init__(self, text: str) -> None:
        self.text = text


def _scripted_pages(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """gateway.complete → page one's read, then page two's, recording each call."""
    calls: list[dict[str, Any]] = []

    async def complete(query: str, **kw: Any) -> _Completion:
        calls.append({"query": query, **kw})
        return _Completion(PAGE_ONE if len(calls) == 1 else PAGE_TWO)

    monkeypatch.setattr(gateway, "complete", complete)
    return calls


async def _rulebook_project(
    client: httpx.AsyncClient, headers: dict[str, str], db: AsyncSession, store: LocalArtifactStore
) -> dict[str, Any]:
    """A project (through the routes) whose `.solus` holds a rulebook PDF in documentation/guides,
    and a text entry beside it."""
    user = await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    project_id, user_id = uuid.UUID(project["id"]), uuid.UUID(user["id"])
    artifact = await create_artifact(
        db,
        store,
        project_id=project_id,
        created_by=user_id,
        data=two_page_pdf(title="Rulebook 2027"),
        media_type="application/pdf",
        source_tool="test",
        tool_call_id=None,
    )
    rulebook = await add_artifact_entry(
        db,
        project_id,
        SolusSection.DOCUMENTATION,
        artifact_id=artifact.id,
        name="rules.pdf",
        created_by=user_id,
        subsection="guides",
    )
    note = await add_text_entry(
        db, project_id, SolusSection.GOALS, "win endurance", author="user", created_by=user_id
    )
    await db.commit()
    return {
        "project_id": project_id,
        "team_id": team["id"],
        "user_id": user_id,
        "entry_id": rulebook.id,
        "note_id": note.id,
    }


def _rulebook_registry(
    engine: AsyncEngine, store: LocalArtifactStore, project_id: uuid.UUID, user_id: uuid.UUID
) -> ToolRegistry:
    registry = ToolRegistry()
    register_rulebook_tool(
        registry,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        store=store,
        project_id=project_id,
        user_id=user_id,
        secret_store=InMemorySecretStore(),
        redis=None,
        enqueue=None,
    )
    return registry


async def _entry_snapshot(db: AsyncSession, project_id: uuid.UUID) -> list[tuple[Any, ...]]:
    """Every `.solus` entry of the project, live or not, with what it holds."""
    rows = await db.execute(
        select(
            SolusEntry.id,
            SolusEntry.section,
            SolusEntry.subsection,
            SolusEntry.kind,
            SolusEntry.text,
            SolusEntry.payload,
            SolusEntry.deleted_at,
        )
        .where(SolusEntry.project_id == project_id)
        .order_by(SolusEntry.id)
    )
    return [tuple(row) for row in rows]


async def test_nothing_becomes_a_constraint_unconfirmed(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R58: the tool returns candidate rows and writes NOTHING. No `.solus` entry appears and no
    payload changes. Each row is what the existing confirm path takes: file its `text` as a
    constraints entry, then PATCH its `payload` onto that entry."""
    store = LocalArtifactStore(str(tmp_path))
    seeded = await _rulebook_project(client, alice_headers, db, store)
    calls = _scripted_pages(monkeypatch)
    before = await _entry_snapshot(db, seeded["project_id"])
    registry = _rulebook_registry(engine, store, seeded["project_id"], seeded["user_id"])
    from solus_api.agent.turn_context import bind_turn_id

    turn_id = uuid.uuid4()
    with bind_turn_id(turn_id):  # as the runner calls it inside a SOL turn (R83)
        result = await registry.invoke(
            ToolCall(tool="extract_rulebook", args={"entry_id": str(seeded["entry_id"])})
        )

    assert result.ok, result.error
    value = result.value or {}
    assert await _entry_snapshot(db, seeded["project_id"]) == before
    assert (value["section"], value["subsection"]) == ("constraints", "rules")
    assert value["pages_read"] == [1, 2] and value["truncated"] is False
    page_reads = [(c["purpose"], c["user_id"], c.get("turn_id")) for c in calls]
    assert page_reads == [("extract", seeded["user_id"], turn_id)] * 2
    voltage, wall, brake = value["rows"]
    assert voltage["payload"] == {
        "quantity": "accumulator_voltage",
        "limit": 600.0,
        "unit": "V",
        "comparator": "<=",
        "scope_entity_ids": [],
        "source_entry_id": str(seeded["entry_id"]),
        "excluded_suppliers": [],
        "required_certifications": [],
    }
    assert (voltage["page"], voltage["quote"]) == (1, "must not exceed 600 V DC")
    assert "600" in voltage["text"] and "page 1" in voltage["text"]
    assert (wall["payload"]["comparator"], wall["payload"]["limit"]) == (">=", 1.2)
    assert (brake["page"], brake["payload"]["quantity"]) == (2, "brake_response")
    assert any("2 proposal" in note for note in value["notes"])

    project = str(seeded["project_id"])
    filed = await client.post(
        f"/api/v1/projects/{project}/solus/constraints/entries",
        json={"kind": "text", "text": voltage["text"], "subsection": "rules"},
        headers=alice_headers,
    )
    assert filed.status_code == 201, filed.text
    entry_id = filed.json()["data"]["id"]
    confirmed = await client.patch(
        f"/api/v1/projects/{project}/solus/entries/{entry_id}/payload",
        json={"payload": voltage["payload"]},
        headers=alice_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["payload"] == voltage["payload"]


async def test_an_unknown_foreign_or_non_document_entry_is_refused(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entry is resolved in the bound project only. An unknown id and another project's
    rulebook are both `not_found`, so there is no existence oracle. A text entry is no document.
    None of these reaches the model."""
    store = LocalArtifactStore(str(tmp_path))
    seeded = await _rulebook_project(client, alice_headers, db, store)
    other = await create_project(client, alice_headers, seeded["team_id"])
    calls = _scripted_pages(monkeypatch)
    theirs = _rulebook_registry(engine, store, uuid.UUID(other["id"]), seeded["user_id"])
    mine = _rulebook_registry(engine, store, seeded["project_id"], seeded["user_id"])

    async def refusal(registry: ToolRegistry, entry_id: uuid.UUID) -> ToolErrorCode | None:
        call = ToolCall(tool="extract_rulebook", args={"entry_id": str(entry_id)})
        result = await registry.invoke(call)
        return result.error.code if result.error is not None else None

    assert await refusal(mine, uuid.uuid4()) is ToolErrorCode.NOT_FOUND
    assert await refusal(theirs, seeded["entry_id"]) is ToolErrorCode.NOT_FOUND
    assert await refusal(mine, seeded["note_id"]) is ToolErrorCode.INVALID_ARGS
    assert calls == []
    assert EXTRACT_RULEBOOK_DESCRIPTOR.requires_confirmation is False


async def test_the_rows_fit_the_result_cap_whole(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m8: rows are added while the whole result, encoded as the prompt layer encodes it, fits
    the descriptor's cap. The rest are counted in `notes`, never cut mid-row. A non-ASCII quote
    grows six-fold as `\\uXXXX` escapes, so twenty rows of them pass the cap."""
    from solus_api.agent.prompt import _encode

    store = LocalArtifactStore(str(tmp_path))
    seeded = await _rulebook_project(client, alice_headers, db, store)
    page = "\n".join(
        _rule_line("rating", f"Maximum supply {n}", str(n + 1), "V", "must not exceed " + "Ω" * 200)
        for n in range(40)
    )

    async def complete(query: str, **kw: Any) -> _Completion:
        return _Completion(page)

    monkeypatch.setattr(gateway, "complete", complete)
    registry = _rulebook_registry(engine, store, seeded["project_id"], seeded["user_id"])

    result = await registry.invoke(
        ToolCall(tool="extract_rulebook", args={"entry_id": str(seeded["entry_id"])})
    )

    assert result.ok, result.error
    value = result.value or {}
    encoded = _encode({"ok": True, "value": value}, 10**9)
    assert len(encoded) <= (EXTRACT_RULEBOOK_DESCRIPTOR.result_cap or 0)
    kept = len(value["rows"])
    assert 0 < kept < 80
    assert any(f"{80 - kept} more candidate(s)" in note for note in value["notes"])


def test_rows_carry_only_a_stated_number_unit_and_bound() -> None:
    """A proposal becomes a row only with a single finite number, a unit and a bound word. The
    bound word becomes the comparator, and the name, without it, becomes the quantity."""
    entry_id = uuid.uuid4()

    def stated(kind: str, name: str, value: str, unit: str | None, quote: str) -> DocumentProposal:
        return DocumentProposal(kind=kind, name=name, value=value, unit=unit, page=3, quote=quote)  # type: ignore[arg-type]

    rows, skipped = rulebook_rows(
        [
            stated("rating", "Track width", "2", "m", "at least 2 m wide"),
            stated("rating", "Noise", "110", "dBC", "less than 110 dBC"),
            stated("dimension", "Ground clearance", "30", "mm", "greater than 30 mm"),
            stated("rating", "Current", "200", "A", "rated 200 A"),  # no bound word
            stated("rating", "Voltage", "nan", "V", "at most nan V"),  # no number
            stated("pinout", "max pins", "8", None, "max 8"),  # no unit, not a limit kind
        ],
        entry_id=entry_id,
    )

    assert [(r["payload"]["quantity"], r["payload"]["comparator"]) for r in rows] == [
        ("track_width", ">="),
        ("noise", "<"),
        ("ground_clearance", ">"),
    ]
    assert skipped == 3
    assert all(r["payload"]["source_entry_id"] == str(entry_id) for r in rows)
