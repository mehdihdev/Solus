"""Bridge write previews (SOLUSDEV-251 / INTEGRATIONS I4): a companion write tool
gets a before→after diff by READING through the same bridge first. Pure fakes."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from solus_api.bridge.previews import (
    PREVIEWABLE_TOOLS,
    kicad_project_path,
    preview_builder,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


class _Reader:
    def __init__(self, answer: dict[str, Any] | None) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append((tool, dict(args)))
        return self.answer


def _netlist() -> dict[str, Any]:
    return {
        "success": True,
        "components": {
            "R1": {
                "lib_id": "Device:R",
                "value": "10k",
                "footprint": "R_0603",
                "properties": {"Tolerance": "1%"},
            },
            "C3": {"lib_id": "Device:C", "value": "100n"},
        },
    }


def test_only_the_kicad_write_is_previewable_today() -> None:
    assert set(PREVIEWABLE_TOOLS) == {
        "kicad.set_symbol_property",
        "code.create_environment",
        "code.install",
        "code.run",
        "code.test",
        "code.exec",
        "code.process_start",
        "code.profile_capture",
    }
    assert preview_builder("kicad.export_netlist", _Reader(None)) is None
    assert preview_builder("kicad.set_symbol_property", _Reader(None)) is not None


def test_kicad_project_path_derives_from_the_schematic() -> None:
    assert kicad_project_path("hw/main/main.kicad_sch") == "hw/main/main.kicad_pro"
    assert kicad_project_path("hw/main/main.KICAD_SCH") == "hw/main/main.kicad_pro"
    assert kicad_project_path("hw/main/main.txt") is None
    assert kicad_project_path("") is None


async def test_value_footprint_and_custom_property_rows() -> None:
    reader = _Reader(_netlist())
    build = preview_builder("kicad.set_symbol_property", reader)
    assert build is not None
    rows = await build(
        {
            "schematic_path": "hw/main.kicad_sch",
            "reference": "R1",
            "property": "Value",
            "value": "4k7",
        }
    )
    assert rows[0] == {"label": "R1 · Value", "before": "10k", "after": "4k7"}
    assert rows[1] == {"label": "schematic", "before": None, "after": "hw/main.kicad_sch"}
    assert reader.calls == [
        ("kicad.extract_project_netlist", {"project_path": "hw/main.kicad_pro"})
    ]

    rows = await build(
        {
            "schematic_path": "hw/main.kicad_sch",
            "reference": "R1",
            "property": "Footprint",
            "value": "R_0805",
        }
    )
    assert rows[0]["before"] == "R_0603"
    rows = await build(
        {
            "schematic_path": "hw/main.kicad_sch",
            "reference": "R1",
            "property": "Tolerance",
            "value": "5%",
        }
    )
    assert rows[0]["before"] == "1%"


async def test_unknown_component_or_failed_read_still_yields_a_row() -> None:
    """The gate must always have something honest to show: an unknown reference
    or a read that declined renders `before: None`, never a guessed value."""
    rows = await preview_builder("kicad.set_symbol_property", _Reader(_netlist()))(  # type: ignore[misc]
        {
            "schematic_path": "hw/main.kicad_sch",
            "reference": "U9",
            "property": "Value",
            "value": "x",
        }
    )
    assert rows[0] == {"label": "U9 · Value", "before": None, "after": "x"}
    rows = await preview_builder("kicad.set_symbol_property", _Reader(None))(  # type: ignore[misc]
        {
            "schematic_path": "hw/main.kicad_sch",
            "reference": "R1",
            "property": "Value",
            "value": "x",
        }
    )
    assert rows[0]["before"] is None


async def test_hostile_netlist_shapes_never_raise() -> None:
    for hostile in (
        {"components": "not a dict"},
        {"components": {"R1": "not a dict"}},
        {"components": {"R1": {"properties": ["not", "a", "dict"]}}},
        {"success": False, "error": "boom"},
        {},
    ):
        rows = await preview_builder("kicad.set_symbol_property", _Reader(hostile))(  # type: ignore[misc]
            {
                "schematic_path": "a.kicad_sch",
                "reference": "R1",
                "property": "Tolerance",
                "value": "x",
            }
        )
        assert rows[0]["before"] is None
    rows = await preview_builder("kicad.set_symbol_property", _Reader(_netlist()))(  # type: ignore[misc]
        {"schematic_path": 5, "reference": None, "property": "Value", "value": None}
    )
    assert rows[0]["after"] is None


async def test_before_values_are_capped_strings() -> None:
    long_value = "v" * 5000
    net = {"components": {"R1": {"value": long_value}}}
    rows = await preview_builder("kicad.set_symbol_property", _Reader(net))(  # type: ignore[misc]
        {"schematic_path": "a.kicad_sch", "reference": "R1", "property": "Value", "value": "x"}
    )
    assert isinstance(rows[0]["before"], str) and len(rows[0]["before"]) <= 500


# ---------------------------------------------------- registration + gate end to end


async def test_registered_kicad_write_previews_through_the_bridge(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """The registered write returns its complete native dry-run through the same session."""
    import asyncio
    import json
    from datetime import UTC, datetime

    from solus_api.agent.confirmations import _build_preview
    from solus_api.agent.runtime import build_sol_registry
    from solus_api.agent.tools.shapes import ToolDescriptor, ToolResult
    from solus_api.bridge.allowlist import BridgeToolSpec
    from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
    from solus_api.bridge.service import ingest_result
    from sqlalchemy.ext.asyncio import async_sessionmaker

    user_id, team_id, project_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def spec(name: str) -> BridgeToolSpec:
        server, _, tool = name.partition(".")
        return BridgeToolSpec(
            server=server,
            remote_name=tool,
            descriptor=ToolDescriptor(
                name=name, description="d", params={"type": "object"}, returns={"type": "object"}
            ),
        )

    sent: list[dict[str, Any]] = []
    holder: dict[str, BridgeSession] = {}

    async def _send(frame: str) -> None:
        data = json.loads(frame)["data"]
        sent.append(data)
        answer = {
            "ok": True,
            "dry_run": True,
            "preview": [{"label": "R1 · Value", "before": "10k", "after": "4k7"}],
        }
        asyncio.get_running_loop().call_soon(
            ingest_result, holder["s"], ToolResult.success(data["call_id"], answer)
        )

    async def _close(code: int) -> None:
        return None

    sessions = InMemoryBridgeSessionRegistry()
    session = BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=user_id,
        team_id=team_id,
        project_id=project_id,
        companion_instance_id="a" * 32,
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=(spec("kicad.set_symbol_property"), spec("kicad.extract_project_netlist")),
        send=_send,
        close=_close,
        max_inflight=8,
        may_write=True,
    )
    holder["s"] = session
    sessions.bind(session)
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        project_id,
        bridge=sessions,
        user_id=user_id,
        team_id=team_id,
    )
    tools = {t.descriptor.name: t for t in registry.tools()}
    assert hasattr(tools["kicad.set_symbol_property"], "preview")
    assert not hasattr(tools["kicad.extract_project_netlist"], "preview")

    rows = await _build_preview(
        tools["kicad.set_symbol_property"],
        {
            "schematic_path": "hw/main.kicad_sch",
            "reference": "R1",
            "property": "Value",
            "value": "4k7",
            "expected_fingerprint": "0123456789abcdef" * 4,
        },
    )
    assert rows[0] == {"label": "R1 · Value", "before": "10k", "after": "4k7"}
    assert len(sent) == 1
    assert sent[0]["tool"] == "kicad.set_symbol_property"
    assert sent[0]["args"] == {
        "schematic_path": "hw/main.kicad_sch",
        "reference": "R1",
        "property": "Value",
        "value": "4k7",
        "expected_fingerprint": "0123456789abcdef" * 4,
        "dry_run": True,
    }


def test_project_path_refuses_escapes_before_any_dispatch() -> None:
    for bad in ("../x.kicad_sch", "a/../../x.kicad_sch", "/abs/x.kicad_sch", "C:\\x.kicad_sch"):
        assert kicad_project_path(bad) is None, bad


async def test_bridge_reader_declines_without_session_tool_or_preflight() -> None:
    """Security review M1/M2/10: the reader uses only the caller's own session,
    refuses a tool the companion does not offer, and honours the BYO preflight."""
    from datetime import UTC, datetime

    from solus_api.agent.runtime import _bridge_reader
    from solus_api.agent.tools.shapes import ToolDescriptor
    from solus_api.agent.tools.tool import ToolException
    from solus_api.bridge.allowlist import BridgeToolSpec
    from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry

    user, team, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sent: list[str] = []

    async def _send(frame: str) -> None:
        sent.append(frame)

    async def _close(code: int) -> None:
        return None

    spec = BridgeToolSpec(
        server="kicad",
        remote_name="extract_project_netlist",
        descriptor=ToolDescriptor(
            name="kicad.extract_project_netlist",
            description="d",
            params={"type": "object"},
            returns={"type": "object"},
        ),
    )
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(
        BridgeSession(
            session_id="s1",
            user_id=user,
            team_id=team,
            project_id=project,
            companion_instance_id="a" * 32,
            companion_version="0.1.0",
            protocol_version=1,
            connected_at=datetime.now(UTC),
            token_exp=datetime.now(UTC),
            inventory=(spec,),
            send=_send,
            close=_close,
            max_inflight=8,
        )
    )
    other_user = _bridge_reader(sessions, uuid.uuid4(), team, project, 1000)
    assert await other_user("kicad.extract_project_netlist", {}) is None
    mine = _bridge_reader(sessions, user, team, project, 1000)
    assert await mine("kicad.set_symbol_property", {}) is None  # not offered
    assert sent == []

    async def _refuse() -> None:
        raise ToolException("no license", retryable=False)

    gated = _bridge_reader(sessions, user, team, project, 1000, _refuse)
    assert await gated("kicad.extract_project_netlist", {}) is None
    assert sent == []  # preflight refused before any dispatch


# ------------------------------------------------ SOLUSDEV-250: code.* previews


async def test_code_previews_show_the_servers_own_argv() -> None:
    reader = _Reader(
        {
            "ok": True,
            "argv": [".venv/bin/python", "-m", "pip", "install", "--", "six==1.17.0"],
            "cwd": ".",
            "sandbox": {"kind": "sandbox-exec", "writable": []},
        }
    )
    build = preview_builder("code.install", reader)
    assert build is not None
    rows = await build({"packages": ["six==1.17.0"], "environment": ".venv"})
    assert rows[0] == {
        "label": "command",
        "before": None,
        "after": ".venv/bin/python -m pip install -- six==1.17.0",
    }
    assert rows[1] == {"label": "cwd", "before": None, "after": "."}
    assert reader.calls == [
        (
            "code.plan",
            {"action": "install", "args": {"packages": ["six==1.17.0"], "environment": ".venv"}},
        )
    ]


async def test_code_preview_refuses_unavailable_or_invalid_plans() -> None:
    from solus_api.agent.tools.tool import ToolException

    for plan in (
        {"ok": False, "argv": [], "cwd": ".", "reason": "package name may not start with -"},
        None,
        {"ok": True, "argv": "rm -rf /", "cwd": 5},
    ):
        builder = preview_builder("code.run", _Reader(plan))
        assert builder is not None
        with pytest.raises(ToolException):
            await builder({"script": "-x.py"})
