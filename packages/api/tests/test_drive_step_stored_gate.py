"""SOLUSDEV-319: drive.step through the confirmation gate's stored-args path.

A parked `front` step stores the Solus-stamped `window`; the decide-time
execution (`registry.invoke_stored`) validates the stored arguments against
`DriveStepTool.stored_params`, so the step runs on exactly the confirmed window.
A kicad step (no `window`) still parks, decides and runs. The model can never
supply `window` itself (model dispatch validates against `descriptor.params`).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from solus_api.agent.confirmations import decide_confirmation, request_confirmation
from solus_api.agent.drive.binding import FrontAppBinding, WindowBinding
from solus_api.agent.drive.executor import Budget, Progress, StepOutcome
from solus_api.agent.drive.tool import DRIVABLE_APPS, DriveStepStoredArgs, DriveStepTool
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
from solus_api.models import Conversation, Project, Team, User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

FRONT = FrontAppBinding(
    bundle_id="com.prusa3d.slic3r",
    name="PrusaSlicer",
    title="benchy.3mf - PrusaSlicer",
    pid=4321,
    window_id=88,
    drivable=True,
    binding="window",
)
WINDOW: dict[str, Any] = {
    "bundle_id": "com.prusa3d.slic3r",
    "name": "PrusaSlicer",
    "title": "benchy.3mf - PrusaSlicer",
    "pid": 4321,
    "window_id": 88,
}
Scope = tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]


class Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, frozenset[str] | WindowBinding]] = []

    async def __call__(
        self, intent: str, target: frozenset[str] | WindowBinding, on_progress: Any
    ) -> StepOutcome:
        self.calls.append((intent, target))
        on_progress(Progress(action=1, max_actions=15, verb="click", elapsed=0.5))
        return StepOutcome(
            outcome="done", code=None, actions=1, seconds=1.0, summary="Done.", app_name="x"
        )


async def _record(event_type: str, payload: dict[str, Any]) -> None:
    return None


def _registry(runner: Runner, front: FrontAppBinding | None = FRONT) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(DriveStepTool(run_step=runner, record=_record, budget=Budget(), front=front))
    return registry


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _scope(maker: async_sessionmaker[AsyncSession]) -> Scope:
    async with maker() as db:
        user = User(supabase_user_id=f"sub-{uuid.uuid4()}", email=f"{uuid.uuid4()}@e.test")
        team = Team(name="T")
        db.add_all([user, team])
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        conversation = Conversation(project_id=project.id, team_id=team.id, created_by=user.id)
        db.add(conversation)
        await db.commit()
        return project.id, team.id, user.id, conversation.id


async def _park_and_decide(
    maker: async_sessionmaker[AsyncSession],
    park_with: ToolRegistry,
    decide_with: ToolRegistry,
    args: dict[str, Any],
) -> tuple[Any, Any]:
    project_id, team_id, user_id, conversation_id = await _scope(maker)
    async with maker() as db:
        parked = await request_confirmation(
            db,
            park_with,
            ToolCall(tool="drive.step", args=args),
            project_id=project_id,
            team_id=team_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        await db.commit()
    assert parked is not None and parked.confirmation_id is not None, parked
    async with maker() as db:
        result = await decide_confirmation(
            db,
            decide_with,
            parked.confirmation_id,
            approve=True,
            project_id=project_id,
            user_id=user_id,
        )
        await db.commit()
    return parked, result


def test_stored_params_is_the_stored_args_model_schema() -> None:
    tool = DriveStepTool(run_step=Runner(), record=_record, budget=Budget(), front=FRONT)
    assert tool.stored_params == DriveStepStoredArgs.model_json_schema()
    assert "window" not in tool.descriptor.params["properties"]


async def test_a_parked_front_step_decides_and_runs_on_the_stored_window(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    runner = Runner()
    registry = _registry(runner)
    parked, result = await _park_and_decide(
        maker, registry, registry, {"app": "front", "intent": "Rotate the model"}
    )
    assert parked.args == {"app": "front", "intent": "Rotate the model", "window": WINDOW}
    assert result.ok is True, result.error
    assert runner.calls == [("Rotate the model", WindowBinding.model_validate(WINDOW))]


async def test_a_front_step_decided_in_a_later_turn_without_front_still_runs(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The decide request's tool has no `front` offered: the stored window rules."""
    runner = Runner()
    _, result = await _park_and_decide(
        maker,
        _registry(Runner()),
        _registry(runner, front=None),
        {"app": "front", "intent": "Rotate the model"},
    )
    assert result.ok is True, result.error
    assert runner.calls == [("Rotate the model", WindowBinding.model_validate(WINDOW))]


async def test_a_kicad_step_still_parks_decides_and_runs(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    runner = Runner()
    registry = _registry(runner)
    parked, result = await _park_and_decide(
        maker, registry, registry, {"app": "kicad", "intent": "Place R1"}
    )
    assert parked.args == {"app": "kicad", "intent": "Place R1"}
    assert result.ok is True, result.error
    assert runner.calls == [("Place R1", DRIVABLE_APPS["kicad"])]


async def test_model_dispatch_never_accepts_a_window() -> None:
    runner = Runner()
    result = await _registry(runner).invoke(
        ToolCall(tool="drive.step", args={"app": "front", "intent": "Rotate", "window": WINDOW})
    )
    assert result.error is not None and result.error.code is ToolErrorCode.INVALID_ARGS
    assert runner.calls == []


async def test_invoke_stored_rejects_a_malformed_stored_window() -> None:
    runner = Runner()
    bad = {"app": "front", "intent": "Rotate", "window": {**WINDOW, "pid": 0}}
    result = await _registry(runner).invoke_stored(ToolCall(tool="drive.step", args=bad))
    assert result.error is not None and result.error.code is ToolErrorCode.INVALID_ARGS
    assert runner.calls == []
