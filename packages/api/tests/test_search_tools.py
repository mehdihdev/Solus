"""SOLUSDEV-321 P1-T4 — SOL's three search tools: the graph, `.solus` and the practice corpus.

Driven through `register_search_tools` on a real `ToolRegistry` against the real database. The
project is bound by Solus code at registration, so a second project proves no argument the model
supplies can leave it; the corpus is global by design (no tenant exists to scope by).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from corpus.corpus_helpers import authored, write_tree
from solus_api.agent.tools import ToolCall, ToolErrorCode, ToolRegistry, ToolResult, search_tools
from solus_api.agent.tools.read_tool import MAX_ROWS, MORE, TRUNCATED
from solus_api.agent.tools.search_tools import register_search_tools, search_workspace_handler
from solus_api.corpus.chunking import build_manifest, load_content_tree, load_release
from solus_api.corpus.ingest import ingest_corpus
from solus_api.corpus.schema import CorpusChunkRow
from solus_api.models import Domain, GraphEntity, Project, SolusSection, Team
from solus_api.services.solus_config import add_text_entry
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]

LOOP = "corpus:electrical/decoupling/loop-area"
LOW = "corpus:electrical/wire_gauge/voltage-drop-rule"


def _maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _new_project(maker: Maker) -> uuid.UUID:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="Rover")
        db.add(project)
        await db.commit()
        return project.id


async def _seed_part(
    maker: Maker,
    project_id: uuid.UUID,
    name: str,
    *,
    kind: str = "component",
    domain: Domain = Domain.ELECTRICAL,
) -> GraphEntity:
    async with maker() as db:
        part = GraphEntity(
            project_id=project_id, kind=kind, domain=domain, origin="manual", name=name
        )
        db.add(part)
        await db.commit()
        return part


async def _seed_entry(maker: Maker, project_id: uuid.UUID, section: SolusSection, text: str) -> Any:
    async with maker() as db:
        entry = await add_text_entry(db, project_id, section, text, author="user", created_by=None)
        await db.commit()
        return entry


def _registry_of(maker: Maker, project_id: uuid.UUID) -> ToolRegistry:
    registry = ToolRegistry()
    register_search_tools(registry, maker, project_id)
    return registry


async def _invoke(registry: ToolRegistry, tool: str, **args: Any) -> ToolResult:
    return await registry.invoke(ToolCall(tool=tool, args=args))


def _ok_text(result: ToolResult) -> str:
    assert result.ok, result.error
    assert result.value is not None
    return str(result.value["text"])


def _json_rows(text: str) -> list[dict[str, Any]]:
    """A result's Mapping rows: each is one compact JSON object on its own line."""
    return [json.loads(line) for line in text.split("\n") if line.startswith("{")]


async def _ingest_tree(db: AsyncSession, root: Path) -> None:
    manifest = build_manifest(load_content_tree(root), load_release(root))
    (root / "manifest.json").write_text(json.dumps(manifest) + "\n")
    await ingest_corpus(db, root=root)
    await db.commit()


def _corpus_files() -> dict[str, str]:
    return {
        "electrical/decoupling/loop-area.md": authored(
            "Loop inductance through the capacitor and the IC pins sets decoupling."
        ),
        "electrical/wire_gauge/voltage-drop-rule.md": authored(
            "Wire gauge in a robot is set by voltage drop over the run, not the ampacity table.",
            title='"Voltage drop sizes robot wiring"',
            confidence="0.5",
            confidence_basis='"rule_of_thumb"',
            kind='"rule_of_thumb"',
            audience='"reference"',
        ),
        "electrical/decoupling/draft-idea.md": authored(
            "An unreviewed thought about decoupling capacitor placement.",
            title='"Draft"',
            status='"draft"',
        ),
    }


# --------------------------------------------------------------------- the registry


async def test_the_three_tools_register_read_only_and_ungated(engine: AsyncEngine) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4())
    descriptors = {d.name: d for d in registry.list()}
    assert set(descriptors) == {"search_workspace", "search_solus", "search_corpus"}
    for descriptor in descriptors.values():
        assert descriptor.requires_confirmation is False
        assert descriptor.files_errors is False
        assert descriptor.result_cap == 8_000
        assert "Read-only" in descriptor.description
        assert descriptor.params["required"] == ["q"]


# ---------------------------------------------------------------- search_workspace


async def test_search_workspace_finds_an_entity_by_name_and_says_why(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    servo = await _seed_part(maker, project_id, "servo 3 (joint 3)")
    await _seed_part(maker, project_id, "Battery pack")
    result = await _invoke(_registry_of(maker, project_id), "search_workspace", q="servo 3")
    text = _ok_text(result)
    (row,) = _json_rows(text)
    assert row["name"] == "servo 3 (joint 3)"
    assert row["id"] == str(servo.id)
    assert (row["kind"], row["domain"]) == ("component", "electrical")
    assert "why" in row
    assert "Battery pack" not in text


async def test_search_workspace_with_no_match_says_so(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    await _seed_part(maker, project_id, "servo 3")
    registry = _registry_of(maker, project_id)
    assert _ok_text(await _invoke(registry, "search_workspace", q="zzqx")) == "no results"


async def test_search_workspace_never_leaves_the_project_or_reads_the_workspace_layer(
    engine: AsyncEngine,
) -> None:
    maker = _maker(engine)
    mine, theirs = await _new_project(maker), await _new_project(maker)
    ours = await _seed_part(maker, mine, "servo 3")
    foreign = await _seed_part(maker, theirs, "servo 3")
    widget = await _seed_part(
        maker, mine, "servo 3 widget", kind="solus:widget", domain=Domain.WORKSPACE
    )
    registry = _registry_of(maker, mine)
    text = _ok_text(await _invoke(registry, "search_workspace", q="servo 3"))
    assert str(ours.id) in text
    assert str(foreign.id) not in text
    assert str(widget.id) not in text
    smuggled = await _invoke(registry, "search_workspace", q="servo 3", project_id=str(theirs))
    assert smuggled.error is not None
    assert smuggled.error.code is ToolErrorCode.INVALID_ARGS


async def test_search_results_capped_at_20_and_result_cap(engine: AsyncEngine) -> None:
    """The schema refuses a `limit` over 20; the handler clamps whatever reaches it anyway."""
    maker = _maker(engine)
    project_id = await _new_project(maker)
    async with maker() as db:
        db.add_all(
            GraphEntity(
                project_id=project_id,
                kind="component",
                domain=Domain.MECHANICAL,
                origin="manual",
                name=f"bolt {n}",
            )
            for n in range(MAX_ROWS + 5)
        )
        await db.commit()
    registry = _registry_of(maker, project_id)
    text = _ok_text(await _invoke(registry, "search_workspace", q="bolt", limit=MAX_ROWS))
    *shown, marker = text.split("\n")  # 25 exist, so the 21st row makes the cut a marked one
    assert len(shown) == MAX_ROWS
    assert marker == TRUNCATED
    refused = await _invoke(registry, "search_workspace", q="bolt", limit=500)
    assert refused.error is not None
    assert refused.error.code is ToolErrorCode.INVALID_ARGS
    rows = await search_workspace_handler(
        {"q": "bolt", "limit": 500}, sessions=maker, project_id=project_id
    )
    assert sum(not isinstance(row, str) for row in rows) == MAX_ROWS


async def test_search_workspace_says_so_when_the_limit_hid_more(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    for n in range(4):
        await _seed_part(maker, project_id, f"bolt {n}")
    registry = _registry_of(maker, project_id)
    cut = _ok_text(await _invoke(registry, "search_workspace", q="bolt", limit=3)).split("\n")
    assert len(_json_rows("\n".join(cut))) == 3
    assert cut[-1] == MORE
    for limit in (4, 10):  # everything fit: no marker, nothing hidden
        whole = _ok_text(await _invoke(registry, "search_workspace", q="bolt", limit=limit))
        assert len(_json_rows(whole)) == 4
        assert MORE not in whole


# ------------------------------------------------------------------- search_solus


async def test_search_solus_finds_an_entry_and_names_its_section(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    goal = await _seed_entry(maker, project_id, SolusSection.GOALS, "Ship the arm by March")
    await _seed_entry(
        maker, project_id, SolusSection.DOCUMENTATION, "The datasheet is on the drive"
    )
    text = _ok_text(
        await _invoke(_registry_of(maker, project_id), "search_solus", q="ship the arm")
    )
    (row,) = _json_rows(text)
    assert row["id"] == str(goal.id)
    assert row["section"] == "goals"
    assert row["text"] == "Ship the arm by March"
    assert "datasheet" not in text


async def test_search_solus_says_so_when_the_limit_hid_more(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    for month in ("March", "April", "May"):
        await _seed_entry(maker, project_id, SolusSection.GOALS, f"Ship the arm by {month}")
    registry = _registry_of(maker, project_id)
    cut = _ok_text(await _invoke(registry, "search_solus", q="ship the arm", limit=2)).split("\n")
    assert len(_json_rows("\n".join(cut))) == 2
    assert cut[-1] == MORE
    whole = _ok_text(await _invoke(registry, "search_solus", q="ship the arm", limit=3))
    assert len(_json_rows(whole)) == 3
    assert MORE not in whole


async def test_search_solus_with_no_match_says_so(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    await _seed_entry(maker, project_id, SolusSection.GOALS, "Ship the arm by March")
    registry = _registry_of(maker, project_id)
    assert _ok_text(await _invoke(registry, "search_solus", q="zzqx")) == "no results"


async def test_search_solus_never_leaves_the_project(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    mine, theirs = await _new_project(maker), await _new_project(maker)
    ours = await _seed_entry(maker, mine, SolusSection.GOALS, "Ship the arm by March")
    foreign = await _seed_entry(maker, theirs, SolusSection.GOALS, "Ship the arm by April")
    text = _ok_text(await _invoke(_registry_of(maker, mine), "search_solus", q="ship the arm"))
    assert str(ours.id) in text
    assert str(foreign.id) not in text
    assert "April" not in text


async def test_search_solus_redacts_what_a_person_wrote(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    await _seed_entry(
        maker, project_id, SolusSection.ERRORS, "flash failed: retried with password=hunter2"
    )
    text = _ok_text(await _invoke(_registry_of(maker, project_id), "search_solus", q="flash"))
    assert "password=[REDACTED]" in text
    assert "hunter2" not in text


# ------------------------------------------------------------------ search_corpus


async def test_search_corpus_says_so_when_nothing_is_ingested(engine: AsyncEngine) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4())
    assert _ok_text(await _invoke(registry, "search_corpus", q="decoupling")) == (
        "corpus not ingested"
    )


async def test_search_corpus_serves_active_chunks_with_confidence_and_source(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    maker = _maker(engine)
    async with maker() as db:
        await _ingest_tree(db, write_tree(tmp_path, _corpus_files()))
        await db.execute(
            update(CorpusChunkRow)
            .where(CorpusChunkRow.id == LOOP)
            .values(attribution="Example Press, CC BY 4.0")
        )
        await db.commit()
    registry = _registry_of(maker, uuid.uuid4())
    text = _ok_text(await _invoke(registry, "search_corpus", q="decoupling loop inductance"))
    (row,) = _json_rows(text)
    assert row["id"] == LOOP
    assert row["title"] == "Decoupling is about loop area"
    assert row["domain"] == "electrical"
    assert row["confidence"] == 0.9
    assert row["source"] == "Example Press, CC BY 4.0"
    assert row["excerpt"].startswith("Loop inductance through the capacitor")
    assert "unreviewed" not in text  # a draft chunk never serves
    assert "low_confidence" not in text


async def test_search_corpus_flags_a_low_confidence_chunk_never_drops_it(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    maker = _maker(engine)
    async with maker() as db:
        await _ingest_tree(db, write_tree(tmp_path, _corpus_files()))
    registry = _registry_of(maker, uuid.uuid4())
    text = _ok_text(await _invoke(registry, "search_corpus", q="wire gauge voltage drop"))
    (row,) = _json_rows(text)
    assert row["id"] == LOW
    assert row["confidence"] == 0.5
    assert row["low_confidence"] is True


async def test_search_corpus_says_so_when_the_limit_hid_more(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    maker = _maker(engine)
    async with maker() as db:
        await _ingest_tree(db, write_tree(tmp_path, _corpus_files()))
    registry = _registry_of(maker, uuid.uuid4())
    cut = _ok_text(await _invoke(registry, "search_corpus", q="decoupling gauge", limit=1))
    assert len(_json_rows(cut)) == 1
    assert cut.split("\n")[-1] == MORE
    whole = _ok_text(await _invoke(registry, "search_corpus", q="decoupling gauge", limit=2))
    assert len(_json_rows(whole)) == 2  # both active chunks match; the draft never serves
    assert MORE not in whole


async def test_search_corpus_with_no_match_is_not_the_not_ingested_message(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    maker = _maker(engine)
    async with maker() as db:
        await _ingest_tree(db, write_tree(tmp_path, _corpus_files()))
    registry = _registry_of(maker, uuid.uuid4())
    assert _ok_text(await _invoke(registry, "search_corpus", q="zzqx")) == "no results"


async def test_search_corpus_never_asks_for_an_embedding(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Embedding the query is a metered model call; this read is full text only."""
    seen: dict[str, Any] = {}

    async def spy(_session: AsyncSession, **kwargs: Any) -> list[Any]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(search_tools, "corpus_hits", spy)
    registry = _registry_of(_maker(engine), uuid.uuid4())
    await _invoke(registry, "search_corpus", q="decoupling", limit=3)
    assert seen == {"text": "decoupling", "k": 4}  # no vector, no embed; k is one past the limit


async def test_a_failing_search_still_closes_its_session(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    maker = _maker(engine)
    opened: list[AsyncSession] = []

    def tracked() -> AsyncSession:
        opened.append(maker())
        return opened[-1]

    async def fail_mid_query(session: AsyncSession, *_args: Any, **_kwargs: Any) -> list[Any]:
        await session.execute(select(1))  # begin a transaction, then fail inside it
        raise RuntimeError("the database hiccupped")

    monkeypatch.setattr(search_tools, "search_entities", fail_mid_query)
    registry = ToolRegistry()
    register_search_tools(registry, cast(Any, tracked), uuid.uuid4())
    result = await _invoke(registry, "search_workspace", q="servo")
    assert result.error is not None
    assert result.error.message == "error: search_workspace failed"
    assert len(opened) == 1
    assert not opened[0].in_transaction()


@pytest.mark.parametrize("tool", ["search_workspace", "search_solus", "search_corpus"])
async def test_a_blank_query_is_refused_not_searched(engine: AsyncEngine, tool: str) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4())
    for q in ("", "   "):
        result = await _invoke(registry, tool, q=q)
        assert result.ok is False
        assert result.error is not None
        assert result.error.code is ToolErrorCode.INVALID_ARGS
