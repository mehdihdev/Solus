"""SOLUSDEV-321 P7 — tool knowledge for the release on the person's own machine.

The route reads each mapped KiCad tool's vendor note without a version (`agent/tools/knowledge.py`).
`agent/guide_toolkb_version.py` reads it again for the release the asker's OWN machine reports —
the project card's machine block, which only the machine's owner gets (`project_card.tool_versions`
behind `owns_machine`) — so SOL never points at a control from another release: a note covering
that release stands, and none gives the Solus sentence "not sure where that is in KiCad <release>".
With no release reported, a tool the knowledge base has nothing for gives the sentence without one.
No model call is made for any of it.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, cast

import pytest
from solus_api.agent.guide_toolkb_version import machine_release, placed_tools
from solus_api.agent.project_card import CardInputs, MachineBlock, ProjectCardCache, machine_block
from solus_api.agent.prompt import tool_specs
from solus_api.agent.tools import knowledge
from solus_api.agent.tools.knowledge import load_knowledge_notes, with_knowledge_notes
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.contracts.tool_knowledge import ToolFamily
from solus_api.services.machines import MachineIn, upsert_machine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_knowledge import _publish
from test_project_card import COMPANION, _companion_session, _project, _user

_SYMBOL_PROPERTIES = "kicad.eeschema.edit_symbol_properties"
_DRAW_WIRES = "kicad.eeschema.interactive_drawing_line_wire_bus.draw_wires"
_DOCS = "https://docs.kicad.org/9.0/en/eeschema/eeschema.html"
_UNPLACED_10 = (
    f"[{_SYMBOL_PROPERTIES}] No vendor documentation covers KiCad 10.0.2: "
    "not sure where that is in KiCad 10.0.2."
)


def _machine_with(*versions: tuple[str, str]) -> MachineBlock:
    return MachineBlock(
        hostname="bench-01", os="linux", arch="arm64", tool_versions=versions, recent_commands=()
    )


def _card_around(machine: MachineBlock | None) -> CardInputs:
    """The route's layer-2 hand-off around a machine block; the rest is what a card needs."""
    return CardInputs(
        cache=ProjectCardCache(InMemoryCacheStore()),
        connectors=ConnectorRegistry(),
        findings={},
        machine=machine,
        active_device_ids=frozenset(),
        budgets="no budgets",
    )


def _kicad_tool(name: str) -> ToolDescriptor:
    return ToolDescriptor(
        name=name, description="d", params={"type": "object"}, returns={"type": "object"}
    )


def test_the_release_is_the_digits_of_the_line_the_machine_reports() -> None:
    assert machine_release(_machine_with(("kicad-cli", "9.0.1")), "kicad-cli") == "9.0.1"
    assert machine_release(_machine_with(("kicad-cli", "kicad-cli 8.0.6-1")), "kicad-cli") == (
        "8.0.6"
    )
    assert machine_release(_machine_with(("kicad-cli", "unknown")), "kicad-cli") is None
    assert machine_release(_machine_with(("git", "git version 2.43.0")), "kicad-cli") is None
    assert machine_release(None, "kicad-cli") is None


async def test_a_note_for_another_release_gives_way_to_not_sure_where_that_is(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    await _publish(db, _SYMBOL_PROPERTIES, ToolFamily.KICAD, _DOCS)  # covers >=8.0 <10.0
    # The note the route hangs on the tool, read without a version (routers/sol.py).
    notes = await load_knowledge_notes(db)
    (routed,) = with_knowledge_notes((_kicad_tool("kicad.set_symbol_property"),), notes)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    nine, ten = (_card_around(_machine_with(("kicad-cli", v))) for v in ("9.0.1", "10.0.2"))

    (covered,) = await placed_tools((routed,), nine, maker)
    assert covered.knowledge_note == routed.knowledge_note
    (uncovered,) = await placed_tools((routed,), ten, maker)
    assert uncovered.knowledge_note == _UNPLACED_10
    # It reaches the model as the tool's fenced knowledge — data, never an instruction.
    (spec,) = tool_specs((uncovered,), nonce="n")
    fenced = spec.description.split("<<<SOLUS-DATA n kind=tool_knowledge>>>", 1)[1]
    assert "not sure where that is in KiCad 10.0.2" in fenced

    # No release reported (no card, or a card with no machine): a note stands, and a tool with
    # none gets the sentence naming the tool alone.
    for card in (None, _card_around(None)):
        kept, bare = await placed_tools((routed, _kicad_tool("kicad.add_wire")), card, maker)
        assert kept.knowledge_note == routed.knowledge_note
        assert bare.knowledge_note == (
            f"[{_DRAW_WIRES}] No vendor documentation covers KiCad: "
            "not sure where that is in KiCad."
        )
    # A tool whose tool no machine reports a release for is never touched.
    onshape = _kicad_tool("onshape.set_variable")
    assert await placed_tools((onshape,), ten, maker) == (onshape,)


async def test_the_release_is_read_from_the_owners_machine_block_alone(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """The release comes through the card's owner-gated machine block: a teammate whose session
    claims the same machine gets no block, so no release reaches the note."""
    project_id, team_id = await _project(db)
    owner, teammate = await _user(db), await _user(db)
    await upsert_machine(
        db,
        project_id,
        owner,
        COMPANION,
        MachineIn(hostname="bench-01", os="linux", arch="arm64"),
        tool_versions={"kicad-cli": "10.0.2"},
    )
    await db.commit()
    mine = await machine_block(
        db,
        project_id=project_id,
        user_id=owner,
        live=_companion_session(owner, team_id, project_id),
    )
    theirs = await machine_block(
        db,
        project_id=project_id,
        user_id=teammate,
        live=_companion_session(teammate, team_id, project_id),
    )
    assert mine is not None and theirs is None
    maker = async_sessionmaker(engine, expire_on_commit=False)
    tool = _kicad_tool("kicad.set_symbol_property")

    (asked,) = await placed_tools((tool,), _card_around(mine), maker)
    assert asked.knowledge_note == _UNPLACED_10
    (other,) = await placed_tools((tool,), _card_around(theirs), maker)
    assert other.knowledge_note == (
        f"[{_SYMBOL_PROPERTIES}] No vendor documentation covers KiCad: "
        "not sure where that is in KiCad."
    )


async def test_a_release_read_asks_its_own_family_and_says_so_when_it_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P7 fix 1 (M5): the release read asks for the offered family's mapped controls alone — one
    query each, never every mapped tool's — and a read that failed says the vendor notes were
    unavailable, never that no vendor documentation covers the release."""
    asked: list[ToolFamily] = []

    async def failing(session: Any, *, tool: ToolFamily, **_: Any) -> Any:
        asked.append(tool)
        raise ConnectionError("tool knowledge store unreachable")

    monkeypatch.setattr(knowledge, "query_entries", failing)
    card = _card_around(_machine_with(("kicad-cli", "10.0.2")))
    tool = _kicad_tool("kicad.set_symbol_property")
    (placed,) = await placed_tools((tool,), card, cast(Any, nullcontext))
    kicad = [f for f, _ in knowledge.TOOL_CONTROLS.values() if f is ToolFamily.KICAD]
    assert asked == kicad and len(asked) < len(knowledge.TOOL_CONTROLS)
    assert placed.knowledge_note == (
        f"[{_SYMBOL_PROPERTIES}] Vendor notes unavailable for KiCad 10.0.2: "
        "not sure where that is in KiCad 10.0.2."
    )
