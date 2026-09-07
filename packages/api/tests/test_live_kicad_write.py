"""SOLUSDEV-251 / I4 — KiCad READ → OPERATION → WRITE → read-back round-trip against the
REAL vendored fork through its launcher (`integrations/mcp/kicad/bin/launch`, materialised
venv). `-m live`: needs the fork venv (`make mcp-forks`); skipped otherwise. No cloud, no
companion — the same tools the bridge relays, exercised on a scratch copy of the sample."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.live

REPO = Path(__file__).resolve().parents[3]
FORK = REPO / "integrations" / "mcp" / "kicad"
FIXTURE = FORK / "tests" / "fixtures" / "solus_sample"
LAUNCH = FORK / "bin" / "launch"
VENV_PY = FORK / ".venv" / "bin" / "python3"

skip_without_fork = pytest.mark.skipif(
    not VENV_PY.exists(), reason="kicad fork venv not materialised (make mcp-forks)"
)


async def _call(workspace: Path, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=str(LAUNCH),
        args=[],
        env={
            "SOLUS_MCP_WORKSPACE": str(workspace),
            "HOME": os.environ.get("HOME", ""),
            "PATH": "/usr/bin:/bin",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            value = result.structuredContent
            assert isinstance(value, dict), result
            return value


@skip_without_fork
async def test_kicad_read_operate_write_read_back(tmp_path: Path) -> None:
    project = tmp_path / "hw"
    shutil.copytree(FIXTURE, project)
    sch = "hw/solus_sample.kicad_sch"
    pro = "hw/solus_sample.kicad_pro"

    # READ — what is here.
    netlist = await _call(tmp_path, "extract_project_netlist", {"project_path": pro})
    assert netlist["success"] is True
    before = netlist["components"]["R1"]["value"]
    assert before and before != "4k7"

    # OPERATION — analyse the schematic's connections (a real computation).
    analysis = await _call(tmp_path, "analyze_schematic_connections", {"schematic_path": sch})
    assert analysis.get("success", True) is not False
    assert analysis.get("component_count", netlist["component_count"]) >= 1

    # WRITE — the confirmation-gated tool (the gate is cloud-side; here we are the approver).
    written = await _call(
        tmp_path,
        "set_symbol_property",
        {"schematic_path": sch, "reference": "R1", "property": "Value", "value": "4k7"},
    )
    assert written.get("changed") is True, written

    # READ BACK — the tool's own read confirms the value landed.
    after = await _call(tmp_path, "extract_project_netlist", {"project_path": pro})
    assert after["components"]["R1"]["value"] == "4k7"
    # And the file is otherwise untouched: one property changed, nothing else.
    original = (FIXTURE / "solus_sample.kicad_sch").read_text()
    edited = (project / "solus_sample.kicad_sch").read_text()
    assert original.count("\n") == edited.count("\n")
    assert edited.count("4k7") == 1
    assert edited.replace('(property "Value" "4k7"', f'(property "Value" "{before}"', 1) == original
