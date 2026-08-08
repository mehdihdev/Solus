"""SOLUSDEV-102 ALT-6 — export_netlist degrades honestly when Altium is
unreachable (the in-house default: no Altium on this machine), and NEVER
raises: every failure path returns the stable `{"degraded": true, "reason"}`
envelope instead of crashing the MCP server.

Also pins the ALT-6 registration outcome: the Solus-authored tool is
registered; upstream's own `proj_export_netlist` writer stays trimmed.
"""

from pathlib import Path
from typing import Any

import pytest

# The bootstrap module must run before any overlay/upstream import — keep the
# support import first (it installs sys.path + the lockfile-dep stubs).
from .test_overlay_support import (  # isort: skip
    FakeMCP,
    call_tool,
    register_overlay,
)
from .altium_paths import overlay_module
from .test_overlay_export_netlist import ScriptedBridge, _payload, export_tool_setup

_netlist_export = overlay_module("netlist_export")

DEGRADED_UNREACHABLE = {
    "degraded": True,
    "reason": _netlist_export.REASON_ALTIUM_UNREACHABLE,
}


class RaisingBridge:
    """A bridge whose send always raises *error* — records nothing else."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    async def send_command_async(
        self, command: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> Any:
        self.calls += 1
        raise self._error


# --- Altium unreachable: the honest in-house default ------------------------------


async def test_default_environment_degrades_with_altium_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No monkeypatched seam: the REAL upstream get_bridge path runs, finds
    no Altium (this repo's test env has no Altium and a stub psutil), and the
    tool returns the degraded envelope — exactly, nothing more."""
    from eda_agent.bridge import reset_bridge

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    monkeypatch.setenv("EDA_AGENT_WORKSPACE", str(workspace / ".eda-agent-ipc"))
    fake = FakeMCP()
    register_overlay(fake)
    try:
        result = await call_tool(
            fake.tools["export_netlist"], project_path=str(workspace / "board.PrjPcb")
        )
    finally:
        reset_bridge()

    assert result == DEGRADED_UNREACHABLE


async def test_altium_not_running_error_degrades(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from eda_agent.bridge.exceptions import AltiumNotRunningError

    wrapper, workspace = export_tool_setup(
        monkeypatch, tmp_path, RaisingBridge(AltiumNotRunningError())
    )

    result = await call_tool(wrapper, project_path=str(workspace / "board.PrjPcb"))

    assert result == DEGRADED_UNREACHABLE


async def test_failure_on_the_second_read_also_degrades(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """get_nets succeeds, get_bom times out mid-sequence — same stable
    envelope, no partial output."""

    class MidSequenceBridge:
        async def send_command_async(
            self,
            command: str,
            params: dict[str, Any] | None = None,
            timeout: float | None = None,
        ) -> Any:
            if command == "project.get_nets":
                return {"pins": [], "count": 0}
            raise TimeoutError("altium stopped answering")

    wrapper, workspace = export_tool_setup(monkeypatch, tmp_path, MidSequenceBridge())

    result = await call_tool(wrapper, project_path=str(workspace / "board.PrjPcb"))

    assert result == DEGRADED_UNREACHABLE


# --- malformed bridge data ---------------------------------------------------------


@pytest.mark.parametrize(
    "get_nets, get_bom",
    [
        ("not a dict", {"components": []}),
        ({"pins": []}, "not a dict"),
        ({"pins": "not a list"}, {"components": []}),
        ({"pins": []}, {"components": {"not": "a list"}}),
    ],
)
async def test_malformed_bridge_payloads_degrade_with_a_stable_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, get_nets: Any, get_bom: Any
) -> None:
    bridge = ScriptedBridge(get_nets=get_nets, get_bom=get_bom)
    wrapper, workspace = export_tool_setup(monkeypatch, tmp_path, bridge)

    result = await call_tool(wrapper, project_path=str(workspace / "board.PrjPcb"))

    assert result == {
        "degraded": True,
        "reason": _netlist_export.REASON_DATA_MALFORMED,
    }


# --- artifact write failure --------------------------------------------------------


async def test_artifact_write_failure_degrades(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _payload("sample_netlist_payload.json")
    monkeypatch.setattr(_netlist_export, "INLINE_MAX_BYTES", 0)

    def refuse_destination(filename: str) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(_netlist_export, "_artifact_destination", refuse_destination)
    bridge = ScriptedBridge(get_nets=payload["get_nets"], get_bom=payload["get_bom"])
    wrapper, workspace = export_tool_setup(monkeypatch, tmp_path, bridge)

    result = await call_tool(wrapper, project_path=str(workspace / "board.PrjPcb"))

    assert result == {
        "degraded": True,
        "reason": _netlist_export.REASON_ARTIFACT_WRITE_FAILED,
    }


# --- the never-raises guarantee ----------------------------------------------------


async def test_an_unexpected_internal_error_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _payload("sample_netlist_payload.json")

    def explode(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(_netlist_export, "emit_protel_netlist", explode)
    bridge = ScriptedBridge(get_nets=payload["get_nets"], get_bom=payload["get_bom"])
    wrapper, workspace = export_tool_setup(monkeypatch, tmp_path, bridge)

    result = await call_tool(wrapper, project_path=str(workspace / "board.PrjPcb"))

    assert result == {
        "degraded": True,
        "reason": _netlist_export.REASON_EXPORT_FAILED,
    }


# --- registration outcome ----------------------------------------------------------


def test_registration_now_includes_export_netlist() -> None:
    fake = FakeMCP()
    registrar = register_overlay(fake)
    assert "export_netlist" in fake.tools
    assert "export_netlist" in registrar.registered


def test_upstreams_proj_export_netlist_stays_trimmed() -> None:
    """Solus ships its OWN exporter; upstream's writer (arbitrary
    output_path, PADS/tabular formats) remains blocked."""
    fake = FakeMCP()
    registrar = register_overlay(fake)
    assert "proj_export_netlist" not in fake.tools
    assert "proj_export_netlist" in registrar.blocked
