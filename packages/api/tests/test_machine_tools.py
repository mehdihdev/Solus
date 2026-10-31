"""SOLUSDEV-321 P1-T4 — `get_machine`, `get_environment_divergences` and `get_history`.

Driven through `register_machine_tools` on a real `ToolRegistry` against the real database, bound
to the requesting member the way the SOL route binds it. A machine belongs to the member who
registered it: another member's recent commands are never returned, however the model phrases the
request (CLAUDE.md §7); and nothing here reaches another project's machines, tables or history.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from solus_api.agent.tools import ToolCall, ToolErrorCode, ToolRegistry, ToolResult
from solus_api.agent.tools.machine_tools import get_history_handler, register_machine_tools
from solus_api.agent.tools.read_tool import MAX_ROWS, MORE, TRUNCATED
from solus_api.models import GraphEntity, Project, SolusEntry, SolusSection, Team, User, utcnow
from solus_api.services.activity import record_activity, record_project_activity
from solus_api.services.machines import MachineIn, upsert_machine
from solus_api.services.solus_config import put_config_entry
from solus_api.services.solus_payloads import (
    DivergenceGroup,
    DivergenceItem,
    EnvironmentDivergencesDoc,
    MachineDivergences,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]

MINE = "0123456789abcdef0123456789abcdef"
THEIRS = "fedcba9876543210fedcba9876543210"
_T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _maker(engine: AsyncEngine) -> Maker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _new_project(maker: Maker) -> tuple[uuid.UUID, uuid.UUID]:
    """(project id, team id)."""
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="Rover")
        db.add(project)
        await db.commit()
        return project.id, team.id


async def _seed_member(maker: Maker, email: str) -> uuid.UUID:
    async with maker() as db:
        user = User(supabase_user_id=uuid.uuid4().hex, email=email)
        db.add(user)
        await db.commit()
        return user.id


async def _seed_machine(
    maker: Maker,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    companion_id: str,
    hostname: str,
    *,
    commands: list[dict[str, Any]] | None = None,
    versions: dict[str, str] | None = None,
) -> GraphEntity:
    async with maker() as db:
        machine = await upsert_machine(
            db,
            project_id,
            user_id,
            companion_id,
            MachineIn(hostname=hostname, os="linux", arch="arm64"),
            tool_versions=versions or {"python3": "Python 3.12.3"},
        )
        machine.attrs = {**machine.attrs, "recent_commands": commands or []}
        await db.commit()
        return machine


def _logged_command(n: int, **over: Any) -> dict[str, Any]:
    entry = {
        "command_redacted": f"cmd {n}",
        "cwd": f"/work/{n}",
        "exit_code": n,
        "output_tail": f"tail {n}",
    }
    return {**entry, **over}


def _registry_of(maker: Maker, project_id: uuid.UUID, user_id: uuid.UUID) -> ToolRegistry:
    registry = ToolRegistry()
    register_machine_tools(registry, maker, project_id, user_id=user_id)
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


def _missing_message(result: ToolResult) -> str:
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND
    return result.error.message


# --------------------------------------------------------------------- the registry


async def test_the_tools_register_read_only_and_ungated(engine: AsyncEngine) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4(), uuid.uuid4())
    descriptors = {d.name: d for d in registry.list()}
    assert set(descriptors) == {"get_machine", "get_environment_divergences", "get_history"}
    for descriptor in descriptors.values():
        assert descriptor.requires_confirmation is False
        assert descriptor.files_errors is False
        assert descriptor.result_cap == 8_000
        assert "Read-only" in descriptor.description
    assert descriptors["get_machine"].params["required"] == ["companion_id"]


# ------------------------------------------------------------------------ get_machine


async def test_get_machine_returns_the_owners_machine_and_its_five_newest_commands(
    engine: AsyncEngine,
) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    alice = await _seed_member(maker, "alice@x.io")
    machine = await _seed_machine(
        maker,
        project_id,
        alice,
        MINE,
        "alice-box",
        commands=[_logged_command(n) for n in range(1, 8)],
        versions={"python3": "Python 3.12.3", "git": "git version 2.45.0"},
    )
    registry = _registry_of(maker, project_id, alice)
    text = _ok_text(await _invoke(registry, "get_machine", companion_id=MINE))
    head, versions, *commands = _json_rows(text)
    assert head == {
        "machine": "alice-box",
        "os": "linux",
        "arch": "arm64",
        "id": str(machine.id),
        "owner": "you",
    }
    # The tool versions are ONE row, a mapping keyed by tool, not a row per tool.
    assert versions == {"tool_versions": {"git": "git version 2.45.0", "python3": "Python 3.12.3"}}
    assert [command["command_redacted"] for command in commands] == [
        f"cmd {n}" for n in (7, 6, 5, 4, 3)
    ]
    assert commands[0] == {
        "command_redacted": "cmd 7",
        "cwd": "/work/7",
        "exit_code": "7",
        "output_tail": "tail 7",
    }
    assert "cmd 2" not in text
    assert "withheld" not in text


async def test_get_machine_shows_every_binary_the_companion_reports(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    alice = await _seed_member(maker, "alice@x.io")
    reported = {f"tool{n:02d}": f"{n}.0" for n in range(10)}  # the companion reports ten at most
    await _seed_machine(maker, project_id, alice, MINE, "alice-box", versions=reported)
    registry = _registry_of(maker, project_id, alice)
    rows = _json_rows(_ok_text(await _invoke(registry, "get_machine", companion_id=MINE)))
    assert rows[1] == {"tool_versions": reported}


async def test_get_machine_says_how_many_tool_versions_it_did_not_show(
    engine: AsyncEngine,
) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    alice = await _seed_member(maker, "alice@x.io")
    reported = {f"tool{n:02d}": f"{n}.0" for n in range(15)}  # past what a companion reports
    await _seed_machine(maker, project_id, alice, MINE, "alice-box", versions=reported)
    registry = _registry_of(maker, project_id, alice)
    text = _ok_text(await _invoke(registry, "get_machine", companion_id=MINE))
    shown = _json_rows(text)[1]["tool_versions"]
    assert list(shown) == [f"tool{n:02d}" for n in range(12)]
    assert "+3 more tool versions" in text.split("\n")


async def test_get_machine_never_returns_another_members_commands(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    alice = await _seed_member(maker, "alice@x.io")
    bob = await _seed_member(maker, "bob@x.io")
    await _seed_machine(maker, project_id, alice, MINE, "alice-box")
    await _seed_machine(
        maker,
        project_id,
        bob,
        THEIRS,
        "bob-box",
        commands=[
            _logged_command(1, command_redacted="rm -rf bobs-secret-project", cwd="/home/bob/x"),
            _logged_command(2, output_tail="bob-only-output"),
        ],
        versions={"python3": "Python 3.11.9"},
    )
    asked = await _invoke(
        _registry_of(maker, project_id, alice), "get_machine", companion_id=THEIRS
    )
    text = _ok_text(asked)
    head, versions, withheld = _json_rows(text)  # three rows: not a command among them
    assert (head["machine"], head["owner"]) == ("bob-box", "another member")
    assert versions == {"tool_versions": {"python3": "Python 3.11.9"}}
    assert withheld == {"recent_commands": "withheld: only the machine's owner sees them"}
    for private in ("bobs-secret-project", "/home/bob/x", "bob-only-output", "command_redacted"):
        assert private not in text
    # The rule keys on the member the tool is bound to, not on the machine asked for.
    bobs = _registry_of(maker, project_id, bob)
    theirs = _ok_text(await _invoke(bobs, "get_machine", companion_id=THEIRS))
    assert "bob-only-output" in theirs
    assert "withheld" not in theirs


async def test_get_machine_redacts_commands_and_tool_versions(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    alice = await _seed_member(maker, "alice@x.io")
    leaky = _logged_command(
        1, command_redacted="deploy --token=abc123def456", output_tail="password=hunter2"
    )
    await _seed_machine(
        maker,
        project_id,
        alice,
        MINE,
        "alice-box",
        commands=[leaky],
        versions={"pip": "pip 24.0 token=xyz789"},
    )
    registry = _registry_of(maker, project_id, alice)
    text = _ok_text(await _invoke(registry, "get_machine", companion_id=MINE))
    assert "--token=[REDACTED]" in text
    assert "password=[REDACTED]" in text
    assert "pip 24.0 token=[REDACTED]" in text
    for secret in ("abc123def456", "hunter2", "xyz789"):
        assert secret not in text


async def test_get_machine_that_is_not_here_is_the_same_not_found(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    mine, _ = await _new_project(maker)
    theirs, _ = await _new_project(maker)
    alice = await _seed_member(maker, "alice@x.io")
    bob = await _seed_member(maker, "bob@x.io")
    await _seed_machine(maker, theirs, bob, THEIRS, "bob-box")
    registry = _registry_of(maker, mine, alice)
    absent = _missing_message(await _invoke(registry, "get_machine", companion_id=MINE))
    elsewhere = _missing_message(await _invoke(registry, "get_machine", companion_id=THEIRS))
    assert absent == elsewhere == "Machine not found"


@pytest.mark.parametrize("companion_id", ["", "not-hex", MINE.upper(), MINE[:-1], MINE + "0"])
async def test_get_machine_refuses_an_id_that_is_not_a_companion_id(
    engine: AsyncEngine, companion_id: str
) -> None:
    registry = _registry_of(_maker(engine), uuid.uuid4(), uuid.uuid4())
    result = await _invoke(registry, "get_machine", companion_id=companion_id)
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS


# ------------------------------------------------------- get_environment_divergences


def _divergence_doc(*hostnames: str, diverging: bool = True) -> EnvironmentDivergencesDoc:
    causes = (
        [
            DivergenceGroup(
                cause="missing",
                items=[DivergenceItem(name="opencv-python"), DivergenceItem(name="pyserial")],
            ),
            DivergenceGroup(
                cause="version_drift",
                items=[DivergenceItem(name="numpy", expected="==1.26.4", actual="2.0.1")],
            ),
            DivergenceGroup(cause="extra", items=[DivergenceItem(name="ipdb", actual="0.13")]),
        ]
        if diverging
        else []
    )
    return EnvironmentDivergencesDoc(
        computed_at=_T0,
        spec_entry_id=None,
        machines=[
            MachineDivergences(machine_id=uuid.uuid4(), hostname=name, causes=causes)
            for name in hostnames
        ],
    )


async def _seed_divergences(
    maker: Maker, project_id: uuid.UUID, document: EnvironmentDivergencesDoc
) -> None:
    async with maker() as db:
        await put_config_entry(
            db,
            project_id,
            SolusSection.ENVIRONMENT,
            "divergences",
            document,
            text="Environment divergences",
            configured_entity_id=None,
            created_by=None,
            author="system",
        )
        await db.commit()


async def test_get_environment_divergences_reads_the_stored_table(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    document = _divergence_doc("bench-pc")
    document.machines.append(
        MachineDivergences(machine_id=uuid.uuid4(), hostname="build-box", causes=[])
    )
    await _seed_divergences(maker, project_id, document)
    registry = _registry_of(maker, project_id, uuid.uuid4())
    rows = _json_rows(_ok_text(await _invoke(registry, "get_environment_divergences")))
    assert rows[0]["computed_at"].startswith("2026-10-01T00:00:00")
    causes = {(row["machine"], row["cause"]): row["items"] for row in rows if "cause" in row}
    assert causes == {
        ("bench-pc", "missing"): "opencv-python; pyserial",
        ("bench-pc", "version_drift"): "numpy expected ==1.26.4 actual 2.0.1",
        ("bench-pc", "extra"): "ipdb actual 0.13",
    }
    assert [row["machine"] for row in rows if row.get("diverges") == "none"] == ["build-box"]


async def test_get_environment_divergences_says_how_many_items_it_did_not_show(
    engine: AsyncEngine,
) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    many = [DivergenceItem(name=f"pkg-{n:02d}") for n in range(25)]
    document = EnvironmentDivergencesDoc(
        computed_at=_T0,
        spec_entry_id=None,
        machines=[
            MachineDivergences(
                machine_id=uuid.uuid4(),
                hostname="bench-pc",
                causes=[DivergenceGroup(cause="missing", items=many)],
            )
        ],
    )
    await _seed_divergences(maker, project_id, document)
    registry = _registry_of(maker, project_id, uuid.uuid4())
    text = _ok_text(await _invoke(registry, "get_environment_divergences"))
    assert "pkg-09" in text
    assert "pkg-10" not in text
    assert "+15 more" in text


async def test_get_environment_divergences_says_so_and_writes_nothing_when_not_computed(
    engine: AsyncEngine,
) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    registry = _registry_of(maker, project_id, uuid.uuid4())
    text = _ok_text(await _invoke(registry, "get_environment_divergences"))
    assert text == "environment divergences not computed yet"
    async with maker() as db:
        stored = await db.scalar(select(func.count()).select_from(SolusEntry))
    assert stored == 0  # the route recomputes on first read; the tool only reads


async def test_get_environment_divergences_never_leaves_the_project(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    mine, _ = await _new_project(maker)
    theirs, _ = await _new_project(maker)
    await _seed_divergences(maker, theirs, _divergence_doc("their-pc"))
    registry = _registry_of(maker, mine, uuid.uuid4())
    text = _ok_text(await _invoke(registry, "get_environment_divergences"))
    assert text == "environment divergences not computed yet"


async def test_get_environment_divergences_is_cut_at_the_row_cap(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    await _seed_divergences(maker, project_id, _divergence_doc(*(f"pc-{n}" for n in range(8))))
    registry = _registry_of(maker, project_id, uuid.uuid4())
    lines = _ok_text(await _invoke(registry, "get_environment_divergences")).split("\n")
    assert len(lines) == MAX_ROWS + 1
    assert lines[-1] == TRUNCATED


# ----------------------------------------------------------------------- get_history


async def _seed_activity(
    maker: Maker,
    project_id: uuid.UUID,
    kind: str,
    *,
    ago: timedelta = timedelta(minutes=1),
    entities: tuple[uuid.UUID, ...] = (),
    **fields: Any,
) -> None:
    async with maker() as db:
        activity = await record_project_activity(
            db, project_id, kind, entity_ids=list(entities), **fields
        )
        assert activity is not None
        activity.created_at = utcnow() - ago
        await db.commit()


async def test_get_history_lists_the_projects_newest_events_first(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    part = uuid.uuid4()
    await _seed_activity(maker, project_id, "sync.completed", ago=timedelta(hours=3), domain="code")
    await _seed_activity(
        maker,
        project_id,
        "config.bumped",
        ago=timedelta(hours=1),
        entities=(part,),
        domain="runtime",
        why_ref="finding:abc",
    )
    registry = _registry_of(maker, project_id, uuid.uuid4())
    rows = _json_rows(_ok_text(await _invoke(registry, "get_history")))
    assert len(rows) == 2
    assert (rows[0]["type"], rows[0]["domain"]) == ("config.bumped", "runtime")
    assert rows[0]["entities"] == str(part)
    assert rows[0]["why"] == "finding:abc"
    assert (rows[1]["type"], rows[1]["domain"]) == ("sync.completed", "code")


async def test_get_history_names_three_entities_and_counts_the_rest(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    touched = [uuid.uuid4() for _ in range(5)]
    await _seed_activity(maker, project_id, "bulk.import", entities=tuple(touched))
    registry = _registry_of(maker, project_id, uuid.uuid4())
    (row,) = _json_rows(_ok_text(await _invoke(registry, "get_history")))
    assert row["entities"] == f"{touched[0]}; {touched[1]}; {touched[2]}; +2 more"


async def test_get_history_for_one_entity_names_only_its_events(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    servo, other = uuid.uuid4(), uuid.uuid4()
    await _seed_activity(maker, project_id, "limit.changed", entities=(servo,))
    await _seed_activity(maker, project_id, "part.renamed", entities=(other,))
    registry = _registry_of(maker, project_id, uuid.uuid4())
    text = _ok_text(await _invoke(registry, "get_history", entity_id=str(servo)))
    assert "limit.changed" in text
    assert "part.renamed" not in text


async def test_get_history_reaches_back_at_most_thirty_days(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    await _seed_activity(maker, project_id, "recent.event", ago=timedelta(days=2))
    await _seed_activity(maker, project_id, "ancient.event", ago=timedelta(days=45))
    registry = _registry_of(maker, project_id, uuid.uuid4())
    by_default = _ok_text(await _invoke(registry, "get_history"))
    assert "recent.event" in by_default
    assert "ancient.event" not in by_default
    assert "ancient.event" not in _ok_text(await _invoke(registry, "get_history", since_days=30))
    assert "recent.event" not in _ok_text(await _invoke(registry, "get_history", since_days=1))
    refused = await _invoke(registry, "get_history", since_days=31)
    assert refused.error is not None
    assert refused.error.code is ToolErrorCode.INVALID_ARGS
    clamped = await get_history_handler(
        {"since_days": 400, "limit": 500}, sessions=maker, project_id=project_id
    )
    assert len(clamped) == 1  # the handler clamps what the schema would have refused


async def test_get_history_results_are_capped_at_the_limit(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    for n in range(MAX_ROWS + 3):
        await _seed_activity(maker, project_id, f"event.{n:02d}", ago=timedelta(minutes=n + 1))
    registry = _registry_of(maker, project_id, uuid.uuid4())
    short = _ok_text(await _invoke(registry, "get_history", limit=3)).split("\n")
    assert len(_json_rows("\n".join(short))) == 3
    assert short[-1] == MORE  # 23 exist: the fourth row fetched says the cut is not the end
    *full, marker = _ok_text(await _invoke(registry, "get_history", limit=MAX_ROWS)).split("\n")
    assert len(full) == MAX_ROWS
    assert marker == TRUNCATED
    refused = await _invoke(registry, "get_history", limit=MAX_ROWS + 1)
    assert refused.error is not None
    assert refused.error.code is ToolErrorCode.INVALID_ARGS


async def test_get_history_marks_a_cut_only_when_the_limit_hid_something(
    engine: AsyncEngine,
) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    for n in range(3):
        await _seed_activity(maker, project_id, f"event.{n}", ago=timedelta(minutes=n + 1))
    registry = _registry_of(maker, project_id, uuid.uuid4())
    for limit in (3, 5):  # all three fit, with or without room to spare
        whole = _ok_text(await _invoke(registry, "get_history", limit=limit))
        assert len(_json_rows(whole)) == 3
        assert MORE not in whole
    cut = _ok_text(await _invoke(registry, "get_history", limit=2)).split("\n")
    assert [row["type"] for row in _json_rows("\n".join(cut))] == ["event.0", "event.1"]
    assert cut[-1] == MORE


async def test_get_history_never_leaves_the_project_or_shows_a_payload(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    mine, team = await _new_project(maker)
    theirs, _ = await _new_project(maker)
    await _seed_activity(
        maker, mine, "invite.sent", payload={"email": "carol@elsewhere.io", "role": "admin"}
    )
    await _seed_activity(maker, theirs, "their.event")
    async with maker() as db:
        record_activity(db, team_id=team, activity_type="team.created")
        await db.commit()
    registry = _registry_of(maker, mine, uuid.uuid4())
    text = _ok_text(await _invoke(registry, "get_history"))
    (row,) = _json_rows(text)
    assert row["type"] == "invite.sent"
    for hidden in ("their.event", "team.created", "carol@elsewhere.io", "admin"):
        assert hidden not in text


async def test_get_history_with_nothing_recorded_says_so(engine: AsyncEngine) -> None:
    maker = _maker(engine)
    project_id, _ = await _new_project(maker)
    registry = _registry_of(maker, project_id, uuid.uuid4())
    assert _ok_text(await _invoke(registry, "get_history")) == "no results"
