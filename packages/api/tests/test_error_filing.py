"""Automatic Error logging (SOLUSDEV-252 S5): when a `files_errors` tool fails, the
runner files ONE bounded, redacted `.solus` errors entry as `sol`. Never raises."""

from __future__ import annotations

import uuid
from typing import Any

from solus_api.agent.errors_filing import MAX_ENTRY_CHARS, file_tool_error
from solus_api.agent.tools import ToolCall, ToolDescriptor, ToolError, ToolErrorCode, ToolResult
from solus_api.models import Project, SolusEntry, SolusEntryKind, SolusSection, Team, TeamKind, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

FILING = ToolDescriptor(
    name="companion.run_command",
    description="Runs a command on the person's machine.",
    params={"type": "object"},
    returns={"type": "object"},
    requires_confirmation=True,
    consent_summary="Run a command",
    files_errors=True,
)
PLAIN = FILING.model_copy(update={"name": "get_entity", "files_errors": False})
ENTITY = uuid.uuid4()
CALL = ToolCall(
    tool=FILING.name,
    call_id="c1",
    args={"command": ["pio", "run"], "entity_id": str(ENTITY), "token": "hunter2", "api_key": "k"},
)
FAILED = ToolResult.failure(
    "c1", ToolError(code=ToolErrorCode.TOOL_ERROR, message="exit 1: " + "x" * 5000)
)


async def _seed_project(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(supabase_user_id=uuid.uuid4().hex, email="e@x.io", data_collection_consent=True)
    team = Team(name="T", kind=TeamKind.COLLABORATIVE)
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.commit()
    return project.id, user.id


async def _errors(db: AsyncSession, project_id: uuid.UUID) -> list[SolusEntry]:
    rows = await db.scalars(
        select(SolusEntry).where(
            SolusEntry.project_id == project_id, SolusEntry.section == SolusSection.ERRORS
        )
    )
    return list(rows)


async def test_a_failing_files_errors_tool_files_one_redacted_bounded_entry(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=FAILED,
        descriptor=FILING,
        executed=True,
    )
    [entry] = await _errors(db, project_id)
    assert entry.author == "sol" and entry.kind is SolusEntryKind.SOL
    assert entry.created_by == user_id
    text = entry.text or ""
    assert len(text) <= MAX_ENTRY_CHARS
    assert FILING.name in text and "pio" in text and str(ENTITY) in text
    assert "exit 1" in text and "tool_error" in text
    assert "hunter2" not in text and '"api_key": "k"' not in text  # redacted secrets
    assert "T" in text and ":" in text  # an ISO timestamp line
    assert "When:" in text


async def test_success_and_unflagged_tools_file_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ok = ToolResult.success("c1", {"stdout": "fine"})
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=ok,
        descriptor=FILING,
        executed=True,
    )
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=FAILED,
        descriptor=PLAIN,
        executed=True,
    )
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=FAILED,
        descriptor=None,
        executed=True,
    )
    assert await _errors(db, project_id) == []


async def test_a_command_that_exits_nonzero_is_a_failure(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """The command RAN, so the bridge call is `ok=True` — and the thing the
    person wants logged is precisely this: `ModuleNotFoundError`, exit 1. Keying
    filing on the transport's `ok` alone filed nothing for the only failure
    Error logging exists to catch (SOLUSDEV-252, found live)."""
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ran_and_failed = ToolResult.success(
        "c1",
        {
            "exit_code": 1,
            "timed_out": False,
            "stdout": "",
            "stderr": "ModuleNotFoundError: No module named 'solus_nonexistent_module'\n",
        },
    )
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=ran_and_failed,
        descriptor=FILING,
        executed=True,
    )
    (entry,) = await _errors(db, project_id)
    assert entry.text is not None
    assert "exit 1" in entry.text and "solus_nonexistent_module" in entry.text
    assert entry.author == "sol"


async def test_a_failing_commands_output_is_redacted(db: AsyncSession, engine: AsyncEngine) -> None:
    """The filed row is durable, team-visible and replayed to the model. A build
    script that echoes its environment before dying must not put the key there —
    the error CHANNEL is redacted at the bridge, the value channel is not."""
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    leaky = ToolResult.success(
        "c1",
        {
            "exit_code": 2,
            "timed_out": False,
            "stdout": "",
            "stderr": (
                "+ export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
                "+ curl -H 'authorization: Bearer ghp_16C7e42F292c6912E7710c838347Ae178B4a'\n"
                "make: *** [build] Error 2\n"
            ),
        },
    )
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=leaky,
        descriptor=FILING,
        executed=True,
    )
    (entry,) = await _errors(db, project_id)
    assert entry.text is not None
    assert (
        "wJalrXUtnFEMI" not in entry.text
        and "ghp_16C7e42F292c6912E7710c838347Ae178B4a" not in entry.text
    )
    assert "exit 2" in entry.text  # still useful


async def test_a_timed_out_command_is_a_failure(db: AsyncSession, engine: AsyncEngine) -> None:
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    timed_out = ToolResult.success(
        "c1", {"exit_code": None, "timed_out": True, "stdout": "", "stderr": ""}
    )
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=timed_out,
        descriptor=FILING,
        executed=True,
    )
    (entry,) = await _errors(db, project_id)
    assert entry.text is not None and "timed out" in entry.text


async def test_a_failed_step_of_a_multi_step_build_is_a_failure(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """`create_environment` runs an ordered build and stops at the first failure,
    reporting the steps under `results` with NO top-level exit code. Reading only
    the flat shape filed nothing for a venv that could not be created."""
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    build = ToolResult.success(
        "c1",
        {
            "kind": "venv",
            "name": "sim",
            "dry_run": False,
            "steps": [["/usr/bin/python3", "-m", "venv", "/w/sim"]],
            "results": [
                {
                    "argv": ["/usr/bin/python3", "-m", "venv", "/w/sim"],
                    "exit_code": 1,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "Error: [Errno 13] Permission denied: '/w/sim'\n",
                }
            ],
        },
    )
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=build,
        descriptor=FILING,
        executed=True,
    )
    (entry,) = await _errors(db, project_id)
    assert entry.text is not None
    assert "step 1 exit 1" in entry.text and "Permission denied" in entry.text


async def test_a_true_exit_code_is_not_a_failure(db: AsyncSession, engine: AsyncEngine) -> None:
    """`True` is an `int` in Python and `True != 0`; a boolean in that field is a
    shape violation, not a failed run."""
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=ToolResult.success("c1", {"exit_code": True, "timed_out": False}),
        descriptor=FILING,
        executed=True,
    )
    assert await _errors(db, project_id) == []


async def test_a_clean_exit_and_a_planning_dry_run_file_nothing(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """exit 0 is a success; a dry run never ran at all."""
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    for value in (
        {"exit_code": 0, "timed_out": False, "stdout": "ok", "stderr": ""},
        {"dry_run": True, "argv": ["pio", "run"], "cwd": "/w"},
    ):
        await file_tool_error(
            maker,
            project_id=project_id,
            user_id=user_id,
            call=CALL,
            result=ToolResult.success("c1", value),
            descriptor=FILING,
            executed=True,
        )
    assert await _errors(db, project_id) == []


async def test_filing_never_raises(engine: AsyncEngine) -> None:
    def broken() -> Any:
        raise RuntimeError("db gone")

    # An unknown project (lock_project 404s) and a sessionmaker that explodes: both swallowed.
    await file_tool_error(
        async_sessionmaker(engine, expire_on_commit=False),
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        call=CALL,
        result=FAILED,
        descriptor=FILING,
        executed=True,
    )
    await file_tool_error(
        broken,
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        call=CALL,
        result=FAILED,
        descriptor=FILING,
        executed=True,
    )


# ---------------------------------------------------------------------------
# The gate seam (review HIGH). A confirmation-gated call comes back from
# `dispatch` PARKED — not executed — carrying an UNAUTHORIZED refusal whose own
# text says "This is not a failure". Filing that would write a durable,
# team-visible Errors row the moment SOL *proposes* an action; and the ONE place
# such a tool actually runs (`decide_confirmation`) filed nothing at all.

GATED_UNAUTHORIZED = ToolResult.failure(
    "c1",
    ToolError(
        code=ToolErrorCode.UNAUTHORIZED,
        message="companion.run_command is now waiting for the person to approve it — "
        "This is not a failure",
    ),
)
UNGATED = FILING.model_copy(update={"requires_confirmation": False, "consent_summary": None})


async def test_a_parked_gated_call_files_nothing(db: AsyncSession, engine: AsyncEngine) -> None:
    """The proposal is not an execution. Before the fix this filed one entry per
    model round, with the model's own argv on the `Command:` line."""
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=GATED_UNAUTHORIZED,
        descriptor=FILING,
        executed=False,
    )
    assert await _errors(db, project_id) == []


async def test_an_ungated_files_errors_tool_that_fails_still_files(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=FAILED,
        descriptor=UNGATED,
        executed=True,
    )
    assert len(await _errors(db, project_id)) == 1


async def test_a_tool_that_returns_unauthorized_after_running_still_files(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """Why `executed` is a caller fact and not a sniff of the error code: a tool
    that really ran and really got a 403 back must still file."""
    project_id, user_id = await _seed_project(db)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    denied = ToolResult.failure(
        "c1", ToolError(code=ToolErrorCode.UNAUTHORIZED, message="the board refused the flash")
    )
    await file_tool_error(
        maker,
        project_id=project_id,
        user_id=user_id,
        call=CALL,
        result=denied,
        descriptor=UNGATED,
        executed=True,
    )
    [entry] = await _errors(db, project_id)
    assert "the board refused the flash" in (entry.text or "")
