"""SOLUSDEV-321 P6 (R134) — `agent/firmware_recipe.py`: firmware for a board from the graph's
topology. The recipe reads the topology under the asker's scope and the current file through the
owned write's dry run (nothing is written), makes ONE model call as the requester with the facts
fenced as data, refuses what a write card cannot show, and routes the turn so the Build policy
forces `machine.write_file`'s card: the person asked for firmware, not for a write."""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fixtures.fake_arm import CODE_PATH, FakeArm, seed_fake_arm
from solus_api.agent import firmware_recipe
from solus_api.agent.execution_policy import BuildExecutionPolicy, register_owned_routine
from solus_api.agent.firmware_recipe import (
    FIRMWARE_RECIPE,
    FirmwareRecipe,
    routed_by_firmware,
)
from solus_api.agent.modes import ActionMode
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools.machine_writes import (
    CARD_ROWS,
    ROW_CHARS,
    MachineWriteTool,
    build_machine_write_tool,
    card_rows,
)
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.turn_budget import TurnBudget
from solus_api.agent.turn_context import PerceptionTurn, bind_perception, bind_turn_id
from solus_api.agent.turn_limits import turn_limits
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.graph.edges import retire_edge
from solus_api.models import DataEvent, GraphEdge, Project, Team, User
from solus_api.orchestration import gateway
from solus_api.orchestration.providers import ProviderRefusalError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_machine_writes import Telling

CURRENT = "// the arm's firmware today\nvoid setup() {}\nvoid loop() {}\n"
PROPOSED = "#include <SolusTelemetry.h>\n// commands servo 1..6\nvoid setup() {}\nvoid loop() {}\n"
STYLE = "two-space indent; no macros"


class _Arm:
    """A project holding the fake arm, a person who consented to data collection, and the
    linked folder holding the arm's firmware."""

    def __init__(self, project_id: uuid.UUID, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.project_id, self.team_id, self.user_id = project_id, team_id, user_id
        self.arm: FakeArm


async def _arm(db: AsyncSession, root: Path) -> _Arm:
    team = Team(name="firmware")
    db.add(team)
    await db.flush()
    project = Project(team_id=team.id, name="firmware")
    user = User(supabase_user_id=f"fw-{uuid.uuid4()}", email="fw@example.com")
    user.data_collection_consent = True
    db.add_all([project, user])
    await db.flush()
    held = _Arm(project.id, team.id, user.id)
    held.arm = await seed_fake_arm(db, project.id, user_id=None)
    await db.commit()
    (root / CODE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / CODE_PATH).write_text(CURRENT)
    return held


def _recipe(engine: AsyncEngine, held: _Arm, writer: MachineWriteTool) -> FirmwareRecipe:
    return FirmwareRecipe(
        sessions=async_sessionmaker(engine, expire_on_commit=False),
        project_id=held.project_id,
        user_id=held.user_id,
        team_id=held.team_id,
        writer=writer,
        secret_store=InMemorySecretStore(),
        redis=None,
        enqueue=None,
    )


def _budget() -> TurnBudget:
    budget = TurnBudget(replace(turn_limits(ActionMode.DO), max_model_calls=6))
    budget.note_model_call()  # the round that proposed the call
    return budget


def _replying(monkeypatch: pytest.MonkeyPatch, text: str) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def complete(query: str, **kwargs: Any) -> Any:
        calls.append((query, kwargs))
        return SimpleNamespace(text=text)

    monkeypatch.setattr(gateway, "complete", complete)
    return calls


async def test_rmw_behind_card_and_refuses_above_ceiling(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = await _arm(db, tmp_path)
    writer = build_machine_write_tool(Telling(tmp_path))
    calls = _replying(monkeypatch, f"```cpp\n{PROPOSED}```\n")
    budget, turn = _budget(), uuid.uuid4()
    args = {"board_id": str(held.arm.brain), "path": CODE_PATH}

    with bind_turn_id(turn), bind_perception(PerceptionTurn(budget, code_style=STYLE)):
        answer = await _recipe(engine, held, writer).prepare(args)
        routed = routed_by_firmware("machine.write_file")
        other_tool = routed_by_firmware("code.exec")
        registry = ToolRegistry()
        register_owned_routine(writer, family="machine")
        registry.register(writer)
        write = ToolCall(tool="machine.write_file", args={"path": CODE_PATH, "content": PROPOSED})
        carded = await BuildExecutionPolicy(registry, ActionMode.DO).prepare(write)
    with bind_turn_id(uuid.uuid4()):
        elsewhere = routed_by_firmware("machine.write_file")

    # the read-modify-write: the current file read, nothing written, the new file proposed
    assert answer == {
        "path": CODE_PATH,
        "content": PROPOSED,
        "card_rows": card_rows(CURRENT, PROPOSED),
        "next": firmware_recipe.NEXT,
    }
    assert (tmp_path / CODE_PATH).read_text() == CURRENT
    # ONE call, as the requester, in its turn, on the turn's budget; facts fenced as data
    ((query, kwargs),) = calls
    assert query.startswith(FIRMWARE_RECIPE)
    for kind in ("topology", "pins", "telemetry_library", "current_file", "code_style"):
        assert f"kind={kind}>>>" in query, kind
    assert "servo1.position" in query and f"{CODE_PATH}:11" in query and STYLE in query
    assert "the arm's firmware today" in query
    assert kwargs["user_id"] == held.user_id and kwargs["turn_id"] == turn
    assert kwargs["project_id"] == held.project_id  # its usage row names the project (R148)
    assert kwargs["purpose"] == "answer" and kwargs["session"] is not None and "redis" in kwargs
    assert budget.model_calls == 2
    # the write keeps its card in this turn only, and only the write
    assert (routed, other_tool, elsewhere, carded) == (True, False, False, False)
    events = list(
        await db.scalars(select(DataEvent).where(DataEvent.project_id == held.project_id))
    )
    assert [e.event_type for e in events] == ["sol.firmware_recipe.prepared"]
    assert set(events[0].payload) == {"card_rows", "commands", "pins", "channels"}

    # a reply no write card can show is refused, naming the ceiling, and nothing is proposed
    _replying(monkeypatch, "x" * (ROW_CHARS * CARD_ROWS))
    with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(_budget())):
        with pytest.raises(ToolException) as refused:
            await _recipe(engine, held, writer).prepare(args)
    assert f"{CARD_ROWS} rows of {ROW_CHARS} characters" in refused.value.message


def _spied(writer: MachineWriteTool, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The paths the recipe asks the owned write to read."""
    read: list[str] = []
    real = writer.current_text

    async def current_text(path: str) -> str | None:
        read.append(path)
        return await real(path)

    monkeypatch.setattr(writer, "current_text", current_text)
    return read


async def test_a_path_the_graph_does_not_name_is_refused_before_anything_is_read(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R138: the path is decided first. One the topology does not name as the board's firmware is
    refused in words that do not say whether it exists, and the companion is never asked."""
    held = await _arm(db, tmp_path)
    writer = build_machine_write_tool(Telling(tmp_path))
    read, calls = _spied(writer, monkeypatch), _replying(monkeypatch, PROPOSED)
    said: list[str] = []
    for exists in (True, False):
        notes = tmp_path / "notes.txt"
        notes.write_text("not firmware\n") if exists else notes.unlink()
        with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(_budget())):
            with pytest.raises(ToolException) as refused:
                await _recipe(engine, held, writer).prepare(
                    {"board_id": str(held.arm.brain), "path": "notes.txt"}
                )
        said.append(refused.value.message)
    assert said[0] == said[1]
    assert (
        said[0]
        == f"The graph does not name notes.txt as this board's firmware; named: {CODE_PATH}."
    )
    assert read == [] and calls == []


async def test_the_boards_own_file_past_the_ceiling_is_refused_naming_it(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = await _arm(db, tmp_path)
    writer = build_machine_write_tool(Telling(tmp_path))
    calls = _replying(monkeypatch, PROPOSED)
    (tmp_path / CODE_PATH).write_text("x" * (ROW_CHARS * (CARD_ROWS - 2) + 1))
    with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(_budget())):
        with pytest.raises(ToolException) as refused:
            await _recipe(engine, held, writer).prepare(
                {"board_id": str(held.arm.brain), "path": CODE_PATH}
            )
    assert f"{CARD_ROWS} rows of {ROW_CHARS} characters" in refused.value.message
    assert calls == []


async def test_a_board_with_no_firmware_yet_gets_a_new_file_without_a_read(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R138: with no firmware named for the board, the recipe writes a new file from the topology
    alone. It reads nothing, existing or not: the write's card shows anything it would replace."""
    held = await _arm(db, tmp_path)
    for edge in await db.scalars(select(GraphEdge).where(GraphEdge.relation_type == "commands")):
        retire_edge(edge)
    await db.commit()
    writer = build_machine_write_tool(Telling(tmp_path))
    read, calls = _spied(writer, monkeypatch), _replying(monkeypatch, PROPOSED)
    with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(_budget())):
        answer = await _recipe(engine, held, writer).prepare(
            {"board_id": str(held.arm.brain), "path": CODE_PATH}
        )
    assert answer["content"] == PROPOSED and answer["card_rows"] == card_rows("", PROPOSED)
    ((query, _kwargs),) = calls
    assert '"text":null' in query and read == []  # nothing read, though the file is there


async def test_the_recipe_needs_a_board_a_turn_and_a_model_call_left(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = await _arm(db, tmp_path)
    recipe = _recipe(engine, held, build_machine_write_tool(Telling(tmp_path)))
    calls = _replying(monkeypatch, PROPOSED)
    board = {"board_id": str(held.arm.brain), "path": CODE_PATH}
    spent = TurnBudget(replace(turn_limits(ActionMode.DO), max_model_calls=1))
    spent.note_model_call()

    with pytest.raises(ToolException):  # outside a turn
        await recipe.prepare(board)
    with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(_budget())):
        for wrong in ({**board, "board_id": str(held.arm.robot)}, {**board, "extra": 1}):
            with pytest.raises(ToolException):
                await recipe.prepare(wrong)
    with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(spent)):
        with pytest.raises(ToolException) as refused:
            await recipe.prepare(board)
    assert "model call" in refused.value.message and calls == []


async def test_another_projects_board_is_refused_as_no_board_and_nothing_is_read(
    db: AsyncSession, engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P6 fix 1 (m7), the §7 isolation proof: another project's board is refused in the same
    words as an id that names nothing, before the companion or the model is asked anything."""
    held, theirs = await _arm(db, tmp_path), await _arm(db, tmp_path / "theirs")
    writer = build_machine_write_tool(Telling(tmp_path))
    read, calls = _spied(writer, monkeypatch), _replying(monkeypatch, PROPOSED)
    said: list[tuple[str, str]] = []
    for board in (theirs.arm.brain, uuid.uuid4()):
        with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(_budget())):
            with pytest.raises(ToolException) as refused:
                await _recipe(engine, held, writer).prepare(
                    {"board_id": str(board), "path": CODE_PATH}
                )
        said.append((refused.value.message, refused.value.code))
    assert said == [("board_id names no board in this project.", "not_found")] * 2
    assert read == [] and calls == []


@pytest.mark.parametrize(
    ("failure", "retryable"),
    [
        (ProviderRefusalError("anthropic/claude-x refused the request", category="cyber"), False),
        (RuntimeError("upstream hiccup"), True),
    ],
)
async def test_a_refused_recipe_call_is_not_offered_as_retryable(
    db: AsyncSession,
    engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    retryable: bool,
) -> None:
    """SOLUSDEV-319: a refusal repeats for the same request, so the model is not invited to retry
    it (and burn the turn's calls); any other failure stays retryable."""
    held = await _arm(db, tmp_path)
    writer = build_machine_write_tool(Telling(tmp_path))

    async def complete(query: str, **kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(gateway, "complete", complete)
    with bind_turn_id(uuid.uuid4()), bind_perception(PerceptionTurn(_budget())):
        with pytest.raises(ToolException) as raised:
            await _recipe(engine, held, writer).prepare(
                {"board_id": str(held.arm.brain), "path": CODE_PATH}
            )
    assert raised.value.code is ToolErrorCode.UNAVAILABLE
    assert raised.value.retryable is retryable
