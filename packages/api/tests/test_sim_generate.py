"""SOLUSDEV-322 P6-T2 — `sim.generate_model`: a static card whose preview IS the gap report and
whose approval enqueues `run_generate_sim_model`. Nothing here runs the job or a simulator: the
graph is the scripted CAD arm of `test_model_job`, the queue a mock.
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.confirmations import request_confirmation
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.runtime import DispatchFn, build_dispatch, build_sol_registry
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
from solus_api.agent.tools.sim_generate import NAME, SimGenerateTool, gap_report_rows
from solus_api.agent.tools.tool import ToolException
from solus_api.models import Project, ToolConfirmation
from solus_api.simulation.model_job import JOB, GenerateModelRequest, gap_report, gather
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_model_job import CadArm, Maker, cad_arm, footprint


@pytest.fixture
def maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


def _tool(maker: Maker, arm: CadArm, enqueue: Any | None) -> SimGenerateTool:
    return SimGenerateTool(maker, arm.project_id, user_id=arm.user_id, enqueue_sim=enqueue)


def _dispatch(mode: ActionMode, registry: ToolRegistry, maker: Maker, arm: CadArm) -> DispatchFn:
    async def park(call: ToolCall) -> Any:
        async with maker() as session:
            project = await session.get(Project, arm.project_id)
            assert project is not None
            parked = await request_confirmation(
                session,
                registry,
                call,
                project_id=arm.project_id,
                team_id=project.team_id,
                user_id=arm.user_id,
            )
            await session.commit()
            return parked

    return build_mode_dispatch(
        mode, registry.list(), build_dispatch(registry, park), registry=registry
    )


async def test_generate_is_a_card_whose_preview_is_the_gap_report(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch)
    enqueue = AsyncMock(return_value="job-1")
    registry = ToolRegistry()
    registry.register(_tool(maker, arm, enqueue))
    args = {"robot_id": str(arm.robot.id), "name": "Arm"}
    call = ToolCall(tool=NAME, args=args)
    async with maker() as session:
        report = gap_report(
            await gather(session, GenerateModelRequest.model_validate(arm.request()))
        )
    expected = gap_report_rows(report)

    parked = await _dispatch(ActionMode.DO, registry, maker, arm)(call)

    assert not parked.ok and parked.error is not None
    assert parked.error.code is ToolErrorCode.UNAUTHORIZED
    async with maker() as session:
        rows = list(await session.scalars(select(ToolConfirmation)))
    assert [(r.tool, r.args) for r in rows] == [(NAME, args)]
    assert rows[0].preview == expected
    # The card shows every property and every gap of the report, in its order.
    labels = [row["label"] for row in expected]
    assert labels == [p["name"] for p in report["properties"]] + [g["name"] for g in report["gaps"]]
    assert {"label": "base.mass", "before": None, "after": "1.5 kg (cad_mass)"} in expected
    gap = next(row for row in expected if row["label"] == "tip.mass")
    assert gap["after"] is not None and gap["after"].startswith("GAP")
    assert "mass_properties" in gap["after"]
    enqueue.assert_not_awaited()  # parking a card runs nothing

    refused = await _dispatch(ActionMode.GUIDE, registry, maker, arm)(call)
    assert not refused.ok and refused.error is not None
    assert "Guide mode can explain" in refused.error.message
    enqueue.assert_not_awaited()

    # Approval (the confirmation flow) runs `invoke`: one job, keyed by the request.
    value = await registry.tools()[0].invoke(args)

    enqueue.assert_awaited_once_with(
        JOB,
        str(arm.project_id),
        {
            "project_id": str(arm.project_id),
            "robot_id": str(arm.robot.id),
            "name": "Arm",
            "requested_by": str(arm.user_id),
            "source_entity_id": None,
        },
    )
    assert value["status"] == "queued" and value["job_id"] == "job-1"
    assert value["gaps"] == report["gaps"]


async def test_generate_refuses_the_card_when_no_mate_can_move_and_without_a_queue(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch, frames=(False, False))
    args = {"robot_id": str(arm.robot.id), "name": "Arm"}

    with pytest.raises(PreviewRefusal, match="frame"):
        await _tool(maker, arm, AsyncMock()).preview(args)

    framed = await cad_arm(db, client, alice_headers, app, monkeypatch)
    with pytest.raises(ToolException) as refused:
        await _tool(maker, framed, None).invoke({"robot_id": str(framed.robot.id), "name": "Arm"})
    assert refused.value.code is ToolErrorCode.UNAVAILABLE
    # A robot without a CAD import, a foreign robot and hostile arguments are refused, not parked.
    with pytest.raises(PreviewRefusal, match="CAD"):
        await _tool(maker, framed, None).preview({"robot_id": str(uuid.uuid4()), "name": "Arm"})
    for bad in (
        {"robot_id": "robot", "name": "Arm"},
        {"robot_id": str(framed.robot.id), "name": "-rf"},
    ):
        with pytest.raises(ToolException) as invalid:
            await _tool(maker, framed, None).preview(bad)
        assert invalid.value.code is ToolErrorCode.INVALID_ARGS


async def test_generate_is_registered_gated_only_when_a_person_is_bound(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch)

    bare = {d.name for d in build_sol_registry(maker, arm.project_id).list()}
    bound = build_sol_registry(maker, arm.project_id, user_id=arm.user_id)

    assert NAME not in bare
    descriptor = next(d for d in bound.list() if d.name == NAME)
    assert descriptor.requires_confirmation is True
    tool = next(t for t in bound.tools() if t.descriptor.name == NAME)
    assert getattr(tool, "requires_complete_preview", False) is True


def test_gap_report_rows_are_bounded_to_the_card() -> None:
    report = {
        "properties": [
            {"name": f"link{i}.mass", "value": 0.5, "unit": "kg", "source": "cad_mass"}
            for i in range(60)
        ],
        "gaps": [{"name": "j.frame", "set_in": "x" * 900}],
    }
    rows = gap_report_rows(report)
    assert len(rows) == 50 and rows[-1]["label"].startswith("… and 12 more")
    assert all(len(row["after"] or "") <= 500 for row in rows)


async def test_another_projects_robot_is_refused_nothing_queued_nothing_written(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant isolation (CLAUDE.md §7): project A's tool, handed project B's robot or B's assembly,
    refuses at preview and at invoke, queues no job, parks nothing and writes to neither graph."""
    mine = await cad_arm(db, client, alice_headers, app, monkeypatch)
    theirs = await cad_arm(db, client, bob_headers, app, monkeypatch)
    enqueue = AsyncMock(return_value="job-x")
    tool = _tool(maker, mine, enqueue)
    before = await footprint(maker, mine.project_id, theirs.project_id)
    foreign = [
        {"robot_id": str(theirs.robot.id), "name": "Arm"},
        {"robot_id": str(theirs.robot.id), "name": "Arm", "source_entity_id": str(theirs.root.id)},
        {"robot_id": str(mine.robot.id), "name": "Arm", "source_entity_id": str(theirs.root.id)},
    ]

    for args in foreign:
        for step in (tool.preview, tool.invoke):
            with pytest.raises(PreviewRefusal, match="CAD") as refused:
                await step(args)
            assert str(theirs.root.id) not in str(refused.value), (args, step)

    enqueue.assert_not_awaited()
    assert await footprint(maker, mine.project_id, theirs.project_id) == before
    async with maker() as session:
        assert list(await session.scalars(select(ToolConfirmation))) == []


#: One line, ends in a period, no absolute path: what SOL repeats to the person as it is.
SENTENCE = re.compile(r"[^\n]*\S\.")


async def test_every_failure_result_has_a_reason_sentence(
    db: AsyncSession,
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    maker: Maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P7-T2 (missing inputs): the gap-report refusals — no CAD import, no mate that can move —
    and the missing queue each reach SOL as one line it can repeat, never a doubled period."""
    arm = await cad_arm(db, client, alice_headers, app, monkeypatch, frames=(False, False))
    with pytest.raises(PreviewRefusal) as no_cad:
        await _tool(maker, arm, None).preview({"robot_id": str(uuid.uuid4()), "name": "Arm"})
    assert no_cad.value.message == (
        "No CAD import exists for this robot; import its CAD first. Nothing was parked."
    )
    with pytest.raises(PreviewRefusal) as no_frame:
        await _tool(maker, arm, None).preview({"robot_id": str(arm.robot.id), "name": "Arm"})
    with pytest.raises(ToolException) as no_queue:
        await _tool(maker, arm, None).invoke({"robot_id": str(arm.robot.id), "name": "Arm"})
    for message in (no_cad.value.message, no_frame.value.message, no_queue.value.message):
        assert SENTENCE.fullmatch(message) and ".." not in message, message
