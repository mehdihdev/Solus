"""`exposure: internal` (sol-drive.md §3, ADR-041): a server whose tools the
companion may advertise and the cloud accepts, but which are NEVER registered in
the SOL agent's tool set — only Solus code (the drive executor) dispatches them.
Like `requires_confirmation`, exposure comes ONLY from the Solus-owned allowlist."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from solus_api.agent.runtime import build_sol_registry
from solus_api.bridge.allowlist import ServerAllowlist, load_allowlist, validate_inventory
from solus_api.bridge.frames import HelloData
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from sqlalchemy.ext.asyncio import async_sessionmaker

INTERNAL_YAML = """
server: drive
launched_by: builtin
exposure: internal
tools:
  - name: identify
  - name: act
    requires_confirmation: true
    reason: moves your mouse and types in the bound window
"""

MODEL_YAML = """
server: mock
tools:
  - name: echo
"""


def _hello(servers: dict[str, list[str]]) -> HelloData:
    return HelloData.model_validate(
        {
            "protocol_version": 1,
            "companion_version": "0.1.0",
            "companion_instance_id": "i-1",
            "servers": [
                {
                    "server": server,
                    "tools": [
                        {"name": name, "description": "d", "input_schema": {"type": "object"}}
                        for name in names
                    ],
                }
                for server, names in servers.items()
            ],
        }
    )


def _allowlists(tmp_path: Path) -> Path:
    for server, text in (("drive", INTERNAL_YAML), ("mock", MODEL_YAML)):
        (tmp_path / server).mkdir()
        (tmp_path / server / "allowlist.yaml").write_text(text)
    return tmp_path


def test_exposure_defaults_to_model() -> None:
    assert ServerAllowlist(server="x").exposure == "model"


def test_exposure_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        ServerAllowlist.model_validate({"server": "x", "exposure": "public"})


def test_internal_specs_are_accepted_and_marked(tmp_path: Path) -> None:
    specs = validate_inventory(
        _hello({"drive": ["identify", "act"], "mock": ["echo"]}),
        load_allowlist(_allowlists(tmp_path)),
    )
    internal = {s.descriptor.name: s.internal for s in specs}
    assert internal == {"drive.identify": True, "drive.act": True, "mock.echo": False}


def test_a_companion_cannot_make_an_internal_tool_model_facing(tmp_path: Path) -> None:
    # The advertisement has no exposure field at all; the allowlist alone decides.
    hello = _hello({"drive": ["identify"]})
    assert "exposure" not in hello.model_dump_json()
    (spec,) = validate_inventory(hello, load_allowlist(_allowlists(tmp_path)))
    assert spec.internal is True


def _session(scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID], specs: tuple) -> BridgeSession:  # type: ignore[type-arg]
    async def _send(frame: str) -> None:
        return None

    async def _close(code: int) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=specs,
        send=_send,
        close=_close,
        max_inflight=8,
    )


def test_internal_tools_never_reach_the_agent_tool_set(tmp_path: Path) -> None:
    scope = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    specs = validate_inventory(
        _hello({"drive": ["identify", "act"], "mock": ["echo"]}),
        load_allowlist(_allowlists(tmp_path)),
    )
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(_session(scope, specs))
    registry = build_sol_registry(
        async_sessionmaker(), scope[2], bridge=sessions, user_id=scope[0], team_id=scope[1]
    )
    names = {d.name for d in registry.list()}
    assert "mock.echo" in names
    assert not {n for n in names if n.startswith("drive.") and n != "drive.step"}


def test_the_real_drive_allowlist_is_internal_and_gates_act() -> None:
    root = Path(__file__).resolve().parents[3] / "integrations" / "mcp"
    loaded = load_allowlist(root)
    assert "drive" in loaded.internal
    act = loaded.get("drive", "act")
    assert act is not None and act.requires_confirmation is True
    assert loaded.internal == {"drive"}
