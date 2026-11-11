"""SOLUSDEV-322 P1-T2 — `sim.available`: what can simulate for this person, honestly.

One row per provider. `installed` is a fact read off the person's machine (`attrs.simulators`,
derived by `services/machine_simulators.py`) or off this process; `connected` is whether the
provider's routine tools are registered in THIS registry (connection is registration, P1-T3);
`runnable_here` needs both and the platform. The tool never guesses: with no companion a bridge
row says the companion is offline and Isaac stays `installed=None`. Every `reason` is one
sentence SOL repeats as it is (P7-T2).

An adapter by design (`tests/test_sol_runtime.py` allowlist): it calls at most two probe tool
OBJECTS directly — `gazebo.probe` and `isaac.probe` — and only when the registry already holds
them, inside the dispatch the gate made for `sim.available` itself. It never reaches the registry.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.project_card import owns_machine
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.tool import InProcessTool, ToolException
from solus_api.billing.development import SESSION_SETTINGS_KEY
from solus_api.graph import kinds
from solus_api.models import GraphEntity
from solus_api.simulation.providers.ngspice_provider import pinned_simulator
from solus_api.simulation.sessions_ledger import SessionsLedger
from solus_api.simulation.sim_ladder import jobs_queued

if TYPE_CHECKING:
    from solus_api.core.config import Settings

logger = logging.getLogger("solus.agent.tools.sim_available")

NAME = "sim.available"
_TIMEOUT_SECONDS = 45
_PROBES = {"gazebo": "gazebo.probe", "isaac": "isaac.probe"}
_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}
#: Module attribute so a test can stand in a server with or without the package.
_find_spec = importlib.util.find_spec
#: The reasons a row cannot run here: one sentence each, repeated by SOL as it is.
_OFFLINE = "The companion is offline (bridge offline)."
_NO_MACHINE = "No machine is registered for you in this project."
_NO_QUEUE = "No job queue is configured on this server to run rung-3 jobs."

Row = dict[str, Any]
Counts = dict[str, int]


@dataclass(frozen=True)
class _MachineFacts:
    os: str
    arch: str
    simulators: Mapping[str, Any]

    @classmethod
    def of(cls, attrs: Mapping[str, Any]) -> _MachineFacts:
        simulators = attrs.get("simulators")
        return cls(
            os=str(attrs.get("os") or ""),
            arch=str(attrs.get("arch") or ""),
            simulators=simulators if isinstance(simulators, Mapping) else {},
        )


@dataclass(frozen=True)
class _ProbeAnswer:
    """One probe tool's answer: `value` when it answered, else the failure code."""

    value: dict[str, Any] | None
    error: str | None = None


def _provider_row(
    provider: str,
    *,
    installed: bool | None,
    connected: bool,
    runnable_here: bool,
    sessions: Counts,
    reason: str | None = None,
    version: str | None = None,
    capabilities: dict[str, Any] | None = None,
) -> Row:
    return {
        "provider": provider,
        "installed": installed,
        "connected": connected,
        "runnable_here": runnable_here,
        "reason": reason,
        "version": version,
        "running_sessions": sessions,
        "capabilities": capabilities,
    }


def _job_provider_row(
    provider: str,
    *,
    installed: bool,
    queued: bool,
    sessions: Counts,
    missing: str,
    version: str | None = None,
) -> Row:
    """A rung-3 provider of this deployment: installed here, run by the job queue."""
    reason = missing if not installed else None if queued else _NO_QUEUE
    return _provider_row(
        provider,
        installed=installed,
        connected=installed and queued,
        runnable_here=installed and queued,
        sessions=sessions,
        reason=reason,
        version=version,
    )


def _mujoco_version() -> str | None:
    try:
        return importlib.metadata.version("mujoco")
    except importlib.metadata.PackageNotFoundError:
        return None


def _gazebo_row(machine: _MachineFacts | None, probe: _ProbeAnswer | None, sessions: Counts) -> Row:
    found = machine.simulators.get("gazebo") if machine is not None else None
    found = found if isinstance(found, Mapping) else None
    installed = None if machine is None else found is not None
    if probe is None:
        reason: str | None = _OFFLINE
    elif machine is None:
        reason = _NO_MACHINE
    elif not installed:
        reason = "No Gazebo binary was detected on the machine."
    elif probe.error is not None:
        reason = f"The Gazebo probe failed ({probe.error})."
    else:
        reason = None
    return _provider_row(
        "gazebo",
        installed=installed,
        connected=probe is not None,
        runnable_here=reason is None,
        sessions=sessions,
        reason=reason,
        version=str(found["version"]) if found and found.get("version") else None,
        capabilities=probe.value if probe is not None else None,
    )


# The desktop PUTs Node's `os.arch()` vocabulary (`x64`, `arm64`), not Python's (`x86_64`).
_X86_64_ARCHES = frozenset({"x86_64", "amd64", "x64"})


def _isaac_platform_reason(machine: _MachineFacts | None) -> str | None:
    if machine is None:
        return None  # unknown machine: no platform claim either way
    if machine.os.lower() != "linux":
        return "Isaac runs only on Linux with an NVIDIA GPU."
    if machine.arch.lower() not in _X86_64_ARCHES:
        return "Isaac Sim ships for x86_64 only."
    if not machine.simulators.get("nvidia_smi"):
        return "No NVIDIA GPU was detected on the machine (nvidia-smi absent)."
    return None


def _isaac_row(machine: _MachineFacts | None, probe: _ProbeAnswer | None, sessions: Counts) -> Row:
    value = probe.value if probe is not None else None
    # `available: true` establishes an installation; anything else stays unknown, never "absent".
    installed = True if value is not None and value.get("available") is True else None
    platform = _isaac_platform_reason(machine)
    if platform is not None:
        reason: str | None = platform
    elif probe is None:
        reason = _OFFLINE
    elif probe.error is not None:
        reason = f"The Isaac probe failed ({probe.error})."
    elif installed is None:
        reason = "The Isaac installation is unverified by its probe."
    else:
        reason = None
    version = value.get("version") if value is not None else None
    return _provider_row(
        "isaac",
        installed=installed,
        connected=probe is not None,
        runnable_here=reason is None,
        sessions=sessions,
        reason=reason,
        version=version if isinstance(version, str) else None,
        capabilities=value,
    )


class SimAvailability:
    """The `sim.available` handler, bound to one project and the member asking."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        settings: Settings | None,
        registry: ToolRegistry,
        ledger: SessionsLedger,
    ) -> None:
        self._sessions = sessions
        self._project_id = project_id
        self._user_id = user_id
        self._settings = settings
        self._registry = registry
        self._ledger = ledger
        self.descriptor = ToolDescriptor(
            name=NAME,
            description=(
                "List what can simulate for you right now, one row per provider (the closed-form "
                "calculators, the rigid-body and SPICE jobs, and the external simulators your "
                "machine reports): installed, connected, runnable here, version, running "
                "sessions you own or attached to, and the reason when something is not usable."
            ),
            params=_NO_ARGS,
            returns={"type": "object", "properties": {"providers": {"type": "array"}}},
            timeout_seconds=_TIMEOUT_SECONDS,
        )

    def tool(self) -> InProcessTool:
        return InProcessTool(self.descriptor, self.handler)

    async def handler(self, args: dict[str, Any]) -> dict[str, Any]:
        machine, settings = await self._machine_and_settings()
        registered = {d.name for d in self._registry.list()}
        probes = {
            provider: await self._probe(name)
            for provider, name in _PROBES.items()
            if name in registered
        }
        counts = await self._session_counts()
        queued = jobs_queued(settings)
        pinned = pinned_simulator(settings.ngspice_bin) if settings is not None else None
        mujoco = _find_spec("mujoco") is not None
        return {
            "providers": [
                _provider_row(
                    "calculators",
                    installed=True,
                    connected=True,
                    runnable_here=True,
                    sessions=counts["calculators"],
                ),
                _job_provider_row(
                    "mujoco",
                    installed=mujoco,
                    queued=queued,
                    sessions=counts["mujoco"],
                    missing="MuJoCo is not installed on the server.",
                    version=_mujoco_version() if mujoco else None,
                ),
                _job_provider_row(
                    "ngspice",
                    installed=pinned is not None,
                    queued=queued,
                    sessions=counts["ngspice"],
                    missing="No circuit simulator is pinned on the server (SOLUS_NGSPICE_BIN).",
                ),
                _gazebo_row(machine, probes.get("gazebo"), counts["gazebo"]),
                _isaac_row(machine, probes.get("isaac"), counts["isaac"]),
            ]
        }

    async def _machine_and_settings(self) -> tuple[_MachineFacts | None, Settings | None]:
        """The asker's most recently updated machine of the project, and the settings the
        session runs under when none were bound at construction."""
        async with self._sessions() as session:
            rows = await session.scalars(
                select(GraphEntity)
                .where(
                    GraphEntity.project_id == self._project_id,
                    GraphEntity.kind == kinds.MACHINE,
                    GraphEntity.deleted_at.is_(None),
                )
                .order_by(GraphEntity.updated_at.desc(), GraphEntity.id)
            )
            mine = next((m for m in rows if owns_machine(m.attrs, self._user_id)), None)
            settings = self._settings or session.info.get(SESSION_SETTINGS_KEY)
        return (_MachineFacts.of(mine.attrs) if mine is not None else None), settings

    async def _probe(self, name: str) -> _ProbeAnswer:
        tool = next(t for t in self._registry.tools() if t.descriptor.name == name)
        try:
            value = await tool.invoke({})
        except ToolException as exc:
            # By class and code only: the message can carry companion text (CLAUDE.md §7).
            logger.info("%s probe failed project=%s code=%s", name, self._project_id, exc.code)
            return _ProbeAnswer(None, exc.code.value)
        return _ProbeAnswer(value if isinstance(value, dict) else {"value": value})

    async def _session_counts(self) -> dict[str, Counts]:
        counts: dict[str, Counts] = {
            p: {"owned": 0, "attached": 0} for p in ("calculators", "mujoco", "ngspice", *_PROBES)
        }
        for record in await self._ledger.running(project_id=self._project_id):
            bucket = counts.setdefault(record.provider, {"owned": 0, "attached": 0})
            bucket["owned" if record.owner == "sol" else "attached"] += 1
        return counts


def register_sim_available(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    ledger: SessionsLedger,
    settings: Settings | None = None,
) -> None:
    """Register `sim.available` AFTER the bridge tools: it reads which probes they brought."""
    registry.register(
        SimAvailability(
            sessions,
            project_id,
            user_id=user_id,
            settings=settings,
            registry=registry,
            ledger=ledger,
        ).tool()
    )
