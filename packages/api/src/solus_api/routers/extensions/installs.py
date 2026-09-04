"""Project install, storage and widget-layout routes (SOLUSDEV-235 / ADR-035,
docs/api/extensions.md §6–§8, §11–§13; EXT-09).

Every route resolves the project through `ProjectCtx` (non-member → 404, no
existence leak). Reads have no role floor (§3); every write applies
`require_role(ctx, Role.MEMBER)` FIRST, then the §12 budget, then any lookup.
Bodies are `extra="forbid"`; ids come only from the resolved context.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator
from solus_contracts.extension_manifest import SEMVER_PATTERN, SlotSize, parse_extension_manifest
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.config import Settings
from solus_api.core.errors import APIError
from solus_api.core.pagination import encode_cursor
from solus_api.core.responses import envelope
from solus_api.deps import ProjectContext, ProjectCtx, SessionDep, SettingsDep, require_role
from solus_api.extensions import installs as svc
from solus_api.extensions.ratelimit import get_or_create_limiter, rate_limited_response
from solus_api.extensions.schemas import serialize_install, serialize_storage_value
from solus_api.extensions.schemas import serialize_widget_layout as _layout_out
from solus_api.extensions.settings_schema import (
    SETTINGS_MAX_BYTES,
    coerce_settings,
    encoded_size,
    settings_with_defaults,
    validate_settings_values,
)
from solus_api.extensions.slugs import SlugPath
from solus_api.models import (
    WIDGET_LAYOUT_MAX_SLOTS,
    Extension,
    ExtensionInstall,
    ExtensionStorage,
    ExtensionVersion,
    Role,
    WidgetLayout,
)
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/projects/{project_id}")

#: Schema §4.8 — `builtin:<id>` or `ext:<slug>` (the manifest slug rule).
LAYOUT_REF_PATTERN = r"^(builtin:[a-z][a-z0-9-]{0,63}|ext:[a-z][a-z0-9-]{1,63})$"
#: Raw-body ceiling before JSON parsing (the canonical size is what §7 caps).
_STORAGE_RAW_CEILING = 4 * svc.STORAGE_VALUE_MAX_BYTES
_INSTALL_LIMITER = "extension_install_write_limiter"
_STORAGE_LIMITER = "extension_storage_write_limiter"
_STORAGE_READ_LIMITER = "extension_storage_read_limiter"
_WINDOW_SECONDS = 60
_SENTINEL = object()

KeyPath = Annotated[str, Path(pattern=svc.STORAGE_KEY_PATTERN)]


# ------------------------------------------------------------------- bodies
class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GrantsIn(_Body):
    scopes: list[str] = Field(default_factory=list, max_length=64)
    network: list[str] = Field(default_factory=list, max_length=64)


class InstallBody(_Body):
    version: Annotated[str, StringConstraints(pattern=SEMVER_PATTERN)] | None = None
    grants: GrantsIn


class PatchBody(_Body):
    enabled: StrictBool | None = None
    settings: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> PatchBody:
        if self.enabled is None and self.settings is None:
            raise ValueError("body must carry enabled and/or settings")
        return self


class LayoutSlotIn(_Body):
    ref: Annotated[str, StringConstraints(pattern=LAYOUT_REF_PATTERN)]
    size: SlotSize


class LayoutBody(_Body):
    layout: list[LayoutSlotIn] = Field(max_length=WIDGET_LAYOUT_MAX_SLOTS)

    @model_validator(mode="after")
    def _distinct_refs(self) -> LayoutBody:
        refs = [slot.ref for slot in self.layout]
        if len(set(refs)) != len(refs):
            raise ValueError("layout refs must be distinct")
        return self


# ------------------------------------------------------------------ helpers
def _rate_limited(request: Request, attr: str, key: str, limit: int) -> Response | None:
    """§12 budgets — the shared per-process `FixedWindowLimiter` on `app.state`."""
    if get_or_create_limiter(request.app.state, attr, _WINDOW_SECONDS).bump(key) <= limit:
        return None
    return rate_limited_response("Too many extension writes; slow down", _WINDOW_SECONDS)


def _install_budget(request: Request, ctx: ProjectContext, settings: Settings) -> Response | None:
    return _rate_limited(
        request,
        _INSTALL_LIMITER,
        str(ctx.user.id),
        settings.extension_install_writes_per_minute_per_user,
    )


def _storage_budget(
    request: Request, install: ExtensionInstall, settings: Settings
) -> Response | None:
    return _rate_limited(
        request,
        _STORAGE_LIMITER,
        str(install.id),
        settings.extension_storage_writes_per_minute_per_install,
    )


def _emit(
    session: AsyncSession, ctx: ProjectContext, event_type: str, payload: dict[str, Any]
) -> None:
    emit_event(
        session,
        user=ctx.user,
        event_type=event_type,
        team_id=ctx.team.id,
        project_id=ctx.project.id,
        payload=payload,
    )


async def _installed(
    session: AsyncSession, ctx: ProjectContext, slug: str
) -> tuple[Extension, ExtensionInstall]:
    """The live extension AND this project's install of it, or 404."""
    extension = await svc.find_live_extension(session, slug)
    install = await svc.get_install(session, ctx.project.id, extension.id) if extension else None
    if extension is None or install is None:
        raise APIError(404, "not_found", "Extension is not installed in this project")
    return extension, install


async def _pinned(session: AsyncSession, install: ExtensionInstall) -> ExtensionVersion:
    version = await session.get(ExtensionVersion, install.version_id)
    if version is None:  # RESTRICT FK — unreachable
        raise APIError(500, "internal_error", "Pinned version is missing")
    return version


async def _item(
    session: AsyncSession, ctx: ProjectContext, install: ExtensionInstall
) -> dict[str, Any]:
    join = await svc.load_install_join(session, install, ctx.team.id)
    return serialize_install(
        join.install, join.extension, join.publisher, join.pinned, join.latest, join.policy
    ).payload()


def _changed_keys(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(
        key
        for key in set(before) | set(after)
        if before.get(key, _SENTINEL) != after.get(key, _SENTINEL)
    )


def _json(status_code: int, data: Any) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=envelope(data))


# -------------------------------------------------------------- §6.1 list
@router.get("/extensions")
async def list_installs(
    ctx: ProjectCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=svc.INSTALLS_MAX_LIMIT)] = svc.INSTALLS_DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    joins = await svc.list_install_joins(
        session, ctx.project.id, ctx.team.id, limit=limit, cursor=cursor
    )
    has_next = len(joins) > limit
    visible = joins[:limit]
    last = visible[-1].install if has_next and visible else None
    items = [
        serialize_install(
            j.install, j.extension, j.publisher, j.pinned, j.latest, j.policy
        ).payload()
        for j in visible
    ]
    next_cursor = encode_cursor(last.created_at, last.id) if last else None
    return envelope(items, {"limit": limit, "has_next": has_next, "next_cursor": next_cursor})


# ----------------------------------------------------------- §6.2 install
@router.put("/extensions/{slug}", response_model=None)
async def install_extension(
    slug: SlugPath,
    body: InstallBody,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    require_role(ctx, Role.MEMBER)
    if limited := _install_budget(request, ctx, settings):
        return limited
    extension = await svc.find_live_extension(session, slug)
    if extension is None:
        raise APIError(404, "not_found", "Extension not found")
    if await svc.is_blocked(session, ctx.team.id, extension.id):
        raise APIError(403, "extension_blocked", "This extension is blocked by your team")
    target = (
        await svc.approved_version(session, extension.id, body.version)
        if body.version
        else await svc.latest_approved_version(session, extension)
    )
    if target is None:
        raise APIError(404, "not_found", "No installable version of this extension")

    declared = svc.Grants.declared_by(target.manifest)
    requested = svc.Grants.of(body.grants.scopes, body.grants.network)
    if undeclared := requested - declared:
        raise APIError(
            422,
            "validation_error",
            "Grants include permissions the manifest does not declare",
            details=[undeclared.sorted_lists()],
        )
    install = await svc.get_install(session, ctx.project.id, extension.id)
    if install is None:
        created = await _create_install(session, ctx, extension, target, requested)
        return _json(201, await _item(session, ctx, created))
    await _update_install(session, ctx, extension, install, target, declared, requested)
    return _json(200, await _item(session, ctx, install))


async def _create_install(
    session: AsyncSession,
    ctx: ProjectContext,
    extension: Extension,
    target: ExtensionVersion,
    requested: svc.Grants,
) -> ExtensionInstall:
    policy = await svc.get_policy(session, ctx.team.id, extension.id)
    manifest = parse_extension_manifest(target.manifest)
    install = ExtensionInstall(
        project_id=ctx.project.id,
        extension_id=extension.id,
        version_id=target.id,
        enabled=True,
        settings=coerce_settings(manifest, policy.default_settings if policy else {}),
        granted_scopes=sorted(requested.scopes),
        granted_network=sorted(requested.network),
        installed_by=ctx.user.id,
    )
    session.add(install)
    extension.install_count = extension.install_count + 1
    _emit(
        session,
        ctx,
        "extension.install",
        {
            "slug": extension.slug,
            "version": target.version,
            "granted_scopes": sorted(requested.scopes),
            "granted_network": sorted(requested.network),
        },
    )
    await session.commit()
    return install


async def _update_install(
    session: AsyncSession,
    ctx: ProjectContext,
    extension: Extension,
    install: ExtensionInstall,
    target: ExtensionVersion,
    declared: svc.Grants,
    requested: svc.Grants,
) -> None:
    current = svc.Grants.stored_on(install)
    new_settings = install.settings
    if target.id != install.version_id:
        if missing := svc.widening(declared, current, requested):
            raise APIError(
                409,
                "grants_required",
                "The new version requires permissions not yet granted",
                details=[missing.sorted_lists()],
            )
        # Re-pin: settings the new manifest no longer declares are dropped.
        new_settings = coerce_settings(parse_extension_manifest(target.manifest), install.settings)
        install.version_id = target.id
    changed_keys = _changed_keys(install.settings, new_settings)
    added, removed = requested - current, current - requested
    if added or removed or changed_keys:
        _emit(
            session,
            ctx,
            "extension.grants_changed",
            {
                "slug": extension.slug,
                "scope": "project",
                "added_scopes": sorted(added.scopes),
                "removed_scopes": sorted(removed.scopes),
                "added_network": sorted(added.network),
                "removed_network": sorted(removed.network),
                "changed_keys": changed_keys,
            },
        )
    install.settings = new_settings
    install.granted_scopes = sorted(requested.scopes)
    install.granted_network = sorted(requested.network)
    await session.commit()


# ------------------------------------------------------------- §6.3 patch
@router.patch("/extensions/{slug}", response_model=None)
async def patch_install(
    slug: SlugPath,
    body: PatchBody,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any] | Response:
    require_role(ctx, Role.MEMBER)
    if limited := _install_budget(request, ctx, settings):
        return limited
    extension, install = await _installed(session, ctx, slug)
    pinned = await _pinned(session, install)
    new_settings = _validated_settings(pinned, body.settings)
    if body.enabled is True and await svc.is_blocked(session, ctx.team.id, extension.id):
        raise APIError(403, "extension_blocked", "This extension is blocked by your team")

    base = {"slug": extension.slug, "version": pinned.version}
    if new_settings is not None:
        changed = _changed_keys(install.settings, new_settings)
        install.settings = new_settings
        _emit(session, ctx, "extension.settings_changed", {**base, "changed_keys": changed})
    if body.enabled is not None:
        install.enabled = body.enabled
        if body.enabled:
            _emit(session, ctx, "extension.enable", base)
        else:
            _emit(session, ctx, "extension.disable", {**base, "reason": "user"})
    await session.commit()
    return envelope(await _item(session, ctx, install))


def _validated_settings(
    pinned: ExtensionVersion, values: dict[str, Any] | None
) -> dict[str, Any] | None:
    """§6.3 — the body's `settings` against the PINNED manifest, completed with
    defaults; `None` when the body carries no settings."""
    if values is None:
        return None
    if encoded_size(values) > SETTINGS_MAX_BYTES:
        raise APIError(422, "validation_error", "settings exceed 16 KiB")
    manifest = parse_extension_manifest(pinned.manifest)
    if problems := validate_settings_values(manifest, values):
        raise APIError(422, "validation_error", "Invalid settings", details=problems)
    return settings_with_defaults(manifest, values)


# --------------------------------------------------------- §6.4 uninstall
@router.delete("/extensions/{slug}", status_code=204, response_model=None)
async def uninstall_extension(
    slug: SlugPath,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    require_role(ctx, Role.MEMBER)
    if limited := _install_budget(request, ctx, settings):
        return limited
    extension, install = await _installed(session, ctx, slug)
    pinned = await _pinned(session, install)
    deleted = await svc.delete_storage(session, ctx.project.id, extension.id)
    await session.delete(install)
    extension.install_count = max(0, extension.install_count - 1)
    _emit(
        session,
        ctx,
        "extension.uninstall",
        {"slug": extension.slug, "version": pinned.version, "storage_rows_deleted": deleted},
    )
    await session.commit()
    return Response(status_code=204)


# ------------------------------------------------------------- §7 storage
async def _refuse(
    session: AsyncSession, ctx: ProjectContext, slug: str, method: str, reason: str, error: APIError
) -> None:
    """§7/§11: every refusal is an `extension.bridge_refused` event — the host
    should never have let the call through, so a refusal here is a signal."""
    _emit(
        session, ctx, "extension.bridge_refused", {"slug": slug, "method": method, "reason": reason}
    )
    await session.commit()
    raise error


async def _storage_install(
    session: AsyncSession, ctx: ProjectContext, slug: str, method: str, *, for_update: bool = False
) -> tuple[Extension, ExtensionInstall]:
    """The install a storage call runs against: present, enabled, not
    team-blocked, granting `storage.own` — else 404 / `403 scope_denied`."""
    extension = await svc.find_live_extension(session, slug)
    install = (
        await svc.get_install(session, ctx.project.id, extension.id, for_update=for_update)
        if extension
        else None
    )
    denied = APIError(403, "scope_denied", "storage.own is not available to this extension here")
    if extension is None or install is None:
        not_found = APIError(404, "not_found", "Extension is not installed in this project")
        await _refuse(session, ctx, slug, method, "not_installed", not_found)
    elif await svc.is_blocked(session, ctx.team.id, extension.id):
        await _refuse(session, ctx, slug, method, "blocked", denied)
    elif not install.enabled:
        await _refuse(session, ctx, slug, method, "disabled", denied)
    elif svc.STORAGE_SCOPE not in install.granted_scopes:
        await _refuse(session, ctx, slug, method, "scope_not_granted", denied)
    assert extension is not None and install is not None  # narrowed by the raises above
    return extension, install


async def _storage_row(
    session: AsyncSession, project_id: uuid.UUID, extension_id: uuid.UUID, key: str
) -> ExtensionStorage:
    row = await svc.get_storage_row(session, project_id, extension_id, key)
    if row is None:
        raise APIError(404, "not_found", "No such storage key")
    return row


@router.get("/extensions/{slug}/storage/{key}", response_model=None)
async def get_storage(
    slug: SlugPath,
    key: KeyPath,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any] | Response:
    # Phase 4 L3: reads ride a per-USER window (writes stay per-install, §12).
    if limited := _rate_limited(
        request,
        _STORAGE_READ_LIMITER,
        str(ctx.user.id),
        settings.extension_storage_reads_per_minute_per_user,
    ):
        return limited
    extension, _ = await _storage_install(session, ctx, slug, "storage.get")
    row = await _storage_row(session, ctx.project.id, extension.id, key)
    return envelope(serialize_storage_value(row).payload())


async def _read_storage_value(request: Request) -> tuple[Any, int]:
    """The raw JSON body (any type) and its canonical size — 413 over 64 KiB,
    422 when not JSON."""
    raw = await request.body()
    if len(raw) > _STORAGE_RAW_CEILING:
        raise APIError(413, "payload_too_large", "Storage value exceeds 64 KiB")
    try:
        value = json.loads(raw)
    except ValueError:
        raise APIError(422, "validation_error", "Body must be a JSON value") from None
    size = encoded_size(value)
    if size > svc.STORAGE_VALUE_MAX_BYTES:
        raise APIError(413, "payload_too_large", "Storage value exceeds 64 KiB")
    return value, size


@router.put("/extensions/{slug}/storage/{key}", response_model=None)
async def put_storage(
    slug: SlugPath,
    key: KeyPath,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    require_role(ctx, Role.MEMBER)
    value, size = await _read_storage_value(request)
    # Row lock on the install (schema §4.6): the quota check and the write are one unit.
    extension, install = await _storage_install(session, ctx, slug, "storage.put", for_update=True)
    if limited := _storage_budget(request, install, settings):
        return limited
    used = await svc.storage_used_bytes(session, ctx.project.id, extension.id, excluding_key=key)
    if used + size > svc.STORAGE_TOTAL_MAX_BYTES:
        raise APIError(
            413,
            "storage_quota_exceeded",
            "This extension's storage for the project would exceed 256 KiB",
            details=[{"used_bytes": used + size, "limit_bytes": svc.STORAGE_TOTAL_MAX_BYTES}],
        )
    row = await svc.get_storage_row(session, ctx.project.id, extension.id, key)
    created = row is None
    if row is None:
        row = ExtensionStorage(
            project_id=ctx.project.id,
            extension_id=extension.id,
            key=key,
            value=value,
            size_bytes=size,
        )
        session.add(row)
    else:
        row.value = value
        row.size_bytes = size
    await session.commit()
    return _json(201 if created else 200, serialize_storage_value(row).payload())


@router.delete("/extensions/{slug}/storage/{key}", status_code=204, response_model=None)
async def delete_storage(
    slug: SlugPath,
    key: KeyPath,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    require_role(ctx, Role.MEMBER)
    extension, install = await _storage_install(session, ctx, slug, "storage.delete")
    if limited := _storage_budget(request, install, settings):
        return limited
    row = await _storage_row(session, ctx.project.id, extension.id, key)
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


# -------------------------------------------------------- §8 widget layout
@router.get("/widget-layout")
async def get_widget_layout(ctx: ProjectCtx, session: SessionDep) -> dict[str, Any]:
    layout = await svc.get_layout(session, ctx.project.id, ctx.user.id)
    return envelope(_layout_out(ctx.project.id, layout).payload())


@router.put("/widget-layout", response_model=None)
async def put_widget_layout(
    body: LayoutBody,
    request: Request,
    ctx: ProjectCtx,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any] | Response:
    require_role(ctx, Role.MEMBER)
    if limited := _install_budget(request, ctx, settings):
        return limited
    slots = [slot.model_dump() for slot in body.layout]
    layout = await svc.get_layout(session, ctx.project.id, ctx.user.id)
    if layout is None:
        layout = WidgetLayout(project_id=ctx.project.id, user_id=ctx.user.id, layout=slots)
        session.add(layout)
    else:
        layout.layout = slots
    await session.commit()  # §8: no data event — per-user display state only
    return envelope(_layout_out(ctx.project.id, layout).payload())
