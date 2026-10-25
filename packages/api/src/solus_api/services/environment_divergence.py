"""Environment divergences (SOLUSDEV-320 P5-T3, docs/api/solus.md §2.1 `environment/divergences`).

`diff_environment` is pure: the spec, one machine's observed `environment/software`
document and its `tool_versions` → `[{cause, items}]` with the desktop's four causes
(`lib/api/environment.ts`). Only what was observed is compared: a package ecosystem the
venv cannot show (npm, ros) is never reported missing, a machine without a CONFIG says
nothing, and an installed version the probe could not read is unknown rather than drift.
`recompute_divergences` stores ONE `environment/divergences` CONFIG per project, bound to
the cell's own `solus_subsection` node (the spec is bound to the `.solus` root), so neither
counts toward the per-section cap (resolution 20).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any, Final

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.graph import kinds
from solus_api.models import GraphEntity, SolusEntry, SolusEntryKind, SolusSection, utcnow
from solus_api.services.code_env import SUBSECTION as SOFTWARE_SUBSECTION
from solus_api.services.code_env import CodeEnvironment
from solus_api.services.environment_spec import _normalize_name, recompute_environment_spec
from solus_api.services.solus_config import find_config_entry, put_config_entry
from solus_api.services.solus_graph import SolusGraph
from solus_api.services.solus_payloads import (
    DivergenceCause,
    DivergenceGroup,
    DivergenceItem,
    EnvironmentDivergencesDoc,
    EnvironmentSpec,
    MachineDivergences,
)

logger = logging.getLogger("solus.services.environment_divergence")

DIVERGENCES_SUBSECTION: Final = "divergences"
CAUSES: Final[tuple[DivergenceCause, ...]] = ("missing", "version_drift", "platform_build", "extra")
#: The only ecosystem a `CodeEnvironment` (a venv) can show installed packages for.
_OBSERVABLE: Final = "python"


def _installed_pins(machine_env: Mapping[str, Any] | None) -> dict[str, str | None] | None:
    if machine_env is None:
        return None
    try:
        env = CodeEnvironment.model_validate(machine_env)
    except ValidationError:
        return None
    return {_normalize_name(pin.name): pin.version for pin in env.packages}


def _satisfies(specifier: str, version: str) -> bool | None:
    """None when either side is not PEP 440 (then nothing is claimed)."""
    try:
        return SpecifierSet(specifier).contains(Version(version), prereleases=True)
    except (InvalidSpecifier, InvalidVersion):
        return None


def _local_tag(version: str) -> str | None:
    try:
        return Version(version).local
    except InvalidVersion:
        return None


def _pin_items(spec: EnvironmentSpec, installed: dict[str, str | None]) -> dict[str, list[Any]]:
    groups: dict[str, list[DivergenceItem]] = {cause: [] for cause in CAUSES}
    wanted = [p for p in spec.packages if p.ecosystem == _OBSERVABLE]
    for package in wanted:
        key = _normalize_name(package.name)
        if key not in installed:
            groups["missing"].append(DivergenceItem(name=package.name, expected=package.specifier))
            continue
        version = installed[key]
        if version is None:
            continue
        if package.specifier is not None and _satisfies(package.specifier, version) is False:
            groups["version_drift"].append(
                DivergenceItem(name=package.name, expected=package.specifier, actual=version)
            )
            continue
        local = _local_tag(version)
        if local:
            groups["platform_build"].append(
                DivergenceItem(
                    name=package.name,
                    expected=package.specifier,
                    actual=version,
                    detail=f"platform build +{local}",
                )
            )
    if wanted:  # an empty spec has nothing to be "extra" to
        names = {_normalize_name(p.name) for p in wanted}
        groups["extra"].extend(
            DivergenceItem(name=key, actual=version)
            for key, version in installed.items()
            if key not in names
        )
    return groups


def _tool_items(spec: EnvironmentSpec, tool_versions: Mapping[str, str]) -> dict[str, list[Any]]:
    groups: dict[str, list[DivergenceItem]] = {cause: [] for cause in CAUSES}
    for tool in spec.tools:
        line = tool_versions.get(tool.name)
        if line is None:
            groups["missing"].append(DivergenceItem(name=tool.name, expected=tool.version))
        elif tool.version and tool.version not in line:
            groups["version_drift"].append(
                DivergenceItem(name=tool.name, expected=tool.version, actual=line[:200])
            )
    return groups


def diff_environment(
    spec: EnvironmentSpec,
    machine_env: Mapping[str, Any] | None,
    tool_versions: Mapping[str, str],
) -> list[dict[str, Any]]:
    """`[{cause, items}]` in CAUSES order, empty groups left out."""
    installed = _installed_pins(machine_env)
    pins = _pin_items(spec, installed) if installed is not None else {c: [] for c in CAUSES}
    tools = _tool_items(spec, tool_versions)
    return [
        DivergenceGroup(cause=cause, items=pins[cause] + tools[cause]).model_dump(mode="json")
        for cause in CAUSES
        if pins[cause] or tools[cause]
    ]


async def _machine_environments(
    session: AsyncSession, project_id: uuid.UUID, machine_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any] | None]:
    if not machine_ids:
        return {}
    rows = await session.scalars(
        select(SolusEntry).where(
            SolusEntry.project_id == project_id,
            SolusEntry.section == SolusSection.ENVIRONMENT,
            SolusEntry.subsection == SOFTWARE_SUBSECTION,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.configured_entity_id.in_(machine_ids),
            SolusEntry.deleted_at.is_(None),
        )
    )
    return {row.configured_entity_id: row.payload for row in rows if row.configured_entity_id}


def _tool_versions_of(machine: GraphEntity) -> dict[str, str]:
    raw = machine.attrs.get("tool_versions")
    if not isinstance(raw, Mapping):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


async def recompute_divergences(session: AsyncSession, project_id: uuid.UUID) -> SolusEntry:
    """Recompute the spec, diff every `machine` of the project against it and store the
    document as the ONE `environment/divergences` CONFIG (unbound; same id each time)."""
    spec_entry = await recompute_environment_spec(session, project_id)
    spec = EnvironmentSpec.model_validate(spec_entry.payload)
    machines = list(
        await session.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind == kinds.MACHINE,
                GraphEntity.deleted_at.is_(None),
            )
            .order_by(GraphEntity.created_at, GraphEntity.id)
        )
    )
    environments = await _machine_environments(session, project_id, [m.id for m in machines])
    doc = EnvironmentDivergencesDoc(
        computed_at=utcnow(),
        spec_entry_id=spec_entry.id,
        machines=[
            MachineDivergences(
                machine_id=machine.id,
                hostname=str(machine.attrs.get("hostname") or machine.name)[:128],
                causes=[
                    DivergenceGroup.model_validate(group)
                    for group in diff_environment(
                        spec, environments.get(machine.id), _tool_versions_of(machine)
                    )
                ],
            )
            for machine in machines
        ],
    )
    graph = await SolusGraph.ensure(session, project_id)
    subject = graph.subsection_node(SolusSection.ENVIRONMENT, DIVERGENCES_SUBSECTION)
    entry = await put_config_entry(
        session,
        project_id,
        SolusSection.ENVIRONMENT,
        DIVERGENCES_SUBSECTION,
        doc,
        text="Environment divergences",
        configured_entity_id=subject.id,
        created_by=None,
        author="system",
        ignore=("computed_at",),
    )
    logger.info(
        "environment divergences project=%s machines=%d diverging=%d",
        project_id,
        len(doc.machines),
        sum(1 for m in doc.machines if m.causes),
    )
    return entry


async def find_divergences_entry(session: AsyncSession, project_id: uuid.UUID) -> SolusEntry | None:
    return await find_config_entry(
        session, project_id, SolusSection.ENVIRONMENT, DIVERGENCES_SUBSECTION, any_subject=True
    )


async def recompute_divergences_guarded(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The hook form: one SAVEPOINT, logged, never raises — a failed recompute must never
    fail the sync, the config save or the machine PUT that triggered it."""
    try:
        async with session.begin_nested():
            await recompute_divergences(session, project_id)
    except Exception:  # noqa: BLE001 — best-effort derived data, the caller's write stands
        logger.exception("environment recompute failed project=%s", project_id)
