"""SOLUSDEV-321 P5 (R103, R104, R127, D6, D10) — `render_view`: one labelled, cached view.

A face question on the fake arm's scene draws ONE labelled render (the offscreen renderer, stubbed
here; `livebench/tests/lb_offscreen_test.py` proves the engine) and reads it with ONE vision call,
counted against the turn. Asking again costs nothing: no render, no call, no finding. A read that
names a length the graph states differently shows the graph's value and files ONE info finding.
The picture reaches the chat only when asked, as a fresh artifact reference each time. The cache is
reached only after the asker's own read of the subject (R127): another project never gets a hit.
Outside a turn the tool is unavailable; with renders off the turn, or nothing to draw the entity,
nothing is drawn and nothing is read.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image
from solus_api.agent.modes import ActionMode
from solus_api.agent.prompt import tool_specs
from solus_api.agent.tools import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode, ToolResult
from solus_api.agent.turn_budget import TurnBudget
from solus_api.agent.turn_context import CONNECTIVITY_REFUSAL, with_perception, with_turn
from solus_api.agent.turn_limits import turn_limits
from solus_api.agent.vision import renderers
from solus_api.agent.vision.render_annotate import LABEL_INK
from solus_api.agent.vision.render_view import (
    RENDER_VIEW_DESCRIPTOR,
    choose_view,
    register_render_view_tool,
)
from solus_api.agent.vision.renderers import ViewSpec
from solus_api.agent.vision.vision_postcheck import RULE_ID
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.models import Artifact, Domain, GraphEntity, SourceType
from solus_api.orchestration import gateway
from solus_api.services.artifacts import fetch_artifact_bytes
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from test_renderers import (
    _bridge_with,
    _hidden_base_for,
    _member,
    _render_scope,
    _RenderScope,
    _scene_for_arm,
    _source,
    _sourced,
    _StubOffscreen,
)

TURN = uuid.uuid4()
#: The turn's project as the runner binds it beside the turn (R148); no test here reads a ledger.
TURN_PROJECT = uuid.uuid4()
TTL = 3600
FRONT = "What is on the front face of servo 2?"
READ = "A front view of the fake arm: servo 2 (joint 2) stands on servo 1 (joint 1), labelled."
LONG_READ = "Servo 2 (joint 2) is about 350 mm long."


def _looking(
    scope: _RenderScope,
    monkeypatch: pytest.MonkeyPatch,
    read: str = READ,
    *,
    asker: uuid.UUID | None = None,
    bridge: Any = None,
) -> tuple[ToolRegistry, _StubOffscreen, list[dict[str, Any]]]:
    """`render_view` bound to `scope`'s project and to `asker` (the scope's person by default),
    its scene renderer stubbed and every vision call recorded and answered with `read`."""
    offscreen = _StubOffscreen()
    monkeypatch.setattr(renderers, "_offscreen", lambda: offscreen)
    calls: list[dict[str, Any]] = []

    async def complete(query: str, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(text=read)

    monkeypatch.setattr(gateway, "complete", complete)
    registry = ToolRegistry()
    register_render_view_tool(
        registry,
        scope.maker,
        scope.project_id,
        user_id=asker or scope.user_id,
        team_id=scope.team_id,
        secret_store=InMemorySecretStore(),
        artifact_store=scope.store,
        artifact_ttl_seconds=TTL,
        connectors=scope.connectors,
        bridge=bridge,
    )
    return registry, offscreen, calls


def _turn_budget(max_model_calls: int = 6) -> TurnBudget:
    budget = TurnBudget(replace(turn_limits(ActionMode.GUIDE), max_model_calls=max_model_calls))
    budget.note_model_call()  # the round that proposed the call
    return budget


async def _ask_in_turn(
    registry: ToolRegistry, budget: TurnBudget, *, refused: bool = False, **args: Any
) -> ToolResult:
    """The tool as the runner reaches it: inside the turn, with its perception bound (R125)."""
    dispatch = with_perception(
        with_turn(registry.invoke, TURN, TURN_PROJECT), budget, connectivity=refused, counting=False
    )
    return await dispatch(ToolCall(tool="render_view", args=args))


async def _findings(scope: _RenderScope) -> list[GraphEntity]:
    async with scope.maker() as db:
        return list(
            await db.scalars(
                select(GraphEntity).where(
                    GraphEntity.project_id == scope.project_id, GraphEntity.kind == kinds.FINDING
                )
            )
        )


async def _with_length(scope: _RenderScope, part_id: uuid.UUID) -> None:
    """The graph states the part's extents (a CAD import's bounding box): 40 x 40 x 300 mm."""
    async with scope.maker() as db:
        part = await db.get(GraphEntity, part_id)
        assert part is not None
        geometry = {"length_unit": "mm", "dimensions": [40.0, 40.0, 300.0]}
        part.attrs = {**part.attrs, "geometry": geometry}
        await db.commit()


async def _fetched(scope: _RenderScope, artifact_id: uuid.UUID) -> bytes | None:
    """The artifact's bytes as its creator reads them through the artifacts route's rules, or None
    when it is gone (expired, consumed or never this project's)."""
    async with scope.maker() as db:
        try:
            _, data = await fetch_artifact_bytes(
                db,
                scope.store,
                project_id=scope.project_id,
                artifact_id=artifact_id,
                requester_id=scope.user_id,
                ttl_seconds=TTL,
                max_bytes=8 * 1024 * 1024,
            )
        except APIError:
            return None
    return data


async def test_face_question_one_cached_labelled_render(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    registry, offscreen, calls = _looking(scope, monkeypatch)
    budget = _turn_budget()

    result = await _ask_in_turn(registry, budget, entity_id=str(arm.parts[1]), question=FRONT)

    assert result.ok, result.error
    value = result.value or {}
    assert (value["rendered"], value["view"], value["renderer"]) == (True, "face:front", "scene")
    assert value["cached"] is False and value["read"] == READ and value["findings"] == []
    assert "artifact_id" not in value  # shown only when asked
    (shot,) = offscreen.calls
    assert (shot["view"], shot["side"], shot["target_joint"]) == ("face", "front", "joint_2")
    (call,) = calls
    assert (call["purpose"], call["turn_id"]) == ("vision", TURN)
    (image,) = call["images"]
    picture = Image.open(io.BytesIO(image.data)).convert("RGB")
    assert picture.width == 320 and picture.height > 240  # the caption band under the render
    assert picture.getpixel((150, 100)) == LABEL_INK  # servo 2's box, at its projected bounds
    assert budget.model_calls == 2  # the round, and the one read


async def test_second_ask_zero_calls(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same view of an unchanged graph is the cache's: no render, no model call, no finding.
    A changed graph is a new picture."""
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    await _with_length(scope, arm.parts[1])
    registry, offscreen, calls = _looking(scope, monkeypatch, read=LONG_READ)
    budget = _turn_budget()
    servo = str(arm.parts[1])

    first = await _ask_in_turn(registry, budget, entity_id=servo, question=FRONT)
    again = await _ask_in_turn(
        registry, budget, entity_id=servo, question="Show servo 2 from the front."
    )

    assert first.ok and again.ok, (first.error, again.error)
    one, two = first.value or {}, again.value or {}
    assert (one["cached"], two["cached"]) == (False, True)
    assert len(one["findings"]) == 1 and two["findings"] == []  # the hit filed nothing
    assert {**two, "cached": False, "findings": one["findings"]} == one
    assert len(offscreen.calls) == len(calls) == 1 and budget.model_calls == 2
    (finding,) = await _findings(scope)
    assert finding.attrs["count"] == 1

    await _with_length(scope, arm.parts[0])  # servo 1 now states extents: a new picture
    changed = await _ask_in_turn(registry, budget, entity_id=servo, question=FRONT)
    assert (changed.value or {})["cached"] is False and len(offscreen.calls) == 2


async def test_disagreeing_dimension_shows_the_graph_value_and_files_one_info(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    await _with_length(scope, arm.parts[1])
    registry, _, _ = _looking(scope, monkeypatch, read=LONG_READ)

    result = await _ask_in_turn(
        registry, _turn_budget(), entity_id=str(arm.parts[1]), question=FRONT
    )

    value = result.value or {}
    assert value["read"] == (
        "Servo 2 (joint 2) is about 300 mm (the graph's value; the render read 350 mm) long."
    )
    assert value["graph_wins"] == [
        {
            "entity_id": str(arm.parts[1]),
            "label": "servo 2 (joint 2)",
            "graph": {"value": 300.0, "unit": "mm"},
            "render": {"value": 350.0, "unit": "mm"},
        }
    ]
    (finding,) = await _findings(scope)
    assert value["findings"] == [str(finding.id)]
    attrs = finding.attrs
    assert (attrs["rule_id"], attrs["severity"], attrs["source"]) == (RULE_ID, "info", "sol")
    assert attrs["subjects"] == [str(arm.parts[1])]


async def test_show_puts_the_picture_in_the_chat_as_an_artifact_reference(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    registry, _, calls = _looking(scope, monkeypatch)

    result = await _ask_in_turn(
        registry, _turn_budget(), entity_id=str(arm.parts[1]), question=FRONT, show=True
    )

    value = result.value or {}
    assert value["media_type"] == "image/png" and value["uri"].endswith("/content")
    assert value["title"] and value["summary"]
    assert not any(isinstance(item, bytes) for item in value.values())  # a reference, no pixels
    async with scope.maker() as db:
        artifact = await db.get(Artifact, uuid.UUID(value["artifact_id"]))
    assert artifact is not None and artifact.project_id == scope.project_id
    assert artifact.source_tool == "render_view" and artifact.created_by == scope.user_id
    assert await scope.store.get(str(artifact.id)) == calls[0]["images"][0].data  # what was read


async def test_every_show_stores_a_fresh_artifact_even_for_a_cached_look(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R127: the cache keeps the picture, never an artifact. Each `show` stores a fresh TTL
    artifact for the asker, so an expired one is never handed out again."""
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    registry, offscreen, _ = _looking(scope, monkeypatch)
    args: dict[str, Any] = {"entity_id": str(arm.parts[1]), "question": FRONT, "show": True}
    first = await _ask_in_turn(registry, _turn_budget(), **args)
    first_id = uuid.UUID((first.value or {})["artifact_id"])
    async with scope.maker() as db:
        shown = await db.get(Artifact, first_id)
        assert shown is not None
        shown.created_at = shown.created_at - timedelta(seconds=2 * TTL)  # past its TTL
        await db.commit()

    again = await _ask_in_turn(registry, _turn_budget(), **args)

    value = again.value or {}
    assert value["cached"] is True and len(offscreen.calls) == 1
    fresh_id = uuid.UUID(value["artifact_id"])
    assert fresh_id != first_id
    assert await _fetched(scope, first_id) is None  # the expired one stays gone
    fresh = await _fetched(scope, fresh_id)
    assert fresh is not None and fresh.startswith(b"\x89PNG")


async def test_another_project_never_gets_a_hit_on_a_warm_look(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R127: the subject is read in the asker's own scope before the cache is consulted, so a look
    another project warmed is never served, drawn, read or shown to them, and files nothing."""
    ours = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(ours)
    await _with_length(ours, arm.parts[1])
    warm, _, _ = _looking(ours, monkeypatch, read=LONG_READ)
    servo = str(arm.parts[1])
    first = await _ask_in_turn(warm, _turn_budget(), entity_id=servo, question=FRONT)
    assert first.ok and len((first.value or {})["findings"]) == 1
    theirs = await _render_scope(engine, tmp_path / "theirs")
    registry, offscreen, calls = _looking(theirs, monkeypatch, read=LONG_READ)

    asked = [
        await _ask_in_turn(registry, _turn_budget(), entity_id=servo, question=FRONT, show=show)
        for show in (False, True)
    ]

    for foreign in asked:
        assert not foreign.ok and foreign.error is not None
        assert foreign.error.code is ToolErrorCode.NOT_FOUND
    assert offscreen.calls == [] and calls == []
    assert await _findings(theirs) == []
    (finding,) = await _findings(ours)
    assert finding.attrs["count"] == 1
    async with theirs.maker() as db:
        made = await db.scalars(select(Artifact).where(Artifact.project_id == theirs.project_id))
        assert list(made) == []


async def test_a_teammate_whose_view_hides_the_part_never_gets_the_warm_look(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R127 (P5 fix 1, M2): the subject is read in the asker's own graph scope before the cache is
    consulted. Servo 2 comes from a base source that a teammate's active revision snapshot
    replaces in their view, so the look warmed on servo 2 is never served, drawn, read or shown to
    them."""
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    member = await _member(scope)
    base = await _hidden_base_for(scope, member)
    async with scope.maker() as db:
        servo = await db.get(GraphEntity, arm.parts[1])
        assert servo is not None
        servo.source_id = base
        await db.commit()
    warm, _, _ = _looking(scope, monkeypatch)
    servo_id = str(arm.parts[1])
    first = await _ask_in_turn(warm, _turn_budget(), entity_id=servo_id, question=FRONT)
    assert first.ok and (first.value or {})["rendered"] is True
    registry, offscreen, calls = _looking(scope, monkeypatch, asker=member)

    asked = await _ask_in_turn(
        registry, _turn_budget(), entity_id=servo_id, question=FRONT, show=True
    )

    assert not asked.ok and asked.error is not None
    assert asked.error.code is ToolErrorCode.NOT_FOUND
    assert offscreen.calls == [] and calls == []
    async with scope.maker() as db:
        made = await db.scalars(select(Artifact).where(Artifact.created_by == member))
        assert list(made) == []


async def test_a_companion_drawn_view_is_each_askers_own(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P5 fix 1 (M5): a companion exports its person's own working copy, which can hold edits not
    yet synced. So each member asking for the same companion-drawn view gets their own render and
    read, never a teammate's look; the same member asking again is still the cache's."""
    scope = await _render_scope(engine, tmp_path)
    member = await _member(scope)
    kicad = await _source(
        scope, SourceType.KICAD, config={"project_path": "/home/fake/proj/a.kicad_pro"}
    )
    net = str(await _sourced(scope, kicad, kinds.NET, "SDA"))
    sent: list[str] = []
    bridge = _bridge_with(scope, flagged=True, sent=sent)
    _bridge_with(scope, flagged=True, sent=sent, user_id=member, registry=bridge)

    cached = []
    for asker in (scope.user_id, member, scope.user_id):
        registry, _, _ = _looking(scope, monkeypatch, asker=asker, bridge=bridge)
        result = await _ask_in_turn(
            registry, _turn_budget(), entity_id=net, question="Which sheet carries SDA?"
        )
        assert result.ok, result.error
        cached.append((result.value or {})["cached"])

    assert cached == [False, False, True]
    assert len(sent) == 2  # one export per member, none for the repeat


async def test_nothing_is_drawn_outside_a_turn_with_renders_off_or_when_refused(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    registry, offscreen, calls = _looking(scope, monkeypatch)
    args: dict[str, Any] = {"entity_id": str(arm.parts[1]), "question": FRONT}

    outside = await registry.invoke(ToolCall(tool="render_view", args=args))
    off = await _ask_in_turn(registry, _turn_budget(), refused=True, **args)
    monkeypatch.setattr(renderers, "_offscreen", lambda: None)
    refused = await _ask_in_turn(registry, _turn_budget(), **args)

    assert not outside.ok and outside.error is not None
    assert outside.error.code is ToolErrorCode.UNAVAILABLE
    assert off.value == {"rendered": False, "reason": CONNECTIVITY_REFUSAL}
    value = refused.value or {}
    assert value["rendered"] is False and "not installed" in value["reason"]
    assert offscreen.calls == [] and calls == []


async def test_an_unread_render_is_honest_and_not_cached(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With only the closing round's call left, the picture is drawn but not read, and a later
    ask draws it again: only a look a model read is cached."""
    scope = await _render_scope(engine, tmp_path)
    arm, _ = await _scene_for_arm(scope)
    registry, offscreen, calls = _looking(scope, monkeypatch)
    spent = _turn_budget(max_model_calls=3)
    spent.note_model_call()

    unread = await _ask_in_turn(registry, spent, entity_id=str(arm.parts[1]), question=FRONT)
    read = await _ask_in_turn(registry, _turn_budget(), entity_id=str(arm.parts[1]), question=FRONT)

    assert "budget is spent" in (unread.value or {})["read"]
    assert (read.value or {})["read"] == READ and (read.value or {})["cached"] is False
    assert len(offscreen.calls) == 2 and len(calls) == 1


async def test_an_entity_nothing_draws_says_so(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = await _render_scope(engine, tmp_path)
    async with scope.maker() as db:
        loose = GraphEntity(
            project_id=scope.project_id,
            kind=kinds.PART,
            domain=Domain.MECHANICAL,
            origin="manual",
            name="loose bracket",
            attrs={},
        )
        db.add(loose)
        await db.commit()
    registry, offscreen, calls = _looking(scope, monkeypatch)

    result = await _ask_in_turn(registry, _turn_budget(), entity_id=str(loose.id), question=FRONT)

    value = result.value or {}
    assert value["rendered"] is False and "nothing draws" in value["reason"]
    assert offscreen.calls == [] and calls == []


def test_the_model_is_told_to_show_the_picture_only_when_asked() -> None:
    """P5 fix 1 (M4, R103): a render reaches the person only when they asked to see it, so the
    model reads that rule where it chooses: the tool's description and `show`'s own."""
    (spec,) = tool_specs([RENDER_VIEW_DESCRIPTOR])
    show = spec.input_schema["properties"]["show"]
    for text in (spec.description, show["description"]):
        assert "only when the person asked to see the picture" in text


@pytest.mark.parametrize(
    ("question", "sheets", "view"),
    [
        ("What is on the front face?", False, ViewSpec("face", "front")),
        ("How does it look from the rear?", False, ViewSpec("face", "back")),
        ("Show the underside of the base", False, ViewSpec("face", "bottom")),
        ("How big is servo 2?", False, ViewSpec("bounds")),
        ("What does the arm look like?", False, ViewSpec("iso")),
        ("Which sheet carries SDA?", True, ViewSpec("sheet")),
        ("Show the board layout near U1", True, ViewSpec("board")),
        ("What is on the front of the PCB?", True, ViewSpec("board")),
    ],
)
def test_choose_view_reads_the_view_from_the_question(
    question: str, sheets: bool, view: ViewSpec
) -> None:
    assert choose_view(question, sheets=sheets) == view
