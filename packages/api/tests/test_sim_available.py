"""SOLUSDEV-322 P1-T2 — `sim.available`: what can simulate for this person, honestly.

One row per provider. `installed` is a fact read off the person's machine (`attrs.simulators`) or
this process; `connected` is whether the provider's routine tools are registered in THIS registry
(the bridge's probes); `runnable_here` needs both and the platform. The tool never guesses: with
no companion it says "companion offline" and Isaac stays `installed=None`. At most two companion
calls, and only through probe tools already registered.
"""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools import ToolRegistry
from solus_api.agent.tools import sim_available as module
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.sim_available import SimAvailability
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.core.config import Settings
from solus_api.models import Project, Team, User
from solus_api.services.machines import MachineIn, upsert_machine
from solus_api.simulation.sessions_ledger import SessionsLedger
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]

COMPANION = "0123456789abcdef0123456789abcdef"
QUEUED = cast(
    Settings, SimpleNamespace(redis_url="redis://queue", sync_inline=False, ngspice_bin=None)
)
UNQUEUED = cast(Settings, SimpleNamespace(redis_url=None, sync_inline=True, ngspice_bin=None))
#: One line, ends in a period, no absolute path: what SOL repeats to the person as it is.
_SENTENCE = re.compile(r"[^\n]*\S\.")
_ABSOLUTE_PATH = re.compile(r"(?<![\w.])/\w")
EMPTY_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}


async def _project_and_user(maker: Maker) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as db:
        team = Team(name="sim-available")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="sim-available")
        user = User(supabase_user_id=uuid.uuid4().hex, email=f"{uuid.uuid4().hex}@example.com")
        db.add_all([project, user])
        await db.commit()
        return project.id, user.id


async def _machine(
    maker: Maker,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    os: str = "Linux",
    arch: str = "x86_64",
    versions: dict[str, str] | None = None,
) -> None:
    async with maker() as db:
        await upsert_machine(
            db,
            project_id,
            user_id,
            COMPANION,
            MachineIn(hostname="bench", os=os, arch=arch),
            tool_versions=versions if versions is not None else {},
        )
        await db.commit()


def _probe(name: str, result: dict[str, Any] | None) -> InProcessTool:
    """A fake probe answering `result`, or raising "bridge offline" when it is None."""

    async def handler(_args: dict[str, Any]) -> dict[str, Any]:
        if result is None:
            raise ToolException("bridge offline", code=ToolErrorCode.UNAVAILABLE, retryable=True)
        return result

    return InProcessTool(
        ToolDescriptor(name=name, description="fake probe", params=EMPTY_ARGS, returns={}),
        handler,
    )


async def _rows(
    maker: Maker,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    registry: ToolRegistry | None = None,
    settings: Settings = QUEUED,
) -> dict[str, dict[str, Any]]:
    tool = SimAvailability(
        maker,
        project_id,
        user_id=user_id,
        settings=settings,
        registry=registry or ToolRegistry(),
        ledger=SessionsLedger(maker),
    )
    result = await tool.handler({})
    rows = {row["provider"]: row for row in result["providers"]}
    assert set(rows) == {"calculators", "mujoco", "ngspice", "gazebo", "isaac"}
    return rows


def test_descriptor_is_an_ungated_bounded_read() -> None:
    descriptor = SimAvailability(
        async_sessionmaker(),
        uuid.uuid4(),
        user_id=uuid.uuid4(),
        settings=None,
        registry=ToolRegistry(),
        ledger=SessionsLedger(async_sessionmaker()),
    ).descriptor
    assert descriptor.name == "sim.available"
    assert descriptor.requires_confirmation is False
    assert descriptor.timeout_seconds == 45


async def test_sim_available_rows_without_companion(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, user_id = await _project_and_user(maker)
    await _machine(maker, project_id, user_id, versions={"gz": "8.15.0"})
    monkeypatch.setattr(module, "_find_spec", lambda name: object() if name == "mujoco" else None)

    rows = await _rows(maker, project_id, user_id)

    assert rows["mujoco"]["installed"] is True and rows["mujoco"]["connected"] is True
    gazebo = rows["gazebo"]
    assert gazebo["installed"] is True and gazebo["version"] == "8.15.0"
    assert gazebo["connected"] is False and gazebo["runnable_here"] is False
    assert gazebo["reason"] == "The companion is offline (bridge offline)."
    assert gazebo["capabilities"] is None
    assert rows["isaac"]["installed"] is None and rows["isaac"]["connected"] is False
    assert rows["calculators"] == {
        "provider": "calculators",
        "installed": True,
        "connected": True,
        "runnable_here": True,
        "reason": None,
        "version": None,
        "running_sessions": {"owned": 0, "attached": 0},
        "capabilities": None,
    }
    for row in rows.values():
        assert row["running_sessions"] == {"owned": 0, "attached": 0}


async def test_sim_available_forwards_probe_capabilities_when_connected(
    engine: AsyncEngine,
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, user_id = await _project_and_user(maker)
    await _machine(maker, project_id, user_id, versions={"gz": "8.15.0", "nvidia-smi": "550"})
    registry = ToolRegistry()
    capabilities = {"families": ["gz"], "version": "8.15.0", "headless": True}
    registry.register(_probe("gazebo.probe", capabilities))
    registry.register(_probe("isaac.probe", {"available": True, "version": "4.5.0"}))

    rows = await _rows(maker, project_id, user_id, registry=registry)

    gazebo = rows["gazebo"]
    assert gazebo["connected"] is True and gazebo["runnable_here"] is True
    assert gazebo["capabilities"] == capabilities and gazebo["reason"] is None
    isaac = rows["isaac"]
    assert isaac["connected"] is True and isaac["installed"] is True
    assert isaac["runnable_here"] is True and isaac["version"] == "4.5.0"
    assert isaac["capabilities"] == {"available": True, "version": "4.5.0"}


@pytest.mark.parametrize(
    ("os", "arch", "versions", "expected"),
    [
        ("Darwin", "arm64", {"nvidia-smi": "550"}, "Isaac runs only on Linux with an NVIDIA GPU"),
        ("Linux", "x86_64", {}, "NVIDIA GPU"),
        ("Linux", "aarch64", {"nvidia-smi": "550"}, "x86_64 only"),
        # Node's os.arch()/os.platform() vocabulary, which is what the desktop actually PUTs.
        ("darwin", "arm64", {"nvidia-smi": "550"}, "Isaac runs only on Linux with an NVIDIA GPU"),
        ("linux", "arm64", {"nvidia-smi": "550"}, "x86_64 only"),
        ("linux", "x64", {}, "NVIDIA GPU"),
    ],
)
async def test_sim_available_isaac_not_runnable_on_macos_and_without_gpu(
    engine: AsyncEngine, os: str, arch: str, versions: dict[str, str], expected: str
) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, user_id = await _project_and_user(maker)
    await _machine(maker, project_id, user_id, os=os, arch=arch, versions=versions)
    registry = ToolRegistry()
    registry.register(_probe("isaac.probe", {"available": True}))

    isaac = (await _rows(maker, project_id, user_id, registry=registry))["isaac"]

    assert isaac["connected"] is True and isaac["runnable_here"] is False
    assert expected in (isaac["reason"] or "")


@pytest.mark.parametrize(
    ("os", "arch"), [("linux", "x64"), ("Linux", "x86_64"), ("Linux", "amd64")]
)
async def test_sim_available_isaac_runnable_with_desktop_arch_vocabulary(
    engine: AsyncEngine, os: str, arch: str
) -> None:
    """The desktop reports Node's `os.arch()` (`x64`), never Python's `x86_64`; both must pass."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, user_id = await _project_and_user(maker)
    await _machine(maker, project_id, user_id, os=os, arch=arch, versions={"nvidia-smi": "550"})
    registry = ToolRegistry()
    registry.register(_probe("isaac.probe", {"available": True}))

    isaac = (await _rows(maker, project_id, user_id, registry=registry))["isaac"]

    assert isaac["runnable_here"] is True and isaac["reason"] is None


async def test_running_sessions_count_owned_and_attached(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, user_id = await _project_and_user(maker)
    ledger = SessionsLedger(maker)
    await ledger.record_owned_start(
        project_id=project_id,
        provider="gazebo",
        session_id="owned-1",
        call_id="call-1",
        scene_ref="worlds/empty.sdf",
        created_by=user_id,
    )
    for n in range(2):
        await ledger.record_attached(
            project_id=project_id,
            provider="gazebo",
            session_id=f"attached-{n}",
            scene_ref=None,
            created_by=user_id,
        )
    # Another project's sessions are never counted here.
    other_project, other_user = await _project_and_user(maker)
    await ledger.record_attached(
        project_id=other_project, provider="isaac", session_id="x", scene_ref=None, created_by=None
    )

    rows = await _rows(maker, project_id, user_id)

    assert rows["gazebo"]["running_sessions"] == {"owned": 1, "attached": 2}
    assert rows["isaac"]["running_sessions"] == {"owned": 0, "attached": 0}


async def test_sim_available_is_registered_only_with_a_bound_user(engine: AsyncEngine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, user_id = await _project_and_user(maker)

    bare = {d.name for d in build_sol_registry(maker, project_id).list()}
    bound = {d.name for d in build_sol_registry(maker, project_id, user_id=user_id).list()}

    assert "sim.available" not in bare
    assert "sim.available" in bound


@pytest.mark.parametrize(
    ("scenario", "machine", "probes", "settings", "failing", "says"),
    [
        (
            "not_installed_no_companion_no_queue",
            {"versions": {}},
            None,
            UNQUEUED,
            {"mujoco", "ngspice", "gazebo", "isaac"},
            {"mujoco": "not installed", "gazebo": "bridge offline", "isaac": "GPU"},
        ),
        (
            "installed_but_no_queue",
            {"versions": {"gz": "8.15.0"}},
            {"gazebo.probe": {"families": ["gz"]}},
            UNQUEUED,
            {"mujoco", "ngspice", "isaac"},
            {"mujoco": "not installed", "ngspice": "SOLUS_NGSPICE_BIN"},
        ),
        (
            "no_machine_registered",
            None,
            {"gazebo.probe": {"families": []}, "isaac.probe": {"available": True}},
            QUEUED,
            {"mujoco", "ngspice", "gazebo"},
            {"gazebo": "machine"},
        ),
        (
            "not_linux",
            {"os": "Darwin", "arch": "arm64", "versions": {"nvidia-smi": "550"}},
            {"isaac.probe": {"available": True}},
            QUEUED,
            {"mujoco", "ngspice", "gazebo", "isaac"},
            {"isaac": "Linux", "gazebo": "bridge offline"},
        ),
        (
            "no_gpu",
            {"os": "Linux", "arch": "x86_64", "versions": {}},
            {"isaac.probe": {"available": True}},
            QUEUED,
            {"mujoco", "ngspice", "gazebo", "isaac"},
            {"isaac": "GPU"},
        ),
        (
            "x86_64_only",
            {"os": "Linux", "arch": "aarch64", "versions": {"nvidia-smi": "550"}},
            {"isaac.probe": {"available": True}},
            QUEUED,
            {"mujoco", "ngspice", "gazebo", "isaac"},
            {"isaac": "x86_64"},
        ),
        (
            "probes_fail_bridge_offline",
            {"versions": {"gz": "8.15.0", "nvidia-smi": "550"}},
            {"gazebo.probe": None, "isaac.probe": None},
            QUEUED,
            {"mujoco", "ngspice", "gazebo", "isaac"},
            {"gazebo": "probe", "isaac": "probe"},
        ),
        (
            "isaac_probe_does_not_verify",
            {"versions": {"nvidia-smi": "550"}},
            {"isaac.probe": {"version": "4.5.0"}},
            QUEUED,
            {"mujoco", "ngspice", "gazebo", "isaac"},
            {"isaac": "unverified"},
        ),
    ],
)
async def test_every_failure_result_has_a_reason_sentence(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    machine: dict[str, Any] | None,
    probes: dict[str, dict[str, Any] | None] | None,
    settings: Settings,
    failing: set[str],
    says: dict[str, str],
) -> None:
    """P7-T2: a provider that cannot run here says why in one sentence SOL can repeat — not
    installed, no queue, no machine, not Linux, no GPU, x86_64 only, companion offline, a probe
    that failed or did not verify. `runnable_here` rows carry no reason at all."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, user_id = await _project_and_user(maker)
    if machine is not None:
        await _machine(maker, project_id, user_id, **machine)
    monkeypatch.setattr(module, "_find_spec", lambda name: None)
    registry = ToolRegistry()
    for name, answer in (probes or {}).items():
        registry.register(_probe(name, answer))

    rows = await _rows(maker, project_id, user_id, registry=registry, settings=settings)

    assert {p for p, row in rows.items() if row["runnable_here"] is False} == failing, scenario
    for provider, row in rows.items():
        reason = row["reason"]
        if row["runnable_here"]:
            assert reason is None, (provider, reason)
            continue
        assert isinstance(reason, str) and _SENTENCE.fullmatch(reason), (provider, reason)
        assert not _ABSOLUTE_PATH.search(reason), (provider, reason)
        if provider in says:
            assert says[provider] in reason, (provider, reason)
