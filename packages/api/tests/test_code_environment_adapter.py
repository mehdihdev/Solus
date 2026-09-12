"""I3 observations, not a second probe or model-supplied machine facts."""

from datetime import UTC, datetime
from typing import Any

import pytest
from solus_api.agent.tools.tool import ToolException
from solus_api.services.code_env import CodeEnvironment
from solus_api.services.code_environment_adapter import observed_environments


def probe() -> dict[str, Any]:
    return {
        "python": {"path": "/usr/bin/python3", "version": "3.12.3"},
        "interpreters": [{"path": "/usr/bin/python3", "version": "3.12.3"}],
        "venv": {
            "path": ".venv",
            "python_version": "3.12.3",
            "packages": [{"name": "numpy", "version": "2.1.0"}],
            "truncated": False,
        },
        "conda": {"path": "/opt/conda/bin/conda", "envs": ["robot"]},
        "uv": None,
    }


def test_adapter_records_only_observed_facts_and_capture_time() -> None:
    now = datetime(2026, 9, 10, tzinfo=UTC)
    answer = observed_environments(probe(), now=now)
    rows = [CodeEnvironment.model_validate(row) for row in answer["environments"]]
    venv = next(row for row in rows if row.type == "venv")
    assert venv.path == venv.name == ".venv"
    assert venv.interpreter is None and venv.detected_on is None
    assert venv.version == "3.12.3"
    assert venv.captured_at == now
    assert venv.provenance == "detected"
    assert [pin.name for pin in venv.packages] == ["numpy"]
    assert not any(row.type == "conda" for row in rows)
    assert answer["unavailable"]  # I3 does not report conda packages/interpreters.


@pytest.mark.parametrize(
    "bad", [None, {}, {"venv": []}, {"venv": {"path": ".venv", "packages": "invented"}}]
)
def test_adapter_refuses_missing_or_malformed_probe(bad: Any) -> None:
    with pytest.raises(ToolException):
        observed_environments(bad)


def test_truncated_packages_are_not_filed_as_a_complete_inventory() -> None:
    document = probe()
    document["venv"]["truncated"] = True
    answer = observed_environments(document)
    assert not any(row["type"] == "venv" for row in answer["environments"])
    assert answer["unavailable"]


@pytest.mark.parametrize("unavailable", ["missing", "truncated", "malformed"])
async def test_install_records_observed_facts_and_failed_reprobe_preserves_them(
    client: Any, alice_headers: dict[str, str], engine: Any, unavailable: str
) -> None:
    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_api.agent.tools.tool import InProcessTool
    from solus_api.services.code_env import list_code_environments
    from solus_api.services.code_environment_adapter import with_environment_recording
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from test_code_env import _project

    project, user = await _project(client, alice_headers)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    calls: list[dict[str, Any]] = []
    observed = probe()
    observed["venv"]["path"] = "sim"
    probed: list[str | None] = []

    async def execute(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return {"exit_code": 0, "stdout_tail": "installed"}

    async def fetch(environment: str | None = None) -> dict[str, Any]:
        probed.append(environment)
        return observed_environments(observed)

    descriptor = ToolDescriptor(
        name="code.install",
        description="fixture",
        params={"type": "object"},
        returns={"type": "object"},
        requires_confirmation=True,
        consent_summary="Install fixture",
        files_errors=True,
    )

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"label": "command", "before": None, "after": "fixture-install"}]

    tool = with_environment_recording(
        InProcessTool(descriptor, execute, preview=preview), fetch, maker, project, user
    )
    assert isinstance(tool, InProcessTool)
    await tool.preview({"packages": ["numpy"], "environment": "sim"})
    await tool.invoke({"packages": ["numpy"], "environment": "sim"})
    observed["venv"]["packages"][0]["version"] = "2.2.0"
    assert isinstance(tool, InProcessTool)
    await tool.preview({"packages": ["numpy"], "environment": "sim"})
    await tool.invoke({"packages": ["numpy"], "environment": "sim"})
    async with maker() as session:
        rows = await list_code_environments(session, project)
    assert len(rows) == 1
    assert rows[0].provenance == "sol" and rows[0].packages[0].version == "2.2.0"
    assert len(calls) == 2
    assert probed == ["sim", "sim"]
    recorded = rows[0].model_dump(mode="json")

    if unavailable == "missing":
        observed["venv"] = None
    elif unavailable == "truncated":
        observed["venv"]["packages"] = []
        observed["venv"]["truncated"] = True
    else:
        observed["venv"]["packages"] = None
    await tool.preview({"packages": ["numpy"], "environment": "sim"})
    result = await tool.invoke({"packages": ["numpy"], "environment": "sim"})
    assert result["exit_code"] == 0
    assert result["environment_recording"].startswith("unavailable:")
    assert len(calls) == 3
    assert probed == ["sim", "sim", "sim"]
    async with maker() as session:
        remaining = await list_code_environments(session, project)
    assert [row.model_dump(mode="json") for row in remaining] == [recorded]


@pytest.mark.parametrize(
    "plan", [None, {"ok": False}, {"ok": True, "argv": ["x" * 26000], "cwd": "."}]
)
async def test_execution_refuses_unrenderable_plan_even_after_preview_fallback(plan: Any) -> None:
    import uuid

    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_api.agent.tools.tool import InProcessTool
    from solus_api.bridge.previews import code_plan_rows
    from solus_api.services.code_environment_adapter import with_environment_recording
    from sqlalchemy.ext.asyncio import async_sessionmaker

    calls: list[dict[str, Any]] = []

    async def execute(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return {"exit_code": 0}

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        return code_plan_rows(plan)

    descriptor = ToolDescriptor(
        name="code.run",
        description="fixture",
        params={"type": "object"},
        returns={"type": "object"},
        requires_confirmation=True,
        consent_summary="Run fixture",
    )
    tool = with_environment_recording(
        InProcessTool(descriptor, execute, preview=preview),
        None,
        async_sessionmaker(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    with pytest.raises(ToolException):
        await tool.invoke({})
    assert calls == []


async def test_changed_plan_after_final_preview_never_executes() -> None:
    import uuid

    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_api.agent.tools.tool import InProcessTool
    from solus_api.services.code_environment_adapter import with_environment_recording
    from sqlalchemy.ext.asyncio import async_sessionmaker

    calls: list[dict[str, Any]] = []
    command = "approved-command"

    async def execute(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return {"exit_code": 0}

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"label": "command", "before": None, "after": command}]

    descriptor = ToolDescriptor(
        name="code.run",
        description="fixture",
        params={"type": "object"},
        returns={"type": "object"},
        requires_confirmation=True,
        consent_summary="Run fixture",
    )
    tool = with_environment_recording(
        InProcessTool(descriptor, execute, preview=preview),
        None,
        async_sessionmaker(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    assert isinstance(tool, InProcessTool)
    await tool.preview({"script": "fixture.py"})
    command = "changed-command"
    with pytest.raises(ToolException):
        await tool.invoke({"script": "fixture.py"})
    assert calls == []


@pytest.mark.parametrize(
    "outcome",
    [
        {"exit_code": 1},
        {"exit_code": -9},
        {"exit_code": False},
        {"exit_code": 0.0},
        {"exit_code": "0"},
        {"exit_code": None},
        {},
    ],
)
async def test_unsuccessful_or_noninteger_exit_preserves_saved_code_record(
    client: Any, alice_headers: dict[str, str], engine: Any, outcome: dict[str, Any]
) -> None:
    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_api.agent.tools.tool import InProcessTool
    from solus_api.services.code_env import list_code_environments, upsert_code_environment
    from solus_api.services.code_environment_adapter import with_environment_recording
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from test_code_env import _project

    project, user = await _project(client, alice_headers)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    recorded = CodeEnvironment.model_validate(observed_environments(probe())["environments"][0])
    async with maker() as session:
        await upsert_code_environment(session, project, recorded, created_by=user, author="sol")
        await session.commit()
        before = [
            row.model_dump(mode="json") for row in await list_code_environments(session, project)
        ]
    executions: list[dict[str, Any]] = []
    observations: list[str | None] = []

    async def execute(args: dict[str, Any]) -> dict[str, Any]:
        executions.append(args)
        return outcome

    async def fetch(environment: str | None = None) -> dict[str, Any]:
        observations.append(environment)
        changed = probe()
        changed["venv"]["packages"] = []
        return observed_environments(changed)

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"label": "command", "before": None, "after": "fixture-install"}]

    descriptor = ToolDescriptor(
        name="code.install",
        description="fixture",
        params={"type": "object"},
        returns={"type": "object"},
        requires_confirmation=True,
        consent_summary="Install fixture",
    )
    tool = with_environment_recording(
        InProcessTool(descriptor, execute, preview=preview), fetch, maker, project, user
    )
    assert isinstance(tool, InProcessTool)
    args = {"packages": ["numpy"], "environment": ".venv"}
    await tool.preview(args)
    result = await tool.invoke(args)
    assert result == outcome and "environment_recording" not in result
    assert executions == [args] and observations == []
    async with maker() as session:
        after = [
            row.model_dump(mode="json") for row in await list_code_environments(session, project)
        ]
    assert after == before


async def test_missing_original_preview_refuses_before_underlying_invocation() -> None:
    import uuid

    from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
    from solus_api.agent.tools.tool import InProcessTool
    from solus_api.services.code_environment_adapter import with_environment_recording
    from sqlalchemy.ext.asyncio import async_sessionmaker

    calls: list[dict[str, Any]] = []

    async def execute(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return {"exit_code": 0}

    descriptor = ToolDescriptor(
        name="code.run",
        description="fixture",
        params={"type": "object"},
        returns={"type": "object"},
        requires_confirmation=True,
        consent_summary="Run fixture",
    )
    tool = with_environment_recording(
        InProcessTool(descriptor, execute), None, async_sessionmaker(), uuid.uuid4(), uuid.uuid4()
    )
    assert isinstance(tool, InProcessTool)
    args = {"script": "fixture.py"}
    with pytest.raises(ToolException) as preview_failure:
        await tool.preview(args)
    assert preview_failure.value.code is ToolErrorCode.UNAVAILABLE
    with pytest.raises(ToolException) as invoke_failure:
        await tool.invoke(args)
    assert invoke_failure.value.code is ToolErrorCode.UNAUTHORIZED
    assert calls == []
