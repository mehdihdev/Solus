"""SOLUSDEV-321 P1-T4 — `get_finding` and `get_run`: one finding, one recorded run, by id. P2-T1
adds `get_envelope`: one quantity of one part, the bounds and where each came from.

Driven through `register_finding_tools` on a real `ToolRegistry` against the real database. An id
the project does not hold — absent, deleted, another kind, or another project's — answers the
same `not_found` with the same words, so the tools are no existence oracle across tenants.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fixtures.fake_arm import seed_fake_arm
from solus_api.agent.tools import ToolCall, ToolErrorCode, ToolRegistry, ToolResult
from solus_api.agent.tools.finding_tools import register_finding_tools
from solus_api.agent.tools.read_tool import TRUNCATED
from solus_api.checkers.interface import Severity
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.livebench.findings.envelopes import QUANTITIES
from solus_api.livebench.runs import store as run_store
from solus_api.livebench.runs.models import RunSummary
from solus_api.models import Domain, GraphEntity, Project, Team
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]


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


async def _seed_part(maker: Maker, project_id: uuid.UUID, name: str) -> GraphEntity:
    async with maker() as db:
        part = GraphEntity(
            project_id=project_id,
            kind="component",
            domain=Domain.ELECTRICAL,
            origin="manual",
            name=name,
        )
        db.add(part)
        await db.commit()
        return part


async def _seed_finding(
    maker: Maker, project_id: uuid.UUID, subjects: list[uuid.UUID], **over: Any
) -> GraphEntity:
    fields: dict[str, Any] = {
        "rule_id": "i2c_address_conflict",
        "severity": Severity.WARNING,
        "source": "checker",
        "headline": "0x68 used twice",
        "subjects": subjects,
        "evidence": {"address": "0x68"},
        "domain": Domain.ELECTRICAL,
    }
    async with maker() as db:
        row = await raise_finding(db, project_id, FindingSpec(**{**fields, **over}))
        await db.commit()
        return row


async def _seed_run(maker: Maker, project_id: uuid.UUID, **over: Any) -> RunSummary:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "robot_id": uuid.uuid4(),
        "name": "Baseline sweep",
        "origin": "live",
        "status": "completed",
        "started_at": datetime(2026, 10, 1, tzinfo=UTC),
        "ended_at": datetime(2026, 10, 1, 0, 5, tzinfo=UTC),
        "packet_count": 1200,
        "drop_count": 3,
    }
    info = RunSummary(**{**fields, **over})
    async with maker() as db:
        db.add(run_store.new_record(project_id, info, uuid.uuid4()))
        await db.commit()
    return info


def _registry_of(maker: Maker, project_id: uuid.UUID) -> ToolRegistry:
    registry = ToolRegistry()
    register_finding_tools(registry, maker, project_id)
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


def _evidence(text: str) -> dict[str, Any]:
    """The evidence rows of a `get_finding` result merged into one dict. Each row carries exactly
    one key under "evidence", so the key-name rule sees it beside its value."""
    pairs = [row["evidence"] for row in _json_rows(text) if "evidence" in row]
    assert all(len(pair) == 1 for pair in pairs)
    return {key: value for pair in pairs for key, value in pair.items()}


def _missing_message(result: ToolResult) -> str:
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND
    return result.error.message


# --------------------------------------------------------------------- the registry


async def test_the_tools_register_read_only_and_ungated(engine: AsyncEngine) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4())
    descriptors = {d.name: d for d in registry.list()}
    assert set(descriptors) == {"get_envelope", "get_finding", "get_run"}
    for descriptor in descriptors.values():
        assert descriptor.requires_confirmation is False
        assert descriptor.files_errors is False
        assert descriptor.result_cap == 8_000
        assert "Read-only" in descriptor.description
    assert descriptors["get_finding"].params["required"] == ["finding_id"]
    assert descriptors["get_run"].params["required"] == ["run_id"]
    assert descriptors["get_envelope"].params["required"] == ["part_id", "quantity"]
    assert descriptors["get_envelope"].params["properties"]["quantity"]["enum"] == list(QUANTITIES)


# ----------------------------------------------------------------------- get_finding


async def test_get_finding_reads_the_headline_subjects_and_evidence(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    imu = await _seed_part(maker, project_id, "U1 IMU")
    adc = await _seed_part(maker, project_id, "U2 ADC")
    finding = await _seed_finding(
        maker, project_id, [imu.id, adc.id], evidence={"address": "0x68", "bus": "i2c1"}
    )
    registry = _registry_of(maker, project_id)
    text = _ok_text(await _invoke(registry, "get_finding", finding_id=str(finding.id)))
    head, *rest = _json_rows(text)
    assert head["id"] == str(finding.id)
    assert head["headline"] == "0x68 used twice"
    assert (head["severity"], head["status"]) == ("warning", "open")
    assert (head["rule"], head["source"]) == ("i2c_address_conflict", "checker")
    subjects = {row["subject"]: (row["kind"], row["id"]) for row in rest if "subject" in row}
    assert subjects == {
        "U1 IMU": ("component", str(imu.id)),
        "U2 ADC": ("component", str(adc.id)),
    }
    # One row per evidence key, each nested under "evidence" (the key-name rule needs the nesting);
    # the order is the order the finding stores them in, which is not the order they were raised.
    assert _evidence(text) == {"address": "0x68", "bus": "i2c1"}
    assert sum("evidence" in row for row in rest) == 2


async def test_get_finding_shows_a_few_subjects_and_counts_them_all(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    parts = [await _seed_part(maker, project_id, f"U{n}") for n in range(9)]
    finding = await _seed_finding(maker, project_id, [part.id for part in parts])
    registry = _registry_of(maker, project_id)
    rows = _json_rows(_ok_text(await _invoke(registry, "get_finding", finding_id=str(finding.id))))
    assert rows[0]["subject_count"] == 9
    assert sum("subject" in row for row in rows) == 6
    assert rows[-1] == {"evidence": {"address": "0x68"}}  # the subjects did not crowd it out


async def test_get_finding_shows_the_newest_evidence_not_the_raise_history(
    engine: AsyncEngine,
) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    part = await _seed_part(maker, project_id, "U1 IMU")
    await _seed_finding(maker, project_id, [part.id], evidence={"address": "0x68"})
    again = await _seed_finding(maker, project_id, [part.id], evidence={"address": "0x69"})
    text = _ok_text(
        await _invoke(_registry_of(maker, project_id), "get_finding", finding_id=str(again.id))
    )
    rows = _json_rows(text)
    assert rows[0]["count"] == 2
    assert rows[-1] == {"evidence": {"address": "0x69"}}
    assert "items" not in text


async def test_get_finding_redacts_the_connector_text_it_carries(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    part = await _seed_part(maker, project_id, "U1 IMU")
    finding = await _seed_finding(
        maker,
        project_id,
        [part.id],
        headline="driver init failed: retried with password=hunter2",
        evidence={"config": {"api_key": "abc", "ok": 1}},
    )
    registry = _registry_of(maker, project_id)
    text = _ok_text(await _invoke(registry, "get_finding", finding_id=str(finding.id)))
    assert "password=[REDACTED]" in text
    assert '"api_key":"[REDACTED]"' in text
    for secret in ("hunter2", '"abc"'):
        assert secret not in text


async def test_get_finding_masks_a_secret_named_evidence_key(engine: AsyncEngine) -> None:
    """Each evidence key rides in a row of its own, but nested under "evidence", so `redact_value`
    still sees it beside its value: a producer's `{"password": ...}` is masked, which it was not
    when the pairs were split into sibling fields."""
    maker = _maker(engine)
    project_id = await _new_project(maker)
    part = await _seed_part(maker, project_id, "U1 IMU")
    evidence = {"password": "hunter2", "api_key": "abc123", "bus": "i2c1"}
    finding = await _seed_finding(maker, project_id, [part.id], evidence=evidence)
    registry = _registry_of(maker, project_id)
    text = _ok_text(await _invoke(registry, "get_finding", finding_id=str(finding.id)))
    assert _evidence(text) == {"password": "[REDACTED]", "api_key": "[REDACTED]", "bus": "i2c1"}
    for secret in ("hunter2", "abc123"):
        assert secret not in text


async def test_get_finding_keeps_the_evidence_keys_that_fit_and_marks_the_cut(
    engine: AsyncEngine,
) -> None:
    """One row per key means one key too big for the cap costs only itself: the small keys'
    rows render, the oversized one is gone whole, and the marker says the result was cut."""
    maker = _maker(engine)
    project_id = await _new_project(maker)
    part = await _seed_part(maker, project_id, "U1 IMU")
    # The longest name is stored last (JSONB orders keys by length); its 30 x 400 characters are
    # 12 KB, under what a producer may raise and over what the result may carry.
    evidence = {"a": 1, "bb": 2, "ccc": 3, "zz_oversized_samples": ["v" * 400] * 30}
    finding = await _seed_finding(maker, project_id, [part.id], evidence=evidence)
    registry = _registry_of(maker, project_id)
    *rows, marker = _ok_text(
        await _invoke(registry, "get_finding", finding_id=str(finding.id))
    ).split("\n")
    assert marker == TRUNCATED
    assert [json.loads(row) for row in rows]  # every row kept is whole JSON, never cut inside
    kept = "\n".join(rows)
    assert _evidence(kept) == {"a": 1, "bb": 2, "ccc": 3}
    assert "zz_oversized_samples" not in kept


async def test_get_finding_that_is_not_here_is_the_same_not_found(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    mine, theirs = await _new_project(maker), await _new_project(maker)
    part = await _seed_part(maker, mine, "U1 IMU")
    their_part = await _seed_part(maker, theirs, "U9 IMU")
    foreign = await _seed_finding(maker, theirs, [their_part.id])
    registry = _registry_of(maker, mine)
    absent = _missing_message(await _invoke(registry, "get_finding", finding_id=str(uuid.uuid4())))
    elsewhere = _missing_message(await _invoke(registry, "get_finding", finding_id=str(foreign.id)))
    other_kind = _missing_message(await _invoke(registry, "get_finding", finding_id=str(part.id)))
    assert absent == elsewhere == other_kind == "Finding not found"


async def test_get_finding_refuses_an_id_that_is_not_a_uuid(engine: AsyncEngine) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4())
    result = await _invoke(registry, "get_finding", finding_id="not-a-uuid")
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS


# --------------------------------------------------------------------------- get_run


async def test_get_run_reads_the_recorded_summary(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    run = await _seed_run(maker, project_id, session_id=uuid.uuid4())
    registry = _registry_of(maker, project_id)
    (row,) = _json_rows(_ok_text(await _invoke(registry, "get_run", run_id=str(run.id))))
    assert row["id"] == str(run.id)
    assert (row["name"], row["origin"], row["status"]) == ("Baseline sweep", "live", "completed")
    assert row["robot_id"] == str(run.robot_id)
    assert row["started_at"] == "2026-10-01T00:00:00Z"
    assert (row["packet_count"], row["drop_count"]) == (1200, 3)
    assert row["baseline"] is False  # a plain run says it is not its robot's baseline


async def test_get_run_says_which_run_is_the_baseline(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    baseline = await _seed_run(maker, project_id)
    other = await _seed_run(maker, project_id, robot_id=baseline.robot_id)
    async with maker() as db:
        record = await db.get(GraphEntity, baseline.id)
        assert record is not None
        record.attrs = {**record.attrs, "baseline": True}  # what POST .../baseline writes
        await db.commit()
    registry = _registry_of(maker, project_id)
    flags = {}
    for run in (baseline, other):
        (row,) = _json_rows(_ok_text(await _invoke(registry, "get_run", run_id=str(run.id))))
        flags[row["id"]] = row["baseline"]
    assert flags == {str(baseline.id): True, str(other.id): False}
    # the model is told the row carries it
    assert "baseline" in {d.name: d.description for d in registry.list()}["get_run"]


async def test_get_run_redacts_the_name_a_person_gave_it(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id = await _new_project(maker)
    run = await _seed_run(maker, project_id, name="sweep token=abc123def")
    registry = _registry_of(maker, project_id)
    text = _ok_text(await _invoke(registry, "get_run", run_id=str(run.id)))
    assert "token=[REDACTED]" in text
    assert "abc123def" not in text


async def test_get_run_that_is_not_here_is_the_same_not_found(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    mine, theirs = await _new_project(maker), await _new_project(maker)
    part = await _seed_part(maker, mine, "U1 IMU")
    foreign = await _seed_run(maker, theirs)
    registry = _registry_of(maker, mine)
    absent = _missing_message(await _invoke(registry, "get_run", run_id=str(uuid.uuid4())))
    elsewhere = _missing_message(await _invoke(registry, "get_run", run_id=str(foreign.id)))
    other_kind = _missing_message(await _invoke(registry, "get_run", run_id=str(part.id)))
    assert absent == elsewhere == other_kind == "Run not found"


# ----------------------------------------------------------------------- get_envelope

_NO_ENVELOPE = (
    "no envelope: no limits, definition, scene joint, expected value or baseline for this part"
)


async def test_get_envelope_tells_one_quantity_of_one_part(engine: AsyncEngine) -> None:
    """The fake arm's servo 3: its limits are config, its warn bound is derived, and a quantity
    nothing states is said to have no envelope — never given an invented one."""
    maker = _maker(engine)
    project_id = await _new_project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, project_id, user_id=None)
        await db.commit()
    registry = _registry_of(maker, project_id)
    servo = str(arm.parts[2])

    current = await _invoke(registry, "get_envelope", part_id=servo, quantity="current")
    assert _ok_text(current) == (
        "current A: nominal <= 1, warn <= 1.6, limit <= 2 "
        "(sources: nominal=config, warn=derived, limit=config)"
    )
    position = await _invoke(registry, "get_envelope", part_id=servo, quantity="position")
    assert _ok_text(position) == (
        "position deg: warn -120 to 120, limit -150 to 150 (sources: warn=derived, limit=config)"
    )
    for quantity in ("velocity", "torque"):
        silent = await _invoke(registry, "get_envelope", part_id=servo, quantity=quantity)
        assert _ok_text(silent) == _NO_ENVELOPE
    # a part with no config at all says the same
    bare = await _seed_part(maker, project_id, "U1 IMU")
    nothing = await _invoke(registry, "get_envelope", part_id=str(bare.id), quantity="current")
    assert _ok_text(nothing) == _NO_ENVELOPE


async def test_get_envelope_for_a_part_that_is_not_here_is_the_same_not_found(
    engine: AsyncEngine,
) -> None:
    """Absent, another project's part and something that is no part (the robot) are one answer,
    in the same words, so the tool is no existence oracle across tenants."""
    maker = _maker(engine)
    mine, theirs = await _new_project(maker), await _new_project(maker)
    async with maker() as db:
        arm = await seed_fake_arm(db, mine, user_id=None)
        other = await seed_fake_arm(db, theirs, user_id=None)
        await db.commit()
    registry = _registry_of(maker, mine)

    async def message(part: uuid.UUID) -> str:
        result = await _invoke(registry, "get_envelope", part_id=str(part), quantity="current")
        return _missing_message(result)

    absent = await message(uuid.uuid4())
    assert absent == await message(other.parts[2]) == await message(arm.robot) == "Part not found"


@pytest.mark.parametrize(
    "args",
    [
        {"quantity": "spin"},
        {"quantity": "Current"},
        {"quantity": 7},
        {},
        {"quantity": "current", "project_id": "a project the model is not allowed to name"},
    ],
)
async def test_get_envelope_refuses_arguments_it_was_not_given_a_schema_for(
    engine: AsyncEngine, args: dict[str, Any]
) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4())
    result = await _invoke(registry, "get_envelope", part_id=str(uuid.uuid4()), **args)
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS
    bad_id = await _invoke(registry, "get_envelope", part_id="servo 3", quantity="current")
    assert bad_id.error is not None and bad_id.error.code is ToolErrorCode.INVALID_ARGS


@pytest.mark.parametrize("tool", ["get_finding", "get_run", "get_envelope"])
async def test_an_unknown_argument_is_refused(engine: AsyncEngine, tool: str) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4())
    result = await _invoke(registry, tool, project_id=str(uuid.uuid4()))
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS
