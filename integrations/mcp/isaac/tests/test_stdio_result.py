"""Real MCP SDK stdio transport and companion result mapping; never starts Isaac."""

import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_companion.dispatch import map_result


class _RawTool:
    """A bridge capability as the registry sees it: a descriptor, never invoked here."""

    def __init__(self, descriptor: ToolDescriptor) -> None:
        self.descriptor = descriptor

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("the raw capability is never invoked by this test")


async def test_actual_advertisement_survives_bridge_gate_and_exposes_all_cloud_wrappers(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    from solus_api.agent.tools.isaac_tools import build_isaac_tools
    from solus_api.bridge.allowlist import load_allowlist, validate_inventory
    from solus_api.bridge.frames import HelloData, HelloServer, HelloTool
    from solus_api.simulation.sessions_ledger import SessionsLedger
    from sqlalchemy.ext.asyncio import async_sessionmaker

    repository = Path(__file__).resolve().parents[4]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "integrations.mcp.isaac.solus.server"],
        cwd=str(repository),
        env={"SOLUS_MCP_WORKSPACE": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            advertised = await session.list_tools()
    hello = HelloData(
        protocol_version=1,
        companion_version="test",
        companion_instance_id="isaac-boundary-test",
        servers=(
            HelloServer(
                server="isaac",
                tools=tuple(
                    HelloTool(name=tool.name, input_schema=tool.inputSchema)
                    for tool in advertised.tools
                ),
            ),
        ),
    )
    inventory = validate_inventory(hello, load_allowlist(repository / "integrations/mcp"))
    from solus_api.agent.tools.isaac_models import PUBLIC_MODELS

    expected = {"isaac." + tool.name for tool in advertised.tools}
    assert len(expected) == 16  # SOLUSDEV-322 P4-T1: the 8 stage tools joined the roster
    assert {spec.descriptor.name for spec in inventory} == expected
    raw = {spec.descriptor.name: _RawTool(spec.descriptor) for spec in inventory}
    maker = async_sessionmaker()
    wrappers = build_isaac_tools(maker, uuid4(), raw, ledger=SessionsLedger(maker))
    # Every cloud wrapper is an allowlisted, advertised tool; P4-T2 widens PUBLIC_MODELS to 15 —
    # `put_asset` stays internal to `spawn_at` and never becomes a SOL-visible tool.
    wrapped = {tool.descriptor.name for tool in wrappers}
    assert wrapped == {"isaac." + name for name in PUBLIC_MODELS} and wrapped <= expected
    assert expected - wrapped == {"isaac.put_asset"}
    # SOLUSDEV-322 P2-T3/P4-T2: the gate is per call (ownership ledger), not a static descriptor
    # flag; only `save_stage` (a write into the user's own file) is statically gated.
    assert {t.descriptor.name for t in wrappers if t.descriptor.requires_confirmation} == {
        "isaac.save_stage"
    }
    assert all(callable(getattr(tool, "needs_confirmation", None)) for tool in wrappers)
    assert list(tmp_path.iterdir()) == []


async def test_stdio_status_maps_to_cloud_top_level_state(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[4]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "integrations.mcp.isaac.solus.server"],
        cwd=str(repository),
        env={"SOLUS_MCP_WORKSPACE": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("status", {})
            assert not result.isError
            mapped = json.loads(map_result("owned-status", result))
            assert mapped["data"]["value"]["state"] == "stopped"
            assert list(tmp_path.iterdir()) == []


def test_declared_digest_fields_survive_redaction_without_laundering_other_fields() -> None:
    from solus_api.agent.tools.untrusted import redact_value

    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from integrations.mcp.isaac.solus.server import wire_result

    digest = "0123456789abcdef" * 4
    original = {
        "fingerprint": digest,
        "graph_digest": digest,
        "runtime_fingerprint": digest,
        "artifact": {"sha256": digest},
        "untrusted": digest,
        "api_key": digest,
    }
    encoded = wire_result(original)
    safe = redact_value(encoded)
    expected = ":".join(digest[i : i + 16] for i in range(0, 64, 16))
    assert safe["fingerprint"] == safe["graph_digest"] == safe["runtime_fingerprint"] == expected
    assert safe["artifact"]["sha256"] == expected
    assert safe["untrusted"] == safe["api_key"] == "[REDACTED]"
    assert original["fingerprint"] == digest
