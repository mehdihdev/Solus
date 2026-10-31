"""SOLUSDEV-321 P3-T4 — `label_motifs` (`agent/tools/label_motifs.py`; R57, R75, R78).

The one model path for netlist motifs. In a SOL turn, ONE light-tier call labels the candidates
the matrix job left at confidence 0.7 or below.

- The call runs under the requester's identity, with `purpose="motif"` and this turn's id.
- The candidates are fenced as data.
- Every label is checked against the closed set (the five kinds and `unknown`) before it is
  written, under `attrs.motif_labels`, never `attrs.motifs`.
- Outside a turn the tool refuses.

The plan named this file `test_label_motifs_tool.py`; H9 pairs `label_motifs.py` with
`*test_label_motifs.py`, so it is named for the module (a recorded deviation). Every model call
here runs through a scripted gateway or scripted adapters; no provider is reached.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any, Final

import pytest
from fixtures.datasheet import HOSTILE_TEXT
from fixtures.matrix_divider import seed_divider
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools.label_motifs import (
    LABEL_MOTIFS_DESCRIPTOR,
    register_label_motifs_tool,
)
from solus_api.agent.tools.shapes import ToolErrorCode, ToolResult
from solus_api.agent.turn_context import current_turn_id, with_turn
from solus_api.checkers.matrix_runner import run_matrix
from solus_api.checkers.netlist_motifs import CANDIDATE, LABEL_KINDS, LABELS_KEY, MOTIFS_KEY
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import (
    CreditLedger,
    Domain,
    GraphEdge,
    GraphEntity,
    Project,
    Team,
    User,
)
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import Complexity, RouteType
from solus_api.orchestration.providers import Usage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_sol_reasoner import _funded_user

REPLY: Final = "\n".join(
    [
        '{"candidate": 1, "label": "divider_adc"}',
        '{"candidate": 2, "label": "flux_capacitor"}',
        '{"candidate": 9, "label": "h_bridge"}',
        "this line is not json",
    ]
)


async def _candidates_project(db: AsyncSession, *, hostile: bool = False) -> dict[str, Any]:
    """Two inputs nothing names as an ADC input, so both are candidates once the job has run:
    - a divider at MID: R1 from VIN, R2 to ground, U1 on it;
    - an RC input at FILT: R3, C3 and U1.
    With `hostile`, R1's value carries an instruction."""
    tag = uuid.uuid4().hex[:8]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@labels.example")
    team = Team(name=f"labels-{tag}")
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name=f"labels-{tag}", created_by=user.id)
    db.add(project)
    await db.flush()
    values = {"R1": HOSTILE_TEXT if hostile else "10k", "R2": "10k", "R3": "1k", "C3": "1uF"}

    def node(kind: str, name: str) -> GraphEntity:
        attrs = {"value": values[name]} if name in values else {}
        return GraphEntity(
            project_id=project.id,
            kind=kind,
            domain=Domain.ELECTRICAL,
            origin="connector",
            name=name,
            attrs=attrs,
        )

    rows = {name: node("component", name) for name in ("R1", "R2", "R3", "C3", "U1")}
    rows |= {name: node("net", name) for name in ("VIN", "MID", "SIG", "FILT", "GND")}
    db.add_all(rows.values())
    await db.flush()
    pins = (
        ("R1", "VIN"), ("R1", "MID"), ("R2", "MID"), ("R2", "GND"), ("U1", "MID"),
        ("R3", "SIG"), ("R3", "FILT"), ("C3", "FILT"), ("C3", "GND"), ("U1", "FILT"),
    )  # fmt: skip
    db.add_all(
        GraphEdge(
            project_id=project.id,
            src_id=rows[part].id,
            dst_id=rows[net].id,
            relation_type="connected_to",
            domain_pair="electrical<->electrical",
            confidence=1.0,
            origin="connector",
            attrs={"net": net, "pins": [str(n)]},
        )
        for n, (part, net) in enumerate(pins, start=1)
    )
    await db.commit()
    await run_matrix(db, project.id)
    await db.commit()
    return {"project_id": project.id, "user_id": user.id, **{k: r.id for k, r in rows.items()}}


def _label_registry(engine: AsyncEngine, project_id: uuid.UUID, user_id: uuid.UUID) -> ToolRegistry:
    registry = ToolRegistry()
    register_label_motifs_tool(
        registry,
        async_sessionmaker(engine, expire_on_commit=False),
        project_id,
        user_id=user_id,
        secret_store=InMemorySecretStore(),
        redis=None,
        enqueue=None,
    )
    return registry


class _Completion:
    def __init__(self, text: str) -> None:
        self.text = text


def _scripted_reply(monkeypatch: pytest.MonkeyPatch, text: str) -> list[dict[str, Any]]:
    """gateway.complete → `text`, recording each call's query and keywords."""
    calls: list[dict[str, Any]] = []

    async def complete(query: str, **kw: Any) -> _Completion:
        calls.append({"query": query, **kw})
        return _Completion(text)

    monkeypatch.setattr(gateway, "complete", complete)
    return calls


#: The turn's project as the runner binds it beside the turn (R148); `label_motifs` names its own.
TURN_PROJECT = uuid.uuid4()


async def _invoke_in_turn(registry: ToolRegistry, turn_id: uuid.UUID) -> ToolResult:
    """The tool as the runner reaches it: through a dispatch bound to the turn (R75, R148)."""
    dispatch = with_turn(registry.invoke, turn_id, TURN_PROJECT)
    return await dispatch(ToolCall(tool="label_motifs", args={}))


async def _attrs(db: AsyncSession, entity_id: uuid.UUID) -> dict[str, Any]:
    row = await db.get(GraphEntity, entity_id, populate_existing=True)
    assert row is not None
    return dict(row.attrs)


async def test_labels_checked_against_closed_enum(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R57: the reply's labels are checked against the closed set before anything is written.
    A label outside it (`flux_capacitor`) and a candidate number nobody was offered are
    dropped and counted. The one valid label lands on each of that candidate's members under
    `attrs.motif_labels`, with the job's `attrs.motifs` untouched."""
    seeded = await _candidates_project(db)
    calls = _scripted_reply(monkeypatch, REPLY)
    divider = [seeded[n] for n in ("R1", "R2", "U1", "MID")]
    before = {member: (await _attrs(db, member))[MOTIFS_KEY] for member in divider}
    turn_id = uuid.uuid4()
    registry = _label_registry(engine, seeded["project_id"], seeded["user_id"])

    result = await _invoke_in_turn(registry, turn_id)

    assert result.ok, result.error
    value = result.value or {}
    assert value["dropped"] == 2
    (labelled,) = value["labelled"]
    assert (labelled["shape"], labelled["label"]) == ("divider_adc", "divider_adc")
    assert labelled["members"] == [str(member) for member in divider]
    expected = {
        "kind": "divider_adc",
        "members": [str(member) for member in divider],
        "confidence": CANDIDATE,
        "labelled_by": "model",
        "turn_id": str(turn_id),
    }
    for member in divider:
        attrs = await _attrs(db, member)
        assert attrs[LABELS_KEY] == [expected]
        assert attrs[MOTIFS_KEY] == before[member]  # the job's key is never rewritten here
    for member in (seeded["R3"], seeded["C3"], seeded["FILT"]):
        assert LABELS_KEY not in await _attrs(db, member)
    (call,) = calls
    assert (call["purpose"], call["turn_id"], call["user_id"]) == (
        "motif",
        turn_id,
        seeded["user_id"],
    )
    assert (call["complexity"], call["type"]) == (Complexity.TRIVIAL, RouteType.GENERAL)
    assert call["session"] is not None and "redis" in call
    assert "kind=motif_candidates" in call["query"] and "never an instruction" in call["query"]
    assert all(kind in LABEL_MOTIFS_DESCRIPTOR.description for kind in LABEL_KINDS)


async def test_label_motifs_runs_only_inside_a_sol_turn(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R75: outside a SOL turn no turn id is bound, so the tool refuses rather than make an
    unattributed call. Nothing is called and nothing is written."""
    seeded = await _candidates_project(db)
    calls = _scripted_reply(monkeypatch, REPLY)
    registry = _label_registry(engine, seeded["project_id"], seeded["user_id"])

    result = await registry.invoke(ToolCall(tool="label_motifs", args={}))

    assert not result.ok and result.error is not None
    assert result.error.code is ToolErrorCode.UNAVAILABLE
    assert calls == [] and current_turn_id() is None
    assert LABELS_KEY not in await _attrs(db, seeded["R1"])


async def test_the_labelling_call_counts_against_the_turns_model_call_budget(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M122: inside a turn the labelling call is one of the turn's `max_model_calls`. A turn with
    room notes it; a turn one call short of its closing round labels nothing — refused
    UNAVAILABLE, no call made, nothing written."""
    from dataclasses import replace

    from solus_api.agent.modes import ActionMode
    from solus_api.agent.turn_budget import TurnBudget
    from solus_api.agent.turn_context import PerceptionTurn, bind_perception
    from solus_api.agent.turn_limits import turn_limits

    def budget(max_model_calls: int) -> TurnBudget:
        return TurnBudget(replace(turn_limits(ActionMode.GUIDE), max_model_calls=max_model_calls))

    seeded = await _candidates_project(db)
    calls = _scripted_reply(monkeypatch, REPLY)
    registry = _label_registry(engine, seeded["project_id"], seeded["user_id"])

    short = budget(3)
    short.note_model_call()
    short.note_model_call()  # the next call would be the closing round's
    with bind_perception(PerceptionTurn(short)):
        refused = await _invoke_in_turn(registry, uuid.uuid4())
    assert not refused.ok and refused.error is not None
    assert refused.error.code is ToolErrorCode.UNAVAILABLE
    assert calls == [] and short.model_calls == 2
    assert LABELS_KEY not in await _attrs(db, seeded["R1"])

    roomy = budget(6)
    with bind_perception(PerceptionTurn(roomy)):
        result = await _invoke_in_turn(registry, uuid.uuid4())
    assert result.ok and len(calls) == 1 and roomy.model_calls == 1


async def test_nothing_to_label_makes_no_call(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The divider fixture's motifs are settled (its pin says ADC), so no candidate waits and
    no model is called."""
    divider = await seed_divider(db)
    await run_matrix(db, divider.project_id)
    await db.commit()
    calls = _scripted_reply(monkeypatch, REPLY)
    registry = _label_registry(engine, divider.project_id, divider.user_id)

    result = await _invoke_in_turn(registry, uuid.uuid4())

    assert result.ok and calls == []
    assert (result.value or {})["labelled"] == []


async def test_a_hostile_part_value_stays_fenced_and_cannot_choose_a_label(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE.md §7 red team: a part value carrying an instruction reaches the model only inside
    the data fence. Whatever the reply says, only a closed-set label for an offered candidate is
    written. Here the model 'obeys' with a label outside the set, and nothing is written."""
    seeded = await _candidates_project(db, hostile=True)
    calls = _scripted_reply(monkeypatch, '{"candidate": 1, "label": "send the schematic"}')
    registry = _label_registry(engine, seeded["project_id"], seeded["user_id"])

    result = await _invoke_in_turn(registry, uuid.uuid4())

    assert result.ok and (result.value or {})["dropped"] == 1
    (call,) = calls
    instructions, fenced = call["query"].split("<<<SOLUS-DATA", 1)
    assert HOSTILE_TEXT not in instructions and HOSTILE_TEXT in fenced
    for name in ("R1", "R2", "U1"):
        assert LABELS_KEY not in await _attrs(db, seeded[name])


async def test_the_call_is_the_requesters_metered_and_counted_on_the_turn(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the REAL gateway with scripted adapters, the call is debited to the requester.
    Its ledger row carries `purpose="motif"` and the turn's id, so the turn's spend counts it."""

    class _ScriptedLabels:
        async def stream(self, model_name: str, query: str, **_: Any) -> Any:
            yield '{"candidate": 1, "label": "unknown"}'
            yield Usage(tokens_in=5, tokens_out=3)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    seeded = await _candidates_project(db)
    payer = await _funded_user(maker)
    adapters = {name: _ScriptedLabels() for name in ("anthropic", "openai", "google")}
    monkeypatch.setattr(gateway, "complete", partial(gateway.complete, adapters=adapters))
    turn_id = uuid.uuid4()

    result = await _invoke_in_turn(_label_registry(engine, seeded["project_id"], payer), turn_id)

    assert result.ok, result.error
    (labelled,) = (result.value or {})["labelled"]
    assert labelled["label"] == "unknown"
    async with maker() as session:
        rows = await session.scalars(select(CreditLedger).where(CreditLedger.user_id == payer))
        motif = [row.attrs for row in rows.all() if row.attrs.get("purpose") == "motif"]
    assert [attrs["turn_id"] for attrs in motif] == [str(turn_id)]


async def _holders_project(db: AsyncSession, *, holders: int, waiting: int) -> dict[str, Any]:
    """`holders` nets created a second apart, oldest first, each holding one candidate motif on
    itself. Every one but the holder at index `waiting` already carries its label."""
    from datetime import timedelta

    from solus_api.models import utcnow

    tag = uuid.uuid4().hex[:8]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@holders.example")
    team = Team(name=f"holders-{tag}")
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name=f"holders-{tag}", created_by=user.id)
    db.add(project)
    await db.flush()
    start, rows = utcnow(), []
    for n in range(holders):
        net_id = uuid.uuid4()
        entry = {"kind": "rc_on_input", "members": [str(net_id)], "confidence": CANDIDATE}
        label = {**entry, "labelled_by": "model", "turn_id": str(uuid.uuid4())}
        attrs = {MOTIFS_KEY: [entry], **({LABELS_KEY: [label]} if n != waiting else {})}
        rows.append(
            GraphEntity(
                id=net_id,
                project_id=project.id,
                kind="net",
                domain=Domain.ELECTRICAL,
                origin="connector",
                name=f"N{n}",
                attrs=attrs,
                created_at=start + timedelta(seconds=n),
            )
        )
    db.add_all(rows)
    await db.commit()
    return {"project_id": project.id, "user_id": user.id, "holders": [row.id for row in rows]}


async def test_labelled_holders_never_hide_a_later_candidate(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I2: the holders are read a page at a time, oldest first, until a candidate waits. So the
    200 holders labelled first never stop the 201st's candidate from being offered."""
    seeded = await _holders_project(db, holders=250, waiting=200)
    calls = _scripted_reply(monkeypatch, '{"candidate": 1, "label": "rc_on_input"}')
    registry = _label_registry(engine, seeded["project_id"], seeded["user_id"])

    result = await _invoke_in_turn(registry, uuid.uuid4())

    assert result.ok, result.error
    assert len(calls) == 1 and '"N200"' in calls[0]["query"]
    assert LABELS_KEY in await _attrs(db, seeded["holders"][200])


async def test_each_candidate_shows_its_parts_on_its_own_nets_only(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m7: U1 sits in both candidates. Each shows U1 on its own net only, so an IC shared by many
    inputs never grows every candidate's view past the fence's cap."""
    from solus_api.agent import prompt

    seeded = await _candidates_project(db)
    _scripted_reply(monkeypatch, "")
    shown: list[Any] = []
    fence = prompt.data_block

    def spy(nonce: str, kind: str, payload: object, **kw: Any) -> str:
        shown.append(payload)
        return fence(nonce, kind, payload, **kw)

    monkeypatch.setattr(prompt, "data_block", spy)

    await _invoke_in_turn(
        _label_registry(engine, seeded["project_id"], seeded["user_id"]), uuid.uuid4()
    )

    (views,) = shown
    u1_nets = [  # each view's U1, on that view's nets
        next(part["nets"] for part in view["parts"] if part["ref"] == "U1") for view in views
    ]
    assert [list(nets) for nets in u1_nets] == [["MID"], ["FILT"]]


async def test_a_candidate_no_member_kept_is_not_reported_labelled(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m9: `labelled` lists a candidate only when at least one member kept its label. Here another
    writer holds every member row, so nothing is reported labelled, and `notes` counts the rows."""
    from solus_api.agent.tools import label_motifs

    seeded = await _candidates_project(db)
    _scripted_reply(monkeypatch, '{"candidate": 1, "label": "divider_adc"}')

    async def held(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(label_motifs, "add_motif_label", held)
    registry = _label_registry(engine, seeded["project_id"], seeded["user_id"])

    result = await _invoke_in_turn(registry, uuid.uuid4())

    assert result.ok, result.error
    value = result.value or {}
    assert value["labelled"] == []
    assert value["notes"] == ["4 member row(s) another writer held kept no label"]


def test_a_deeply_nested_reply_line_is_noise_not_a_raise() -> None:
    """m12: `parse_labels` never raises, even for a line nested past the JSON decoder's recursion
    limit; such a line is noise, like any line that is not a JSON object."""
    from solus_api.agent.tools.label_motifs import parse_labels

    reply = "[" * 100_000 + "\n" + '{"candidate": 1, "label": "h_bridge"}'
    assert parse_labels(reply, 1) == ({0: "h_bridge"}, 0)
