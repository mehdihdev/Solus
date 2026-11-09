"""SOLUSDEV-321 P4-T4 (R91, R111, R112) — the backward loop's apply: `apply_sim_change`.

The tool is always gated and never an owned routine, so no Build policy runs it without its card.
Its preview shows the concrete change, admits only a change `simulate` dry-ran in the same turn,
and admits one apply per turn. Its handler runs only after the person approves. The subject's
owning domain picks the ONE writer a change goes through (`OWNER_WRITERS`): a v2 config field
through `put_entity_config` for `runtime` and `electrical`, a `.solus` constraints entry through
`add_text_entry` for `project`. Any other owner, or a change of another kind, is propose-only at
every step: its text comes back, and nothing is parked or written. Then rung 1 re-runs and is
recorded. Another project's subject or config entity is not found at any step.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Final

import pytest
from solus_api.agent.confirmations import ParkedCall, decide_confirmation, request_confirmation
from solus_api.agent.execution_policy import BuildExecutionPolicy, register_owned_routine
from solus_api.agent.modes import ActionMode
from solus_api.agent.runtime import build_dispatch
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools import apply_sim_change as apply_module
from solus_api.agent.tools.shapes import ToolErrorCode, ToolResult
from solus_api.agent.turn_context import bind_turn_id
from solus_api.checkers.matrix_runner import run_matrix
from solus_api.graph import kinds
from solus_api.hardware.config import (
    EntityHardwareConfig,
    FieldProvenance,
    PartConfig,
    PartLimits,
    ProvenanceRecord,
)
from solus_api.hardware.store import put_entity_config, read_entity_config
from solus_api.models import Domain, GraphEntity, SolusEntry, SolusSection, ToolConfirmation
from solus_api.simulation.providers.deterministic_mech import DeterministicMech
from sqlalchemy import func, select
from test_simulate import (
    AT_15,
    PAST_YIELD,
    SECTION,
    _bracket,
    _question,
    _registry_for,
    _seed_part,
    _seed_project,
    _SimProject,
    _simulate_call,
)

type Park = Callable[[ToolCall], Awaitable[ParkedCall | None]]

TORQUE_PATH: Final = "component.limits.values.torque_nm"
RULE_LINE: Final = "keep the bracket load under 900 N"
#: R111's table, row by row: (the subject's owning domain, the change's kind, the writer it goes
#: through, or None: propose only).
OWNER_ROWS: Final = [
    ("runtime", "config", "put_entity_config"),
    ("electrical", "config", "put_entity_config"),
    ("project", "constraint", "add_text_entry"),
    ("code", "config", None),
    ("code", "constraint", None),
    ("mechanical", "config", None),
    ("simulation", "constraint", None),
    ("project", "config", None),
    ("runtime", "constraint", None),
]


def _parking(project: _SimProject, registry: ToolRegistry) -> tuple[Park, list[ParkedCall]]:
    """The turn's park, as `routers/sol.py` builds it: the call parked in its own session."""
    parked: list[ParkedCall] = []

    async def park(call: ToolCall) -> ParkedCall | None:
        async with project.maker() as db:
            found = await request_confirmation(
                db,
                registry,
                call,
                project_id=project.project_id,
                team_id=project.team_id,
                user_id=project.user_id,
            )
            await db.commit()
        if found is not None:
            parked.append(found)
        return found

    return park, parked


async def _approve(
    project: _SimProject, registry: ToolRegistry, confirmation_id: uuid.UUID
) -> ToolResult:
    async with project.maker() as db:
        result = await decide_confirmation(
            db,
            registry,
            confirmation_id,
            approve=True,
            project_id=project.project_id,
            user_id=project.user_id,
        )
        await db.commit()
    return result


async def _confirmations(project: _SimProject) -> int:
    async with project.maker() as db:
        found = select(func.count()).select_from(ToolConfirmation)
        return await db.scalar(found.where(ToolConfirmation.project_id == project.project_id)) or 0


async def _hardware_part(project: _SimProject) -> uuid.UUID:
    """A part with a v2 config whose limits state a torque."""
    async with project.maker() as db:
        part = GraphEntity(
            project_id=project.project_id,
            kind=kinds.PART,
            domain=Domain.ELECTRICAL,
            origin="manual",
            name="shoulder servo",
        )
        db.add(part)
        await db.flush()
        await put_entity_config(
            db,
            project.project_id,
            part,
            EntityHardwareConfig(
                entity_id=part.id,
                component=PartConfig(limits=PartLimits(values={"torque_nm": 1.0})),
                provenance={"component": ProvenanceRecord(by=FieldProvenance.USER)},
            ),
            expected_version=0,
            created_by=None,
        )
        await db.commit()
        return part.id


def _change(kind: str, servo: uuid.UUID) -> dict[str, Any]:
    """The bracket's fix as the servo's torque limit, or as a constraints line."""
    if kind == "config":
        return {"kind": "config", "entity_id": str(servo), "path": TORQUE_PATH, "value": 2.5}
    return {"kind": "constraint", "subsection": "rules", "text": RULE_LINE}


def _args_for(subject: uuid.UUID, change: dict[str, Any]) -> dict[str, Any]:
    return {"subject_id": str(subject), "quantity": "stress_mpa", "change": change}


async def _failing(registry: ToolRegistry, subject: uuid.UUID) -> dict[str, Any]:
    """The subject's failing rung-1 result, in the running turn: the one a change answers."""
    failing = await _simulate_call(registry, question=_question(subject, "stress_mpa"))
    assert failing["verdict"] == "fails"
    return failing


async def _state(project: _SimProject, servo: uuid.UUID) -> tuple[int, int]:
    """What a refused change leaves alone: the servo's config version, and how many constraints
    entries the project's `.solus` holds."""
    async with project.maker() as db:
        entry, _ = await read_entity_config(db, project.project_id, servo)
        lines = await db.scalar(
            select(func.count())
            .select_from(SolusEntry)
            .where(
                SolusEntry.project_id == project.project_id,
                SolusEntry.section == SolusSection.CONSTRAINTS,
            )
        )
    assert entry is not None
    return entry.config_version, lines or 0


async def test_the_tool_is_always_gated_and_never_an_owned_routine(
    engine: Any,
) -> None:
    project = await _seed_project(engine)
    registry = _registry_for(project)
    tool = next(t for t in registry.tools() if t.descriptor.name == "apply_sim_change")
    assert tool.descriptor.requires_confirmation is True
    for family in ("onshape", "isaac", "machine", "command", "bridge"):
        register_owned_routine(tool, family=family)
    assert getattr(tool, "_build_authority", None) is None
    call = ToolCall(tool="apply_sim_change", args={})
    assert await BuildExecutionPolicy(registry, ActionMode.DO).prepare(call) is False


@pytest.mark.parametrize(("owner", "kind", "writer"), OWNER_ROWS)
async def test_the_owning_domain_picks_its_one_writer_or_the_change_is_proposed_only(
    engine: Any, owner: str, kind: str, writer: str | None
) -> None:
    """I1: the dry run, the preview and the handler read ONE owner → writer table. A row with a
    writer is dry-run as appliable, carded, and written by that writer alone once approved; every
    other row is propose-only at all three, and nothing is parked or written."""
    project = await _seed_project(engine)
    subject = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain=owner))
    servo = await _hardware_part(project)
    registry = _registry_for(project)
    args = _args_for(subject, _change(kind, servo))
    park, parked = _parking(project, registry)
    before = await _state(project, servo)
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, subject)
        dry = await _simulate_call(
            registry, question=_question(subject, "stress_mpa"), change=args["change"]
        )
        gated = await build_dispatch(registry, park)(ToolCall(tool="apply_sim_change", args=args))
    assert gated.ok is False and gated.error is not None
    if writer is None:
        # The handler, as an approval runs it: before I1, a code-owned change was written here.
        handled = await registry.invoke(ToolCall(tool="apply_sim_change", args=args))
        assert handled.ok is False and handled.error is not None
        assert "propose only" in handled.error.message.lower()
        assert (dry["writer"], dry["appliable"], dry["apply"]) == (None, False, None)
        assert "propose only" in dry["next"].lower()
        assert "propose only" in gated.error.message.lower()
        assert await _confirmations(project) == 0
        assert await _state(project, servo) == before
        return
    assert (dry["writer"], dry["appliable"]) == (writer, True)
    [card] = parked
    assert card.confirmation_id is not None
    approved = await _approve(project, registry, card.confirmation_id)
    assert approved.ok, approved.error
    assert approved.value is not None and approved.value["rerun"]["decision"] == "ran"
    version, lines = before
    expected = (version + 1, lines) if kind == "config" else (version, lines + 1)
    assert await _state(project, servo) == expected


async def test_another_projects_subject_or_config_is_refused_at_every_step(engine: Any) -> None:
    """I2 (CLAUDE.md §7): another project's subject, and another project's config entity, are not
    found by the dry run, by the preview (nothing is parked) or by the handler an approval runs,
    and neither project is written."""
    project = await _seed_project(engine)
    other = await _seed_project(engine)
    ours = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain="electrical"))
    theirs = await _seed_part(other, **_bracket(PAST_YIELD, owning_domain="electrical"))
    our_servo, their_servo = await _hardware_part(project), await _hardware_part(other)
    registry = _registry_for(project)
    park, parked = _parking(project, registry)
    attempts = [
        _args_for(theirs, _change("config", our_servo)),
        _args_for(ours, _change("config", their_servo)),
    ]
    before = (await _state(project, our_servo), await _state(other, their_servo))
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, ours)
        for args in attempts:
            question = {"subject_id": args["subject_id"], "quantity": "stress_mpa"}
            dry = await registry.invoke(
                ToolCall(tool="simulate", args={"question": question, "change": args["change"]})
            )
            assert dry.ok is False and dry.error is not None
            assert dry.error.code is ToolErrorCode.NOT_FOUND
            gated = await build_dispatch(registry, park)(
                ToolCall(tool="apply_sim_change", args=args)
            )
            assert gated.ok is False and gated.error is not None
            assert "not found" in gated.error.message.lower()
    for args in attempts:  # the handler, as an approval runs it
        handled = await registry.invoke(ToolCall(tool="apply_sim_change", args=args))
        assert handled.ok is False and handled.error is not None
        assert handled.error.code is ToolErrorCode.NOT_FOUND
    assert all(card.confirmation_id is None for card in parked)
    assert await _confirmations(project) == 0
    assert (await _state(project, our_servo), await _state(other, their_servo)) == before


async def test_a_config_change_is_written_through_the_config_writer_and_rung_1_reruns(
    engine: Any,
) -> None:
    project = await _seed_project(engine)
    subject = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain="electrical"))
    servo = await _hardware_part(project)
    registry = _registry_for(project)
    change = _change("config", servo)
    park, parked = _parking(project, registry)
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, subject)
        dry = await _simulate_call(
            registry, question=_question(subject, "stress_mpa"), change=change
        )
        assert (dry["decision"], dry["appliable"]) == ("dry_run", True)
        assert TORQUE_PATH in dry["change_text"]
        waiting = await build_dispatch(registry, park)(
            ToolCall(tool=dry["apply"]["tool"], args=dry["apply"]["args"])
        )
    assert waiting.ok is False
    [card] = parked
    assert card.confirmation_id is not None
    assert {"label": f"shoulder servo: {TORQUE_PATH}", "before": "1.0"}.items() <= (
        next(row for row in card.preview if "torque_nm" in row["label"]).items()
    )

    approved = await _approve(project, registry, card.confirmation_id)

    assert approved.ok, approved.error
    assert approved.value is not None and approved.value["rerun"]["sim_result_id"]
    async with project.maker() as db:
        entry, config = await read_entity_config(db, project.project_id, servo)
    assert entry is not None and config is not None and config.component is not None
    assert config.component.limits is not None
    assert config.component.limits.values["torque_nm"] == 2.5
    assert config.provenance[TORQUE_PATH].by is FieldProvenance.SOL


async def test_a_change_no_writer_makes_is_proposed_and_nothing_is_parked(engine: Any) -> None:
    project = await _seed_project(engine)
    subject = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain="mechanical"))
    registry = _registry_for(project)
    thicker = {**SECTION, "dims_mm": [30.0, 6.0]}
    change = {"kind": "attr", "entity_id": str(subject), "attr": "section", "value": thicker}
    park, parked = _parking(project, registry)
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, subject)
        dry = await _simulate_call(
            registry, question=_question(subject, "stress_mpa"), change=change
        )
        assert (dry["appliable"], dry["apply"]) == (False, None)
        # 6 mm instead of 5: the stress falls from 300 to about 208 MPa, under the 276 MPa yield
        assert dry["predicted"]["yield_fraction"]["value"] == pytest.approx(0.755, abs=0.01)
        args = _args_for(subject, change)
        refused = await build_dispatch(registry, park)(ToolCall(tool="apply_sim_change", args=args))
    assert refused.ok is False and refused.error is not None
    assert "propose only" in refused.error.message.lower()
    assert "section" in refused.error.message
    assert all(card.confirmation_id is None for card in parked)
    assert await _confirmations(project) == 0
    async with project.maker() as db:
        row = await db.get(GraphEntity, subject)
    assert row is not None and row.attrs["section"]["dims_mm"] == [30.0, 5.0]


async def test_a_change_is_dry_run_only_against_a_failing_result_the_turn_holds(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2 (R112): the dry run answers a failing result the same turn holds for that subject and
    quantity. Before one, for a subject whose result passes, or for another quantity, it answers
    `no_failing_result` and judges nothing."""
    project = await _seed_project(engine)
    passing = await _seed_part(project, **_bracket(AT_15, owning_domain="project"))
    failing = await _seed_part(
        project, name="failing", **_bracket(PAST_YIELD, owning_domain="project")
    )
    registry = _registry_for(project)
    judged: list[dict[str, Any]] = []

    async def counted(*args: Any, **kwargs: Any) -> Any:
        judged.append(kwargs)
        return await run_matrix(*args, **kwargs)

    monkeypatch.setattr(apply_module, "run_matrix", counted)
    change = {"kind": "constraint", "subsection": "rules", "text": RULE_LINE}
    with bind_turn_id(uuid.uuid4()):
        refused = [
            await _simulate_call(registry, question=_question(failing, "stress_mpa"), change=change)
        ]
        await _simulate_call(registry, question=_question(passing, "stress_mpa"))  # it stops
        failed = await _failing(registry, failing)
        for subject, quantity in ((passing, "stress_mpa"), (failing, "yield_fraction")):
            refused.append(
                await _simulate_call(registry, question=_question(subject, quantity), change=change)
            )
        held = await _simulate_call(
            registry, question=_question(failing, "stress_mpa"), change=change
        )
    assert [found["decision"] for found in refused] == ["no_failing_result"] * 3
    assert all("no failing result to fix" in found["next"] for found in refused)
    assert (held["decision"], held["failing_result_id"]) == ("dry_run", failed["sim_result_id"])
    assert len(judged) == 2  # the held change's two judgements, and no other


async def test_an_apply_needs_a_failing_result_and_its_dry_run_in_the_same_turn(
    engine: Any,
) -> None:
    """M2 (R112): an apply is refused in a turn that holds no failing result for its subject and
    quantity, and then in one that holds the result but no dry run of its own."""
    project = await _seed_project(engine)
    subject = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain="project"))
    registry = _registry_for(project)
    change = {"kind": "constraint", "subsection": "rules", "text": RULE_LINE}
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, subject)
        dry = await _simulate_call(
            registry, question=_question(subject, "stress_mpa"), change=change
        )
    park, _ = _parking(project, registry)
    dispatch = build_dispatch(registry, park)
    with bind_turn_id(uuid.uuid4()):  # a later turn, holding no failing result yet
        unanchored = await dispatch(ToolCall(tool="apply_sim_change", args=dry["apply"]["args"]))
        await _failing(registry, subject)  # now it holds one, but no dry run of its own
        undried = await dispatch(ToolCall(tool="apply_sim_change", args=dry["apply"]["args"]))
    assert unanchored.error is not None and undried.error is not None
    assert "no failing result to fix" in unanchored.error.message.lower()
    assert "dry-run" in undried.error.message.lower()
    assert await _confirmations(project) == 0


async def test_a_card_that_cannot_be_shown_whole_does_not_spend_the_turns_apply(
    engine: Any,
) -> None:
    """M3: the turn's one apply is claimed only for a card shown whole. A line the card cannot
    show (a control character) is refused and parks nothing; the turn's next change is carded."""
    project = await _seed_project(engine)
    subject = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain="project"))
    registry = _registry_for(project)
    park, parked = _parking(project, registry)
    dispatch = build_dispatch(registry, park)
    lines = ("keep the bracket load\x07 under 900 N", RULE_LINE)
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, subject)
        results = []
        for text in lines:
            change = {"kind": "constraint", "subsection": "rules", "text": text}
            dry = await _simulate_call(
                registry, question=_question(subject, "stress_mpa"), change=change
            )
            call = ToolCall(tool="apply_sim_change", args=dry["apply"]["args"])
            results.append(await dispatch(call))
    assert [card.confirmation_id is not None for card in parked] == [False, True]
    unshown = results[0].error
    assert unshown is not None and "in full" in unshown.message
    assert await _confirmations(project) == 1


async def test_a_rerun_that_fails_after_the_write_is_its_own_line(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4: once the change is written, a re-run that fails is reported beside it, never as the
    call's failure: the person learns that the change landed and that rung 1 did not re-run."""
    project = await _seed_project(engine)
    subject = await _seed_part(project, **_bracket(PAST_YIELD, owning_domain="project"))
    servo = await _hardware_part(project)
    registry = _registry_for(project)
    change = {"kind": "constraint", "subsection": "rules", "text": RULE_LINE}
    park, parked = _parking(project, registry)
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, subject)
        dry = await _simulate_call(
            registry, question=_question(subject, "stress_mpa"), change=change
        )
        await build_dispatch(registry, park)(
            ToolCall(tool="apply_sim_change", args=dry["apply"]["args"])
        )
    [card] = parked
    assert card.confirmation_id is not None
    before = await _state(project, servo)

    def broken(self: Any, inputs: Any) -> Any:
        raise ValueError("nothing to compute")

    monkeypatch.setattr(DeterministicMech, "run", broken)
    approved = await _approve(project, registry, card.confirmation_id)

    assert approved.ok, approved.error
    assert approved.value is not None and approved.value["applied"] == dry["change_text"]
    rerun = approved.value["rerun"]
    assert rerun["decision"] == "failed" and "was applied" in rerun["reason"]
    assert await _state(project, servo) == (before[0], before[1] + 1)  # the line landed


async def test_without_an_owning_domain_the_failing_rules_cell_names_it(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M141: nothing writes `attrs.owning_domain`, so a subject that states none takes the
    destination side of the cell whose rule judges the failing value. The bracket's yield is
    judged mechanical → mechanical, and the mechanical domain has no Solus writer, so the change
    is proposed only and nothing can be parked. With no rule to name a domain either, there is no
    loop, and the matrix never runs."""
    project = await _seed_project(engine)
    subject = await _seed_part(project, **_bracket(PAST_YIELD))
    registry = _registry_for(project)
    change = {"kind": "constraint", "subsection": "rules", "text": RULE_LINE}
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, subject)
        derived = await _simulate_call(
            registry, question=_question(subject, "stress_mpa"), change=change
        )
    assert (derived["decision"], derived["owning_domain"], derived["appliable"]) == (
        "dry_run",
        "mechanical",
        False,
    )
    assert derived["next"].startswith("Propose only:") and derived["apply"] is None

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a dry run ran without an owning domain")

    monkeypatch.setattr(apply_module, "fix_owner", lambda quantity: None)
    monkeypatch.setattr(apply_module, "run_matrix", forbidden)
    with bind_turn_id(uuid.uuid4()):
        await _failing(registry, subject)
        found = await _simulate_call(
            registry, question=_question(subject, "stress_mpa"), change=change
        )
    assert found["decision"] == "no_loop"
    assert "attrs.owning_domain" in found["next"]


@pytest.mark.parametrize(
    ("attrs", "owner", "logged"),
    [
        pytest.param({"owning_domain": "electrical"}, "electrical", False, id="a-stated-domain"),
        pytest.param({}, "mechanical", False, id="absent-the-rules-cell-names-it"),
        pytest.param({"owning_domain": "kitchen"}, "mechanical", True, id="a-word-that-is-none"),
        pytest.param({"owning_domain": 7}, "mechanical", True, id="no-text-at-all"),
    ],
)
def test_an_owning_domain_that_names_none_is_logged_and_read_as_absent(
    attrs: dict[str, Any], owner: str, logged: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Minor 6: the rule's cell names the owner only when the subject states none; a stated
    value that names no owning domain is logged, then read as absent."""
    assert apply_module.owning_domain(attrs) == owner
    assert ("names no owning domain" in caplog.text) is logged
