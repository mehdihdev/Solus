"""SOLUSDEV-321 P0-T3 — anchors reach SOL.

The workspace focus, the chat's pins, the `@` mentions, a finding's subjects and a bench robot
are EQUAL anchors: each pulls its neighbourhood into the turn, and they differ only in the reason
they carry (`focused`, `mentioned`, `pinned`, `finding_subject`, `bench_robot`, `ref_match`). The
reason is what lets the context manifest say why SOL looked where it looked.

A stale id is not one policy. A selection the person made — `pins` (like `mentions`), a
`finding_id`, a `robot_id` — is refused at admission when the project cannot see it, because they
can fix it: 409 `stale_mentions` / 404 `not_found`, before any spend. The focus is sent
automatically with every page send, so a focus id that went stale (another project's, or since
deleted) is DROPPED, with its reason, and the turn runs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from fixtures.fake_systems import FakeSolSystems
from fixtures.scope_doubles import no_hits
from httpx import AsyncClient
from solus_api.agent import turn_scope
from solus_api.agent.conversation import ConversationService
from solus_api.agent.reason import MAX_ANCHORS, Anchor, DroppedAnchor, FocusIn
from solus_api.agent.runtime import LlmRunner
from solus_api.agent.sol_anchors import ResolvedAnchors, resolve_anchor_inputs
from solus_api.agent.turn_scope import ScopeInputs, TurnScope, plan_scope
from solus_api.checkers.interface import Severity
from solus_api.graph import kinds
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.models import Domain, GraphEntity, TurnRole, utcnow
from solus_api.orchestration.config import load_orchestration_config
from solus_api.orchestration.enums import Complexity
from solus_api.orchestration.providers import Usage
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_CONFIG = load_orchestration_config()


async def _anchor_plan(query: str = "why is it hot?", **kw: Any) -> TurnScope:
    """`plan_scope` at the standard tier over the canned graph: these tests are about anchors,
    not names or budgets."""
    return await plan_scope(
        ScopeInputs(message=query, tier=Complexity.STANDARD, **kw),
        search=no_hits,
        load=lambda scope, budget: FakeSolSystems().get_graph_context(uuid.uuid4(), scope, budget),
        disambiguate=None,
        config=_CONFIG,
    )


def _ids(count: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(count)]


# ---------------------------------------------------------------- plan_scope (pure)


async def test_focus_pins_mentions_are_equal_anchors_with_reasons() -> None:
    focus, hop, mentioned, pinned, subject, robot, quoted = _ids(7)

    plan = await _anchor_plan(
        f"why does {quoted} stall?",
        mentions=[mentioned],
        pins=[pinned],
        focus=FocusIn(entity_id=focus, path=[hop]),
        finding_subjects=[subject],
        robot_id=robot,
    )

    # Blame order: what the person is looking at, then what they pointed at, then what the
    # system points at; an id lifted out of the prose comes after them — it may be quoted log
    # output — and the focus trail last: the page sends it on its own (P1-T1).
    assert plan.anchors == (
        Anchor(id=focus, reason="focused"),
        Anchor(id=mentioned, reason="mentioned"),
        Anchor(id=pinned, reason="pinned"),
        Anchor(id=subject, reason="finding_subject"),
        Anchor(id=robot, reason="bench_robot"),
        Anchor(id=quoted, reason="ref_match"),
        Anchor(id=hop, reason="focused"),
    )
    # Equal anchors: every one of them seeds the neighbourhood the same way.
    assert plan.scope.anchor_entity_ids == [a.id for a in plan.anchors]
    assert plan.dropped == ()


async def test_an_entity_named_twice_is_one_anchor_under_its_first_reason() -> None:
    both, pinned_too, only_pinned = _ids(3)

    plan = await _anchor_plan(
        f"look at {both}",
        focus=FocusIn(entity_id=both),
        mentions=[both, pinned_too],
        pins=[pinned_too, only_pinned],
    )

    assert plan.anchors == (
        Anchor(id=both, reason="focused"),
        Anchor(id=pinned_too, reason="mentioned"),
        Anchor(id=only_pinned, reason="pinned"),
    )
    assert plan.dropped == ()  # a repeat is not a casualty of the cap


async def test_the_cap_moves_the_lowest_ranked_anchors_to_dropped() -> None:
    focus, *path = _ids(3)
    pins = _ids(4)

    plan = await _anchor_plan(
        focus=FocusIn(entity_id=focus, path=path), mentions=_ids(3), pins=pins
    )

    assert MAX_ANCHORS == 8
    assert [a.reason for a in plan.anchors] == ["focused"] + ["mentioned"] * 3 + ["pinned"] * 4
    # The trail ranks last, nearest the focused entity first (P1-T1): the cap takes it before
    # anything the person pointed at.
    assert plan.dropped == tuple(
        DroppedAnchor(id=hop, reason="focused", cause="over_cap") for hop in reversed(path)
    )
    assert plan.scope.anchor_entity_ids == [a.id for a in plan.anchors]


async def test_ids_the_caller_could_not_see_are_dropped_before_the_cap_with_reason_and_cause() -> (
    None
):
    stale = uuid.uuid4()
    mentions = _ids(MAX_ANCHORS)

    plan = await _anchor_plan(
        focus=FocusIn(entity_id=stale), mentions=mentions, not_visible={stale}
    )

    # The stale focus took no slot: all eight mentions still fit.
    assert plan.anchors == tuple(Anchor(id=m, reason="mentioned") for m in mentions)
    assert plan.dropped == (DroppedAnchor(id=stale, reason="focused", cause="not_visible"),)


async def test_dropped_anchors_stay_in_blame_order_and_each_says_why() -> None:
    stale = uuid.uuid4()
    mentions = _ids(MAX_ANCHORS + 1)

    plan = await _anchor_plan(
        focus=FocusIn(entity_id=stale), mentions=mentions, not_visible={stale}
    )

    # One lost to visibility, one to the cap; the list reads in the order the planner ranked them.
    assert plan.dropped == (
        DroppedAnchor(id=stale, reason="focused", cause="not_visible"),
        DroppedAnchor(id=mentions[-1], reason="mentioned", cause="over_cap"),
    )


async def test_history_ids_ride_the_plan_but_are_not_anchors() -> None:
    plan = await _anchor_plan(history_entity_ids=tuple(_ids(2)))

    # They ride the planner's inputs as hints (docs/api/API.md §2.9, P1-T1): never an anchor,
    # never a root of the graph pull.
    assert plan.anchors == () and plan.scope.anchor_entity_ids == []


# ---------------------------------------------------------------- the turn route


@dataclass(frozen=True)
class _AnchorRoute:
    project_id: uuid.UUID
    conversation_id: uuid.UUID
    url: str


async def _anchor_route(client: AsyncClient, headers: dict[str, str]) -> _AnchorRoute:
    """A project the caller owns, with one conversation in it."""
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    base = f"/api/v1/projects/{project['id']}/sol/conversations"
    convo = await client.post(base, json={}, headers=headers)
    assert convo.status_code == 201, convo.text
    conversation_id = convo.json()["data"]["id"]
    return _AnchorRoute(
        project_id=uuid.UUID(project["id"]),
        conversation_id=uuid.UUID(conversation_id),
        url=f"{base}/{conversation_id}/messages",
    )


async def _anchor_entity(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    name: str = "LM358",
    kind: str = kinds.COMPONENT,
    deleted: bool = False,
) -> uuid.UUID:
    row = GraphEntity(
        project_id=project_id,
        kind=kind,
        domain=Domain.ELECTRICAL,
        name=name,
        deleted_at=utcnow() if deleted else None,
    )
    db.add(row)
    await db.flush()
    entity_id = row.id
    await db.commit()
    return entity_id


async def _anchor_finding(
    db: AsyncSession, project_id: uuid.UUID, subjects: Sequence[uuid.UUID]
) -> uuid.UUID:
    spec = FindingSpec(
        rule_id="i2c_address_conflict",
        severity=Severity.WARNING,
        source="checker",
        headline="0x68 used twice",
        subjects=list(subjects),
        domain=Domain.ELECTRICAL,
    )
    finding_id = (await raise_finding(db, project_id, spec)).id
    await db.commit()
    return finding_id


async def _soft_delete(db: AsyncSession, *entity_ids: uuid.UUID) -> None:
    await db.execute(
        update(GraphEntity).where(GraphEntity.id.in_(entity_ids)).values(deleted_at=utcnow())
    )
    await db.commit()


class _CtxRecorder:
    """Captures the run context Solus code handed the runner — no model involved."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []

    @property
    def ctx(self) -> Any:
        return self.contexts[-1]

    async def run(self, ctx: Any) -> Any:
        self.contexts.append(ctx)
        for _ in ():  # an async generator that yields nothing
            yield


class _ProseModel:
    """Plays every provider: one prose answer, no tool call."""

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Any = None,
        conversation: Any = None,
        **_: Any,
    ) -> AsyncIterator[str | Usage]:
        yield "ok"
        yield Usage(tokens_in=5, tokens_out=2)


def _use_the_real_runner(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[ScopeInputs, TurnScope]]:
    """Run the REAL `LlmRunner` against a scripted model, and return every scope it plans with
    the inputs it planned from — `plan_scope` is the seam where the anchors and their reasons
    become observable."""
    model = _ProseModel()
    app.state.agent_runner = LlmRunner(
        adapters={"anthropic": model, "openai": model, "google": model}
    )
    app.state.sol_systems = FakeSolSystems()
    plans: list[tuple[ScopeInputs, TurnScope]] = []
    real = turn_scope.plan_scope

    async def spy(inputs: ScopeInputs, **kwargs: Any) -> TurnScope:
        plan = await real(inputs, **kwargs)
        plans.append((inputs, plan))
        return plan

    monkeypatch.setattr(turn_scope, "plan_scope", spy)
    return plans


def _spy_on_spend(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, AsyncMock]:
    admission, credits = AsyncMock(), AsyncMock()
    monkeypatch.setattr("solus_api.routers.sol.check_frequency_cap", admission)
    monkeypatch.setattr("solus_api.routers.sol.has_sufficient_credits", credits)
    return admission, credits


async def test_foreign_or_deleted_focus_is_dropped_not_404(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The focus rides along with every page send, so a stale one must not cost the person
    their question: it is dropped WITH its reason, never a 404 (and never named in a reply)."""
    plans = _use_the_real_runner(app, monkeypatch)
    mine = await _anchor_route(client, alice_headers)
    bobs = await _anchor_route(client, bob_headers)
    live = await _anchor_entity(db, mine.project_id)
    foreign = await _anchor_entity(db, bobs.project_id, name="Bob Secret Part")
    deleted = await _anchor_entity(db, mine.project_id, name="Removed Part", deleted=True)

    resp = await client.post(
        mine.url,
        json={
            "content": "what is this?",
            "focus": {"entity_id": str(foreign), "path": [str(live), str(deleted)]},
        },
        headers=alice_headers,
    )

    assert resp.status_code == 200, resp.text
    assert "event: done" in resp.text and "event: error" not in resp.text
    assert "Bob Secret Part" not in resp.text
    ((_, plan),) = plans
    assert plan.anchors == (Anchor(id=live, reason="focused"),)
    assert plan.dropped == (
        DroppedAnchor(id=foreign, reason="focused", cause="not_visible"),
        DroppedAnchor(id=deleted, reason="focused", cause="not_visible"),
    )
    assert plan.scope.anchor_entity_ids == [live]


async def test_foreign_finding_and_robot_id_404(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mine = await _anchor_route(client, alice_headers)
    bobs = await _anchor_route(client, bob_headers)
    part = await _anchor_entity(db, mine.project_id)
    other_part = await _anchor_entity(db, mine.project_id, name="U2")
    my_finding = await _anchor_finding(db, mine.project_id, [part])
    gone_finding = await _anchor_finding(db, mine.project_id, [other_part])
    my_robot = await _anchor_entity(db, mine.project_id, name="Rover", kind=kinds.PHYSICAL_ROBOT)
    gone_robot = await _anchor_entity(
        db, mine.project_id, name="Old Rover", kind=kinds.PHYSICAL_ROBOT, deleted=True
    )
    bobs_part = await _anchor_entity(db, bobs.project_id, name="Bob Secret Part")
    bobs_finding = await _anchor_finding(db, bobs.project_id, [bobs_part])
    bobs_robot = await _anchor_entity(
        db, bobs.project_id, name="Bob Secret Rover", kind=kinds.PHYSICAL_ROBOT
    )
    await _soft_delete(db, gone_finding)
    recorder = _CtxRecorder()
    app.state.agent_runner = recorder
    admission, credits = _spy_on_spend(monkeypatch)

    refused = {
        "foreign finding": ("finding_id", bobs_finding),
        "absent finding": ("finding_id", uuid.uuid4()),
        "a part, not a finding": ("finding_id", part),
        "deleted finding": ("finding_id", gone_finding),
        "foreign robot": ("robot_id", bobs_robot),
        "absent robot": ("robot_id", uuid.uuid4()),
        "a finding, not a robot": ("robot_id", my_finding),
        "deleted robot": ("robot_id", gone_robot),
    }
    answers: dict[str, set[tuple[str, str]]] = {"finding_id": set(), "robot_id": set()}
    for label, (field, value) in refused.items():
        resp = await client.post(
            mine.url,
            json={"content": "what is this?", field: str(value)},
            headers=alice_headers,
        )
        assert resp.status_code == 404, f"{label}: {resp.text}"
        assert "Bob Secret" not in resp.text, label
        error = resp.json()["error"]
        assert error["code"] == "not_found", label
        answers[field].add((error["code"], error["message"]))

    # No existence oracle: foreign, absent, deleted and wrong-kind read the same.
    assert all(len(seen) == 1 for seen in answers.values()), answers
    assert recorder.contexts == []
    admission.assert_not_called()
    credits.assert_not_called()

    # Control: the project's own finding and robot pass, and reach the runner as ids.
    ok = await client.post(
        mine.url,
        json={
            "content": "what is this?",
            "finding_id": str(my_finding),
            "robot_id": str(my_robot),
        },
        headers=alice_headers,
    )
    assert ok.status_code == 200, ok.text
    assert recorder.ctx.finding_id == my_finding and recorder.ctx.robot_id == my_robot


async def test_pins_reuse_stale_mentions_409(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mine = await _anchor_route(client, alice_headers)
    bobs = await _anchor_route(client, bob_headers)
    part = await _anchor_entity(db, mine.project_id)
    foreign = await _anchor_entity(db, bobs.project_id, name="Bob Secret Part")
    deleted = await _anchor_entity(db, mine.project_id, name="Removed Part", deleted=True)
    recorder = _CtxRecorder()
    app.state.agent_runner = recorder
    admission, credits = _spy_on_spend(monkeypatch)

    for stale in (foreign, deleted, uuid.uuid4()):
        resp = await client.post(
            mine.url,
            json={"content": "what is this?", "pins": [str(part), str(stale)]},
            headers=alice_headers,
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "stale_mentions"
        assert "Bob Secret Part" not in resp.text
    # Mentions and pins are one set of selections: either field catches the stale id.
    mixed = await client.post(
        mine.url,
        json={"content": "what is this?", "mentions": [str(part)], "pins": [str(foreign)]},
        headers=alice_headers,
    )
    assert mixed.status_code == 409
    assert recorder.contexts == []
    admission.assert_not_called()
    credits.assert_not_called()

    ok = await client.post(
        mine.url, json={"content": "what is this?", "pins": [str(part)]}, headers=alice_headers
    )
    assert ok.status_code == 200, ok.text
    assert recorder.ctx.pins == (part,)
    assert recorder.ctx.mentions == ()  # a pin is not smuggled in as a mention


async def test_focus_pins_mentions_finding_and_robot_reach_the_runner_apart(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    mine = await _anchor_route(client, alice_headers)
    focus, hop, mentioned, pinned = [await _anchor_entity(db, mine.project_id) for _ in range(4)]
    finding = await _anchor_finding(db, mine.project_id, [focus])
    robot = await _anchor_entity(db, mine.project_id, name="Rover", kind=kinds.PHYSICAL_ROBOT)
    recorder = _CtxRecorder()
    app.state.agent_runner = recorder

    resp = await client.post(
        mine.url,
        json={
            "content": "why is it hot?",
            "focus": {"entity_id": str(focus), "path": [str(hop)]},
            "mentions": [str(mentioned)],
            "pins": [str(pinned)],
            "finding_id": str(finding),
            "robot_id": str(robot),
        },
        headers=alice_headers,
    )

    assert resp.status_code == 200, resp.text
    ctx = recorder.ctx
    assert ctx.focus == FocusIn(entity_id=focus, path=[hop])
    assert ctx.mentions == (mentioned,) and ctx.pins == (pinned,)
    assert ctx.finding_id == finding and ctx.robot_id == robot


async def test_the_default_body_carries_no_anchors(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    mine = await _anchor_route(client, alice_headers)
    recorder = _CtxRecorder()
    app.state.agent_runner = recorder

    resp = await client.post(mine.url, json={"content": "hello"}, headers=alice_headers)

    assert resp.status_code == 200, resp.text
    ctx = recorder.ctx
    assert ctx.focus is None and ctx.pins == () and ctx.finding_id is None
    assert ctx.robot_id is None and ctx.history_entity_ids == ()


async def test_a_findings_subjects_and_the_bench_robot_become_anchors(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = _use_the_real_runner(app, monkeypatch)
    mine = await _anchor_route(client, alice_headers)
    first, second, removed = [
        await _anchor_entity(db, mine.project_id, name=f"U{i}") for i in range(3)
    ]
    finding = await _anchor_finding(db, mine.project_id, [first, second, removed])
    await _soft_delete(db, removed)  # a subject that went away after the finding was raised
    robot = await _anchor_entity(db, mine.project_id, name="Rover", kind=kinds.PHYSICAL_ROBOT)

    resp = await client.post(
        mine.url,
        json={"content": "why?", "finding_id": str(finding), "robot_id": str(robot)},
        headers=alice_headers,
    )

    assert resp.status_code == 200, resp.text
    ((_, plan),) = plans
    assert plan.anchors == (
        Anchor(id=first, reason="finding_subject"),
        Anchor(id=second, reason="finding_subject"),
        Anchor(id=robot, reason="bench_robot"),
    )
    assert plan.dropped == ()


async def test_a_vanished_finding_resolves_to_no_subjects(engine: AsyncEngine) -> None:
    """The route 404s a missing finding at admission; if one disappears between admission and
    the run, the run goes on without its subjects — empty beats a failed turn."""
    maker = async_sessionmaker(engine, expire_on_commit=False)

    resolved = await resolve_anchor_inputs(maker, uuid.uuid4(), focus=None, finding_id=uuid.uuid4())

    assert resolved == ResolvedAnchors()


async def test_history_entity_ids_come_from_prior_tool_args(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mine = await _anchor_route(client, alice_headers)
    a, b, c, d, hidden, e, f, g, h, i, j = _ids(11)
    service = ConversationService()

    async def prior(role: TurnRole, content: str, attrs: Any = None) -> None:
        await service.append_turn(
            db,
            conversation_id=mine.conversation_id,
            project_id=mine.project_id,
            role=role,
            content=content,
            attrs=attrs,
        )

    def tool_turn(args: dict[str, Any]) -> dict[str, Any]:
        return {"call": {"call_id": "c", "tool": "get_entity", "args": args}, "result": {"ok": 1}}

    await prior(TurnRole.USER, f"what about {uuid.uuid4()}?")  # prose is not tool args
    await prior(TurnRole.TOOL, "read", tool_turn({"entity_id": str(a)}))
    await prior(TurnRole.TOOL, "read", tool_turn({"entity_ids": [str(b), str(c)]}))
    await prior(TurnRole.TOOL, "read", tool_turn({"target": {"entity_id": str(d)}}))
    # Two levels down is out of reach, and a non-UUID string is no id.
    await prior(TurnRole.TOOL, "read", tool_turn({"deep": {"nested": {"entity_id": str(hidden)}}}))
    await prior(TurnRole.TOOL, "read", tool_turn({"note": "see U1", "entity_id": str(e)}))
    await prior(TurnRole.TOOL, "read", tool_turn({"entity_ids": [str(f), str(g), str(h)]}))
    await prior(TurnRole.TOOL, "read", tool_turn({"entity_id": str(i), "again": str(i)}))
    await prior(TurnRole.ASSISTANT, "done")
    # Malformed rows are skipped, never fatal: no args, args that are not an object, no call —
    # and attrs that are not even an object (old or hand-edited data must not 500 the turn).
    await prior(TurnRole.TOOL, "read", {"call": {"call_id": "c", "tool": "get_entity"}})
    await prior(TurnRole.TOOL, "read", {"call": {"tool": "x", "args": [str(hidden)]}})
    await prior(TurnRole.TOOL, "read", {})
    await prior(TurnRole.TOOL, "read", [str(hidden)])
    await prior(TurnRole.TOOL, "read", "oops")
    await prior(TurnRole.TOOL, "read", tool_turn({"entity_id": str(j)}))
    await db.commit()
    recorder = _CtxRecorder()
    app.state.agent_runner = recorder

    resp = await client.post(mine.url, json={"content": "and now?"}, headers=alice_headers)

    assert resp.status_code == 200, resp.text
    # Newest call first, at most eight, each id once. `c` and `a` fall off the end (eight is the
    # cap), and `hidden` was never collected: it sits two levels down, or in a malformed row.
    assert recorder.ctx.history_entity_ids == (j, i, f, g, h, e, d, b)

    plans = _use_the_real_runner(app, monkeypatch)
    again = await client.post(mine.url, json={"content": "once more"}, headers=alice_headers)
    assert again.status_code == 200, again.text
    # The planner is handed them as hints; they anchor nothing (docs/api/API.md §2.9).
    ((inputs, plan),) = plans
    assert inputs.history_entity_ids[:2] == (j, i)
    assert plan.anchors == () and plan.scope.anchor_entity_ids == []


@pytest.mark.parametrize(
    "body",
    [
        {"pins": [str(uuid.uuid4()) for _ in range(MAX_ANCHORS + 1)]},
        {"focus": {"entity_id": str(uuid.uuid4()), "path": [str(uuid.uuid4())] * 17}},
        {"focus": {"entity_id": str(uuid.uuid4()), "depth": 3}},
        {"focus": {"path": []}},
        {"focus": "the-bracket"},
        {"finding_id": "not-a-uuid"},
        {"robot_id": 7},
    ],
    ids=[
        "pins-over-cap",
        "path-over-cap",
        "focus-unknown-key",
        "focus-no-entity",
        "focus-not-an-object",
        "finding-malformed",
        "robot-malformed",
    ],
)
async def test_anchor_fields_are_bounded_and_strict(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    body: dict[str, Any],
) -> None:
    mine = await _anchor_route(client, alice_headers)
    recorder = _CtxRecorder()
    app.state.agent_runner = recorder

    resp = await client.post(mine.url, json={"content": "hi", **body}, headers=alice_headers)

    assert resp.status_code == 422, resp.text
    assert recorder.contexts == []


async def test_the_focus_path_may_be_exactly_sixteen_deep(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    mine = await _anchor_route(client, alice_headers)
    recorder = _CtxRecorder()
    app.state.agent_runner = recorder
    focus = {"entity_id": str(uuid.uuid4()), "path": [str(uuid.uuid4()) for _ in range(16)]}

    resp = await client.post(
        mine.url, json={"content": "hi", "focus": focus}, headers=alice_headers
    )

    assert resp.status_code == 200, resp.text
    assert len(recorder.ctx.focus.path) == 16
