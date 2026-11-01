"""SOLUSDEV-319 G1: Solus-derived stored arguments and informational card rows.

A gated tool may add fields Solus derives (drive.step's front-app `window`
binding) to the arguments it parks via `stored_args(args)`. The model can never
supply those fields — model-facing validation is unchanged — but the card, the
duplicate check, the stored row and the decide-time execution all read the
stored arguments, validated against the tool's `stored_params` schema.

Informational rows (`Simulate first`, `Current value`) are left out of the
stale-divergence key: a live reading moving between preview and approval must
not void the card, while a changed Target must.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from jsonschema.exceptions import SchemaError
from solus_api.agent.confirmations import (
    INFORMATIONAL_LABELS,
    decide_confirmation,
    request_confirmation,
)
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.models import (
    ConfirmationStatus,
    Conversation,
    Project,
    Team,
    ToolConfirmation,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_MODEL_PARAMS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent"],
    "properties": {"intent": {"type": "string", "minLength": 1}},
}
_STORED_PARAMS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "window"],
    "properties": {
        "intent": {"type": "string", "minLength": 1},
        "window": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "title", "pid"],
            "properties": {
                "name": {"type": "string"},
                "title": {"type": "string"},
                "pid": {"type": "integer"},
            },
        },
    },
}
WINDOW = {"name": "Fusion", "title": "bracket.f3d", "pid": 4242}


class StampedTool:
    """A gated tool whose stored arguments carry a Solus-stamped window."""

    def __init__(self, *, stored_params: dict[str, Any] | None = _STORED_PARAMS) -> None:
        self.descriptor = ToolDescriptor(
            name="fake.front_step",
            description="Do one step in the front window.",
            consent_summary="SOL will act in the front window",
            params=_MODEL_PARAMS,
            returns={"type": "object"},
            requires_confirmation=True,
        )
        if stored_params is not None:
            self.stored_params = stored_params
        self.ran: list[dict[str, Any]] = []
        self.current = "12.4 deg"
        self.target = "40.0 deg"

    def stored_args(self, args: dict[str, Any]) -> dict[str, Any]:
        if args["intent"] == "no window":
            raise ToolException(
                "fake.front_step needs a summoned window", code=ToolErrorCode.INVALID_ARGS
            )
        return {**args, "window": dict(WINDOW)}

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"label": "App", "before": None, "after": args["window"]["name"]},
            {"label": "Window", "before": None, "after": args["window"]["title"]},
            {"label": "Current value", "before": None, "after": self.current},
            {"label": "Target", "before": None, "after": self.target},
        ]

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        self.ran.append(args)
        return {"done": True}


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _scope(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
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


def _registry(tool: StampedTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


async def _park(
    maker: async_sessionmaker[AsyncSession],
    registry: ToolRegistry,
    args: dict[str, Any],
    scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
):  # type: ignore[no-untyped-def]
    project_id, team_id, user_id, conversation_id = scope
    async with maker() as db:
        parked = await request_confirmation(
            db,
            registry,
            ToolCall(tool="fake.front_step", args=args),
            project_id=project_id,
            team_id=team_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        await db.commit()
    assert parked is not None
    return parked


async def _decide(
    maker: async_sessionmaker[AsyncSession],
    registry: ToolRegistry,
    confirmation_id: uuid.UUID,
    scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
):  # type: ignore[no-untyped-def]
    project_id, _, user_id, _ = scope
    async with maker() as db:
        result = await decide_confirmation(
            db, registry, confirmation_id, approve=True, project_id=project_id, user_id=user_id
        )
        await db.commit()
    return result


async def _rows(maker: async_sessionmaker[AsyncSession]) -> list[ToolConfirmation]:
    async with maker() as db:
        return list(
            await db.scalars(
                select(ToolConfirmation).where(ToolConfirmation.tool == "fake.front_step")
            )
        )


# ---------------------------------------------------------------- parking


async def test_park_stores_the_solus_stamped_window_and_the_card_shows_it(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _scope(maker)
    parked = await _park(maker, _registry(StampedTool()), {"intent": "Rotate it"}, scope)

    assert parked.confirmation_id is not None
    assert parked.args == {"intent": "Rotate it", "window": WINDOW}
    labels = {row["label"]: row["after"] for row in parked.preview}
    assert labels["App"] == "Fusion"
    assert labels["Window"] == "bracket.f3d"
    async with maker() as db:
        row = await db.get(ToolConfirmation, parked.confirmation_id)
    assert row is not None
    assert row.args == {"intent": "Rotate it", "window": WINDOW}
    assert row.preview == parked.preview


async def test_a_model_supplied_stored_only_field_is_invalid_args_and_not_parked(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _scope(maker)
    forged = {"intent": "Rotate it", "window": {"name": "x", "title": "y", "pid": 1}}
    parked = await _park(maker, _registry(StampedTool()), forged, scope)

    assert parked.confirmation_id is None
    assert parked.result.error is not None
    assert parked.result.error.code is ToolErrorCode.INVALID_ARGS
    assert await _rows(maker) == []


async def test_a_tool_exception_from_stored_args_refuses_without_parking(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _scope(maker)
    parked = await _park(maker, _registry(StampedTool()), {"intent": "no window"}, scope)

    assert parked.confirmation_id is None
    assert parked.preview == []
    assert parked.result.error is not None
    assert parked.result.error.code is ToolErrorCode.INVALID_ARGS
    assert parked.result.error.message == "fake.front_step needs a summoned window"
    assert await _rows(maker) == []


async def test_the_duplicate_check_compares_stored_args(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _scope(maker)
    registry = _registry(StampedTool())
    first = await _park(maker, registry, {"intent": "Rotate it"}, scope)
    again = await _park(maker, registry, {"intent": "Rotate it"}, scope)

    assert again.confirmation_id == first.confirmation_id
    assert len(await _rows(maker)) == 1


# --------------------------------------------------------------- deciding


async def test_decide_accepts_the_stored_window_and_executes_exactly_it(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _scope(maker)
    tool = StampedTool()
    registry = _registry(tool)
    parked = await _park(maker, registry, {"intent": "Rotate it"}, scope)

    result = await _decide(maker, registry, parked.confirmation_id, scope)

    assert result.ok is True, result.error
    assert tool.ran == [{"intent": "Rotate it", "window": WINDOW}]


async def test_without_stored_params_decide_falls_back_to_the_model_schema(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _scope(maker)
    tool = StampedTool(stored_params=None)
    registry = _registry(tool)
    parked = await _park(maker, registry, {"intent": "Rotate it"}, scope)

    result = await _decide(maker, registry, parked.confirmation_id, scope)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS
    assert tool.ran == []


async def test_a_changed_current_value_does_not_void_the_card(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _scope(maker)
    tool = StampedTool()
    registry = _registry(tool)
    parked = await _park(maker, registry, {"intent": "Rotate it"}, scope)
    tool.current = "13.9 deg"

    result = await _decide(maker, registry, parked.confirmation_id, scope)

    assert result.ok is True, result.error
    assert len(tool.ran) == 1


async def test_a_changed_target_makes_the_card_stale(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    scope = await _scope(maker)
    tool = StampedTool()
    registry = _registry(tool)
    parked = await _park(maker, registry, {"intent": "Rotate it"}, scope)
    tool.target = "95.0 deg (requested 120.0 deg, clamped to calibrated range)"

    result = await _decide(maker, registry, parked.confirmation_id, scope)

    assert result.ok is False
    assert tool.ran == []
    async with maker() as db:
        row = await db.get(ToolConfirmation, parked.confirmation_id)
    assert row is not None
    assert row.status is ConfirmationStatus.STALE


def test_informational_labels_are_a_solus_owned_constant() -> None:
    assert frozenset({"Simulate first", "Current value"}) == INFORMATIONAL_LABELS


# --------------------------------------------------------------- registry


async def test_the_model_path_never_accepts_stored_only_fields() -> None:
    tool = StampedTool()
    registry = _registry(tool)
    call = ToolCall(tool="fake.front_step", args={"intent": "Rotate it", "window": WINDOW})

    result = await registry.invoke(call)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS
    assert tool.ran == []


async def test_the_stored_path_validates_against_stored_params() -> None:
    tool = StampedTool()
    registry = _registry(tool)

    ok = await registry.invoke_stored(
        ToolCall(tool="fake.front_step", args={"intent": "Rotate it", "window": WINDOW})
    )
    missing = await registry.invoke_stored(
        ToolCall(tool="fake.front_step", args={"intent": "Rotate it"})
    )

    assert ok.ok is True
    assert missing.ok is False
    assert missing.error is not None
    assert missing.error.code is ToolErrorCode.INVALID_ARGS
    assert tool.ran == [{"intent": "Rotate it", "window": WINDOW}]


def test_a_malformed_stored_params_schema_fails_at_registration() -> None:
    with pytest.raises(SchemaError):
        ToolRegistry().register(StampedTool(stored_params={"type": "not-a-type"}))
