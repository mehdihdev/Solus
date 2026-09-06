"""Per-user extension pins — docs/api/extensions.md §6.5 (SOLUSDEV-246, STORE ST3).

`/api/v1/users/me/extension-pins`: the slugs whose tab the desktop rail shows in
EVERY project this user opens. A pin is account state (`CurrentUser`, never a
project context): it installs nothing, grants nothing and is invisible to
teammates. Writes take the install-write budget shared with every other
extension mutation (§12); the list hides pins whose catalog row was unpublished.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.core.responses import envelope
from solus_api.deps import CurrentUser, SessionDep, SettingsDep
from solus_api.extensions import installs as svc
from solus_api.extensions.ratelimit import (
    INSTALL_WRITE_MESSAGE,
    WRITE_WINDOW_SECONDS,
    install_write_exceeded,
)
from solus_api.extensions.schemas import manifest_views
from solus_api.extensions.slugs import SlugPath
from solus_api.models import (
    Extension,
    ExtensionPublisher,
    ExtensionVersion,
    User,
    UserExtensionPin,
)
from solus_api.services.events import emit_event

router = APIRouter(prefix="/api/v1/users/me/extension-pins")

#: A rail is finite; more pins than this is a configuration mistake, not a use case.
PINS_MAX_PER_USER = 32


def _page_view(manifest: dict[str, Any] | None) -> dict[str, str] | None:
    """`views.page` of the latest approved manifest — the label and icon the
    rail draws for a pinned tab in a project where the bundle is not installed.
    Read defensively: the stored manifest is contract-validated, but a stale
    row must never 500 the list."""
    views = manifest.get("views") if isinstance(manifest, dict) else None
    page = views.get("page") if isinstance(views, dict) else None
    if not isinstance(page, dict):
        return None
    label, icon = page.get("label"), page.get("icon")
    if not isinstance(label, str) or not isinstance(icon, str):
        return None
    return {"label": label, "icon": icon}


def _row(
    pin: UserExtensionPin,
    extension: Extension,
    publisher: ExtensionPublisher,
    latest: ExtensionVersion | None,
) -> dict[str, Any]:
    manifest = latest.manifest if latest is not None else None
    return {
        "slug": extension.slug,
        "name": extension.name,
        "verified": extension.verified,
        "publisher": {"display_name": publisher.display_name},
        "version": latest.version if latest is not None else None,
        "views": manifest_views(manifest) if isinstance(manifest, dict) else [],
        "page": _page_view(manifest),
        "pinned_at": pin.created_at.isoformat(),
    }


async def _pins_of(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(UserExtensionPin, Extension, ExtensionPublisher)
            .join(Extension, Extension.id == UserExtensionPin.extension_id)
            .join(ExtensionPublisher, ExtensionPublisher.id == Extension.publisher_id)
            .where(UserExtensionPin.user_id == user_id, Extension.deleted_at.is_(None))
            .order_by(UserExtensionPin.created_at.asc(), UserExtensionPin.id.asc())
        )
    ).all()
    items: list[dict[str, Any]] = []
    for pin, extension, publisher in rows:
        latest = await svc.latest_approved_version(session, extension)
        items.append(_row(pin, extension, publisher, latest))
    return items


async def _pin_of(
    session: AsyncSession, user_id: uuid.UUID, extension_id: uuid.UUID
) -> UserExtensionPin | None:
    pin: UserExtensionPin | None = await session.scalar(
        select(UserExtensionPin).where(
            UserExtensionPin.user_id == user_id, UserExtensionPin.extension_id == extension_id
        )
    )
    return pin


def _budget(request: Request, user: User, settings: Any) -> None:
    if install_write_exceeded(
        request.app.state, user.id, settings.extension_install_writes_per_minute_per_user
    ):
        raise APIError(
            429,
            "rate_limited",
            INSTALL_WRITE_MESSAGE,
            headers={"Retry-After": str(WRITE_WINDOW_SECONDS)},
        )


@router.get("")
async def list_pins(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    return envelope(await _pins_of(session, user.id))


@router.put("/{slug}", response_model=None)
async def pin_extension(
    slug: SlugPath,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Any:
    _budget(request, user, settings)
    extension = await svc.find_live_extension(session, slug)
    if extension is None:
        raise APIError(404, "not_found", "Extension not found")
    publisher = await session.get(ExtensionPublisher, extension.publisher_id)
    if publisher is None:  # RESTRICT FK — unreachable
        raise APIError(500, "internal_error", "Publisher is missing")
    latest = await svc.latest_approved_version(session, extension)

    existing = await _pin_of(session, user.id, extension.id)
    if existing is not None:
        return envelope(_row(existing, extension, publisher, latest))

    total = await session.scalar(
        select(func.count())
        .select_from(UserExtensionPin)
        .where(UserExtensionPin.user_id == user.id)
    )
    if int(total or 0) >= PINS_MAX_PER_USER:
        raise APIError(
            422, "validation_error", f"At most {PINS_MAX_PER_USER} extensions can be pinned"
        )
    pin = UserExtensionPin(user_id=user.id, extension_id=extension.id)
    session.add(pin)
    await session.flush()
    emit_event(session, user=user, event_type="extension.pinned", payload={"slug": extension.slug})
    await session.commit()
    await session.refresh(pin)
    return JSONResponse(status_code=201, content=envelope(_row(pin, extension, publisher, latest)))


@router.delete("/{slug}", status_code=204, response_model=None)
async def unpin_extension(
    slug: SlugPath,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    _budget(request, user, settings)
    # Unpublished extensions may still be unpinned — the row is the user's.
    extension = await session.scalar(
        select(Extension).where(func.lower(Extension.slug) == slug.lower())
    )
    if extension is None:
        raise APIError(404, "not_found", "Extension not found")
    pin = await _pin_of(session, user.id, extension.id)
    if pin is None:
        return  # idempotent: unpinning what is not pinned is a no-op, not an error
    await session.delete(pin)
    emit_event(
        session, user=user, event_type="extension.unpinned", payload={"slug": extension.slug}
    )
    await session.commit()


__all__ = ["PINS_MAX_PER_USER", "router"]
