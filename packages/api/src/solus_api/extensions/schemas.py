"""Response shapes of the extensions surface (SOLUSDEV-235 / ADR-035, EXT-03).

Every shape `docs/api/extensions.md` RETURNS, as frozen Pydantic v2 models, plus
the serializers that build them from ORM rows. Field names are the route plan's,
verbatim. Request bodies are NOT here — each router owns its own.

Conventions (route plan §3): every URL is a relative API route, never a storage
locator; the catalog shapes disclose no tenant; `review_problems` appears only
in the publisher's view of a rejected version.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from solus_api.models import (
    Extension,
    ExtensionInstall,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionStorage,
    ExtensionVersion,
    TeamExtensionPolicy,
    WidgetLayout,
)

API_PREFIX = "/api/v1/extensions"
#: Canonical `[views]` key order for `CatalogItem.views`.
VIEW_KINDS = ("widget", "page", "window")


def bundle_url(slug: str, version: str) -> str:
    return f"{API_PREFIX}/{slug}/versions/{version}/bundle"


def review_url(slug: str, version: str) -> str:
    return f"{API_PREFIX}/{slug}/versions/{version}/review"


def asset_url(slug: str, version: str, path: str) -> str:
    return f"{API_PREFIX}/{slug}/versions/{version}/assets/{path}"


# ------------------------------------------------------------ manifest reads
def manifest_requires(manifest: dict[str, Any]) -> list[list[str]]:
    requires = manifest.get("extension", {}).get("requires", [])
    return [list(group) for group in requires]


def manifest_views(manifest: dict[str, Any]) -> list[str]:
    declared = manifest.get("views", {})
    return [kind for kind in VIEW_KINDS if kind in declared]


def manifest_permissions(manifest: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Declared `(scopes, network)` of a manifest, as sets."""
    permissions = manifest.get("permissions", {})
    return set(permissions.get("scopes", [])), set(permissions.get("network", []))


# ------------------------------------------------------------------ models
class ResponseModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    def payload(self) -> dict[str, Any]:
        """JSON-ready dict for the `data` envelope."""
        return self.model_dump(mode="json")


class PublisherOut(ResponseModel):
    display_name: str


class LatestVersionOut(ResponseModel):
    version: str
    published_at: datetime | None


class CatalogItem(ResponseModel):
    """§4.1 list item."""

    slug: str
    name: str
    summary: str
    publisher: PublisherOut
    verified: bool
    install_count: int
    latest_version: LatestVersionOut
    requires: list[list[str]]
    views: list[str]
    updated_at: datetime


class VersionDetail(ResponseModel):
    """§4.2 `version`."""

    version: str
    published_at: datetime | None
    content_hash: str
    bundle_size_bytes: int
    bundle_url: str


class AssetSection(ResponseModel):
    title: str
    url: str


class ExtensionAssets(ResponseModel):
    """§4.2 `assets` — only URLs whose path is recorded in extension_version_assets."""

    overview: str | None
    privacy_policy: str | None
    icon: str | None
    screenshots: list[str]
    sections: list[AssetSection]


class ExtensionDetail(ResponseModel):
    """§4.2 detail (also the §5.4 PATCH response). `version`/`manifest`/`assets`
    are null only in the publisher's own view of a not-yet-approved listing."""

    slug: str
    name: str
    summary: str
    publisher: PublisherOut
    verified: bool
    install_count: int
    version: VersionDetail | None
    manifest: dict[str, Any] | None
    assets: ExtensionAssets | None
    created_at: datetime
    updated_at: datetime


class VersionSummary(ResponseModel):
    """§4.3 list item. `review_problems` is present only for the publisher AND
    only when rejected — `payload()` drops the key otherwise."""

    version: str
    review_status: ExtensionReviewStatus
    review_problems: list[str] | None = None
    published_at: datetime | None
    content_hash: str
    bundle_size_bytes: int
    created_at: datetime

    def payload(self) -> dict[str, Any]:
        exclude = {"review_problems"} if self.review_problems is None else None
        return self.model_dump(mode="json", exclude=exclude)


class ReviewStatusOut(ResponseModel):
    """§5.2. `review_problems` is `[]` for pending | checking | approved."""

    slug: str
    version: str
    review_status: ExtensionReviewStatus
    review_problems: list[str]
    checked_at: datetime | None
    published_at: datetime | None


class PublishedVersion(ResponseModel):
    """§5.1 `version` inside the 202 body."""

    slug: str
    version: str
    review_status: ExtensionReviewStatus
    content_hash: str
    bundle_size_bytes: int
    bundle_url: str
    review_url: str
    created_at: datetime


class InstallExtensionOut(ResponseModel):
    slug: str
    name: str
    verified: bool
    publisher: PublisherOut


class InstallVersionOut(ResponseModel):
    """The PINNED version — the desktop validates settings against what is installed."""

    version: str
    content_hash: str
    bundle_size_bytes: int
    bundle_url: str
    manifest: dict[str, Any]


class UpdateAvailable(ResponseModel):
    version: str
    widens_permissions: bool


class PolicyState(ResponseModel):
    blocked: bool
    default_installed: bool


NO_POLICY = PolicyState(blocked=False, default_installed=False)


class InstallRow(ResponseModel):
    """§6.1 item. A team-blocked extension is reported `enabled: false`."""

    extension: InstallExtensionOut
    version: InstallVersionOut
    enabled: bool
    settings: dict[str, Any]
    granted_scopes: list[str]
    granted_network: list[str]
    update_available: UpdateAvailable | None
    policy: PolicyState
    installed_by: UUID | None
    installed_at: datetime
    updated_at: datetime


class StorageValue(ResponseModel):
    """§7 GET/PUT body. `value` is opaque — any JSON."""

    key: str
    value: Any
    size_bytes: int
    updated_at: datetime


class PolicyExtensionOut(ResponseModel):
    slug: str
    name: str
    verified: bool


class PolicyRow(ResponseModel):
    """§10 item."""

    extension: PolicyExtensionOut
    blocked: bool
    default_installed: bool
    default_settings: dict[str, Any]
    updated_by: UUID | None
    updated_at: datetime


class LayoutSlot(ResponseModel):
    ref: str
    size: str


class WidgetLayoutOut(ResponseModel):
    """§8. The empty default is `layout: [], updated_at: null`."""

    project_id: UUID
    layout: list[LayoutSlot]
    updated_at: datetime | None


# ------------------------------------------------------------- serializers
def _publisher(publisher: ExtensionPublisher) -> PublisherOut:
    return PublisherOut(display_name=publisher.display_name)


def _version_detail(extension: Extension, version: ExtensionVersion) -> VersionDetail:
    return VersionDetail(
        version=version.version,
        published_at=version.published_at,
        content_hash=version.content_hash,
        bundle_size_bytes=version.bundle_size_bytes,
        bundle_url=bundle_url(extension.slug, version.version),
    )


def _recorded(slug: str, semver: str, path: str | None, recorded: set[str]) -> str | None:
    return asset_url(slug, semver, path) if path and path in recorded else None


def _assets(
    extension: Extension, version: ExtensionVersion, paths: Iterable[str]
) -> ExtensionAssets:
    recorded = set(paths)
    slug, semver = extension.slug, version.version
    store = version.manifest.get("store", {})
    icon = version.manifest.get("views", {}).get("page", {}).get("icon")
    screenshots = [
        url for p in store.get("screenshots", []) if (url := _recorded(slug, semver, p, recorded))
    ]
    sections = [
        AssetSection(title=section["title"], url=url)
        for section in store.get("sections", [])
        if (url := _recorded(slug, semver, section.get("body"), recorded))
    ]
    return ExtensionAssets(
        overview=_recorded(slug, semver, store.get("overview"), recorded),
        privacy_policy=_recorded(slug, semver, store.get("privacy_policy"), recorded),
        icon=_recorded(slug, semver, icon, recorded),
        screenshots=screenshots,
        sections=sections,
    )


def serialize_catalog_item(
    extension: Extension, publisher: ExtensionPublisher, latest: ExtensionVersion
) -> CatalogItem:
    """§4.1 — `latest` is the extension's latest approved version (never None here:
    the list shows only extensions that have one)."""
    return CatalogItem(
        slug=extension.slug,
        name=extension.name,
        summary=extension.summary,
        publisher=_publisher(publisher),
        verified=extension.verified,
        install_count=extension.install_count,
        latest_version=LatestVersionOut(version=latest.version, published_at=latest.published_at),
        requires=manifest_requires(latest.manifest),
        views=manifest_views(latest.manifest),
        updated_at=extension.updated_at,
    )


def serialize_extension_detail(
    extension: Extension,
    publisher: ExtensionPublisher,
    latest: ExtensionVersion | None,
    asset_paths: Iterable[str] = (),
) -> ExtensionDetail:
    """§4.2 — `asset_paths` are the `extension_version_assets.path` values recorded
    for `latest`; only those become URLs. `latest is None` is the publisher's
    own view of an unreleased listing."""
    return ExtensionDetail(
        slug=extension.slug,
        name=extension.name,
        summary=extension.summary,
        publisher=_publisher(publisher),
        verified=extension.verified,
        install_count=extension.install_count,
        version=_version_detail(extension, latest) if latest else None,
        manifest=latest.manifest if latest else None,
        assets=_assets(extension, latest, asset_paths) if latest else None,
        created_at=extension.created_at,
        updated_at=extension.updated_at,
    )


def serialize_version_summary(version: ExtensionVersion, *, as_publisher: bool) -> VersionSummary:
    """§4.3 — problems are disclosed only to the publisher, only when rejected."""
    rejected = version.review_status == ExtensionReviewStatus.REJECTED
    return VersionSummary(
        version=version.version,
        review_status=version.review_status,
        review_problems=list(version.review_problems) if as_publisher and rejected else None,
        published_at=version.published_at,
        content_hash=version.content_hash,
        bundle_size_bytes=version.bundle_size_bytes,
        created_at=version.created_at,
    )


def serialize_review_status(extension: Extension, version: ExtensionVersion) -> ReviewStatusOut:
    """§5.2. `checked_at` has no backing column in docs/schemas/extensions.md §4.3
    (flagged in the EXT-03 completion report); it is null until one exists."""
    return ReviewStatusOut(
        slug=extension.slug,
        version=version.version,
        review_status=version.review_status,
        review_problems=list(version.review_problems),
        checked_at=None,
        published_at=version.published_at,
    )


def serialize_published_version(
    extension: Extension, version: ExtensionVersion
) -> PublishedVersion:
    """§5.1 — the `version` block of the 202 body."""
    return PublishedVersion(
        slug=extension.slug,
        version=version.version,
        review_status=version.review_status,
        content_hash=version.content_hash,
        bundle_size_bytes=version.bundle_size_bytes,
        bundle_url=bundle_url(extension.slug, version.version),
        review_url=review_url(extension.slug, version.version),
        created_at=version.created_at,
    )


def update_available(
    install: ExtensionInstall, pinned: ExtensionVersion, latest: ExtensionVersion | None
) -> UpdateAvailable | None:
    """§6.1 — null when the pin IS the latest approved; otherwise whether the
    latest version declares any scope / origin the current grants lack."""
    if latest is None or latest.id == pinned.id:
        return None
    scopes, network = manifest_permissions(latest.manifest)
    widens = not (scopes <= set(install.granted_scopes) and network <= set(install.granted_network))
    return UpdateAvailable(version=latest.version, widens_permissions=widens)


def serialize_install(
    install: ExtensionInstall,
    extension: Extension,
    publisher: ExtensionPublisher,
    pinned: ExtensionVersion,
    latest: ExtensionVersion | None,
    policy: TeamExtensionPolicy | None,
) -> InstallRow:
    """§6.1 item — the join of install, pinned version, latest approved version
    and the team policy. A team block wins over the stored `enabled` flag."""
    state = (
        PolicyState(blocked=policy.blocked, default_installed=policy.default_installed)
        if policy
        else NO_POLICY
    )
    return InstallRow(
        extension=InstallExtensionOut(
            slug=extension.slug,
            name=extension.name,
            verified=extension.verified,
            publisher=_publisher(publisher),
        ),
        version=InstallVersionOut(
            version=pinned.version,
            content_hash=pinned.content_hash,
            bundle_size_bytes=pinned.bundle_size_bytes,
            bundle_url=bundle_url(extension.slug, pinned.version),
            manifest=pinned.manifest,
        ),
        enabled=install.enabled and not state.blocked,
        settings=install.settings,
        granted_scopes=list(install.granted_scopes),
        granted_network=list(install.granted_network),
        update_available=update_available(install, pinned, latest),
        policy=state,
        installed_by=install.installed_by,
        installed_at=install.created_at,
        updated_at=install.updated_at,
    )


def serialize_storage_value(row: ExtensionStorage) -> StorageValue:
    return StorageValue(
        key=row.key, value=row.value, size_bytes=row.size_bytes, updated_at=row.updated_at
    )


def serialize_policy(policy: TeamExtensionPolicy, extension: Extension) -> PolicyRow:
    return PolicyRow(
        extension=PolicyExtensionOut(
            slug=extension.slug, name=extension.name, verified=extension.verified
        ),
        blocked=policy.blocked,
        default_installed=policy.default_installed,
        default_settings=policy.default_settings,
        updated_by=policy.set_by,
        updated_at=policy.updated_at,
    )


def serialize_widget_layout(project_id: UUID, layout: WidgetLayout | None) -> WidgetLayoutOut:
    """§8 — a user with no stored row receives the empty default."""
    slots = [
        LayoutSlot(ref=slot["ref"], size=slot["size"]) for slot in (layout.layout if layout else [])
    ]
    return WidgetLayoutOut(
        project_id=project_id, layout=slots, updated_at=layout.updated_at if layout else None
    )
