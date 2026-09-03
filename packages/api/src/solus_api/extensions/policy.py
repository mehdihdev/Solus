"""Team extension policy helpers (SOLUSDEV-235 / ADR-035, task EXT-10).

The rules behind docs/api/extensions.md §10 and docs/schemas/extensions.md §4.7:
the pure `default_settings` validator (the §6.3 typing rules applied to the
LATEST APPROVED manifest) and the team-scoped queries. Every query here carries
the resolved `team_id` — a policy row is never reached by bare id (schemas §3).
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.models import (
    Extension,
    ExtensionInstall,
    ExtensionVersion,
    Project,
    TeamExtensionPolicy,
    utcnow,
)

#: §6.3 / §10 — the encoded settings object is capped at 16 KiB.
DEFAULT_SETTINGS_MAX_BYTES = 16 * 1024
POLICY_KEYS = ("blocked", "default_installed", "default_settings")
#: The state a team is in when it has no row for an extension.
NO_POLICY_STATE: dict[str, Any] = {
    "blocked": False,
    "default_installed": False,
    "default_settings": {},
}


# ------------------------------------------------------- settings validation
def _field_problem(spec: dict[str, Any], value: Any) -> str | None:
    """One declared field vs one value; the contract's SettingField typing."""
    key, kind = spec["key"], spec["type"]
    if kind == "boolean":
        return None if isinstance(value, bool) else f"{key}: expected a boolean"
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{key}: expected a number"
        low, high = spec.get("min"), spec.get("max")
        if low is not None and value < low:
            return f"{key}: below the minimum of {low}"
        if high is not None and value > high:
            return f"{key}: above the maximum of {high}"
        return None
    if not isinstance(value, str):
        return f"{key}: expected a string"
    if kind == "select" and value not in spec.get("options", []):
        return f"{key}: not one of the declared options"
    return None


def settings_problems(manifest: dict[str, Any], settings: dict[str, Any]) -> list[str]:
    """Every violation of `settings` against the manifest's `[settings]`."""
    encoded = json.dumps(settings, separators=(",", ":"), sort_keys=True).encode()
    if len(encoded) > DEFAULT_SETTINGS_MAX_BYTES:
        return [f"settings exceed {DEFAULT_SETTINGS_MAX_BYTES} bytes when encoded"]
    declared = {f["key"]: f for f in manifest.get("settings", {}).get("fields", [])}
    problems = [f"{key}: not a declared setting" for key in settings if key not in declared]
    typed = (
        _field_problem(declared[key], value) for key, value in settings.items() if key in declared
    )
    return problems + [problem for problem in typed if problem]


def validate_default_settings(manifest: dict[str, Any], settings: dict[str, Any]) -> None:
    """§10: `default_settings` must fit the latest approved manifest → 422 otherwise."""
    problems = settings_problems(manifest, settings)
    if problems:
        raise APIError(
            422,
            "validation_error",
            "default_settings do not fit the extension's settings",
            problems,
        )


# ------------------------------------------------------------------ queries
async def resolve_approved_extension(
    session: AsyncSession, slug: str
) -> tuple[Extension, ExtensionVersion]:
    """The live extension named by `slug` (case-insensitive) with its latest
    approved version — 404 when either is missing (§10: a policy on an
    extension nobody can install is meaningless)."""
    row = (
        await session.execute(
            select(Extension, ExtensionVersion)
            .join(ExtensionVersion, ExtensionVersion.id == Extension.latest_approved_version_id)
            .where(func.lower(Extension.slug) == slug.lower(), Extension.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        raise APIError(404, "not_found", "Extension not found")
    return row[0], row[1]


async def get_policy(
    session: AsyncSession, team_id: uuid.UUID, extension_id: uuid.UUID
) -> TeamExtensionPolicy | None:
    policy: TeamExtensionPolicy | None = await session.scalar(
        select(TeamExtensionPolicy).where(
            TeamExtensionPolicy.team_id == team_id,
            TeamExtensionPolicy.extension_id == extension_id,
        )
    )
    return policy


def policy_state(policy: TeamExtensionPolicy | None) -> dict[str, Any]:
    if policy is None:
        return dict(NO_POLICY_STATE)
    return {key: getattr(policy, key) for key in POLICY_KEYS}


def changed_keys(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return [key for key in POLICY_KEYS if before[key] != after[key]]


@dataclass(frozen=True)
class UpsertResult:
    policy: TeamExtensionPolicy
    created: bool
    changed_keys: list[str] = field(default_factory=list)
    newly_blocked: bool = False


async def upsert_policy(
    session: AsyncSession,
    *,
    team_id: uuid.UUID,
    extension_id: uuid.UUID,
    changes: dict[str, Any],
    set_by: uuid.UUID,
) -> UpsertResult:
    """Merge `changes` (a subset of POLICY_KEYS) into the team's row, creating
    it when absent. The merged state may not be both blocked and a default —
    the DB CHECK would refuse it; refusing here gives the caller a 422 instead
    of a 500."""
    existing = await get_policy(session, team_id, extension_id)
    before = policy_state(existing)
    after = {**before, **changes}
    if after["blocked"] and after["default_installed"]:
        raise APIError(
            422,
            "validation_error",
            "A blocked extension cannot also be default_installed; clear the default first",
        )
    policy = existing or TeamExtensionPolicy(team_id=team_id, extension_id=extension_id)
    for key in POLICY_KEYS:
        setattr(policy, key, after[key])
    policy.set_by = set_by
    session.add(policy)
    await session.flush()
    return UpsertResult(
        policy=policy,
        created=existing is None,
        changed_keys=changed_keys(before, after),
        newly_blocked=bool(after["blocked"] and not before["blocked"]),
    )


@dataclass(frozen=True)
class DisabledInstall:
    project_id: uuid.UUID
    version: str


async def disable_installs_for_block(
    session: AsyncSession, *, team_id: uuid.UUID, extension_id: uuid.UUID
) -> list[DisabledInstall]:
    """§10 block effect: `enabled = false` on every still-enabled install of the
    extension in any project of THIS team. Returns one entry per project so
    the router can emit `extension.disable` for each."""
    team_projects = select(Project.id).where(Project.team_id == team_id)
    flipped = (
        await session.execute(
            update(ExtensionInstall)
            .where(
                ExtensionInstall.extension_id == extension_id,
                ExtensionInstall.project_id.in_(team_projects),
                ExtensionInstall.enabled.is_(True),
            )
            .values(enabled=False, updated_at=utcnow())
            .returning(ExtensionInstall.project_id, ExtensionInstall.version_id)
            .execution_options(synchronize_session=False)
        )
    ).all()
    if not flipped:
        return []
    version_rows = await session.execute(
        select(ExtensionVersion.id, ExtensionVersion.version).where(
            ExtensionVersion.id.in_({version_id for _, version_id in flipped})
        )
    )
    versions: dict[uuid.UUID, str] = {row[0]: row[1] for row in version_rows.all()}
    return [DisabledInstall(project_id, versions[version_id]) for project_id, version_id in flipped]
