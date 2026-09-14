"""Real MCP SDK stdio transport and companion result mapping; never starts Isaac."""

import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from solus_companion.dispatch import map_result


async def test_actual_advertisement_survives_bridge_gate_and_exposes_all_cloud_wrappers(tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4

    from solus_api.agent.tools.isaac_tools import build_isaac_tools
    from solus_api.bridge.allowlist import load_allowlist, validate_inventory
    from solus_api.bridge.frames import HelloData, HelloServer, HelloTool
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
    expected = {"isaac." + tool.name for tool in advertised.tools}
    assert len(expected) == 8
    assert {spec.descriptor.name for spec in inventory} == expected
    raw = {spec.descriptor.name: SimpleNamespace(descriptor=spec.descriptor) for spec in inventory}
    wrappers = build_isaac_tools(async_sessionmaker(), uuid4(), raw)
    assert {tool.descriptor.name for tool in wrappers} == expected
    assert all(
        tool.descriptor.requires_confirmation
        for tool in wrappers
        if tool.descriptor.name not in {"isaac.probe", "isaac.status"}
    )
    assert list(tmp_path.iterdir()) == []


async def test_stdio_status_maps_to_cloud_top_level_state(tmp_path):
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


def test_declared_digest_fields_survive_redaction_without_laundering_other_fields():
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
