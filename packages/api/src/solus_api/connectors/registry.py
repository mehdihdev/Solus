"""Connector registry — maps a provider id to its connector (CLAUDE.md §2.1).

The runtime resolves connectors only through here, never by importing a
concrete class, so the roster (GitLab, KiCad, Onshape, ROS) plugs in by
registration. The catalog feeds `GET /api/v1/integrations` (API.md §2.5).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from solus_api.connectors import quota
from solus_api.connectors.acquisition import ExportAcquirer
from solus_api.connectors.contracts import Connector
from solus_api.connectors.httpcache import CacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.local_folder import FolderAcquirer

if TYPE_CHECKING:
    from solus_api.core.config import Settings

#: Who is asking for a scoped connector. Decides how much a recorded change
#: signal may be trusted (SOLUSDEV-241) and whether the caller may spend in the
#: degraded quota band (SOLUSDEV-167): a human's explicit action ("user") reads
#: the cache and may spend; the sweep ("scheduled") refreshes the signal and
#: defers; a doorbell ("webhook") never trusts a recorded signal.
Purpose = Literal["user", "scheduled", "webhook"]

ConnectorFactory = Callable[[], Connector]


@dataclass(frozen=True)
class ConnectorContext:
    """Per-sync-run scoping for a SCOPED factory (SOLUSDEV-100 T4b): the
    (project, team, acting-user) triple a live-acquisition-capable connector
    (the EDA family's bridge export acquirer) needs. `acting_user_id` is the
    F3-resolved acting user for THIS run — `None` when neither the manual
    requester nor `source.created_by` resolved to one, in which case live
    acquisition is skipped (the acquirer itself declines cleanly)."""

    #: SOLUSDEV-241: both optional — an ACCOUNT-scoped call (Home listing an
    #: account's documents) has no project. Every project-scoped construction
    #: site still passes both.
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    acting_user_id: uuid.UUID | None = None
    # SOLUSDEV-167 quota accounting. All defaulted, so every existing
    # construction site is unchanged.
    #: The provider ACCOUNT the calls are charged to. Falls back to the source id
    #: when absent — `Source.account_external_id` is nullable and Onshape's
    #: read-only scope can yield "", and every such source sharing ONE ledger key
    #: would let one team latch another team's 402.
    account_ref: str | None = None
    #: Who is spending. Only "user" survives the degraded band; scheduled sweeps
    #: and agent turns can wait.
    purpose: Purpose = "user"


ScopedConnectorFactory = Callable[[ConnectorContext], Connector]


class UnknownConnectorError(KeyError):
    """No connector registered for the given provider id."""


class ConnectorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}
        # Additive: a provider MAY also carry a scoped factory (T4b, EDA live
        # acquisition). `create`/`catalog`/`providers` are entirely unchanged
        # for providers that only ever register a plain factory.
        self._scoped_factories: dict[str, ScopedConnectorFactory] = {}

    def register(self, provider: str, factory: ConnectorFactory) -> None:
        self._factories[provider] = factory

    def register_scoped(self, provider: str, factory: ScopedConnectorFactory) -> None:
        """Register a factory that additionally needs `ConnectorContext`
        scope. A provider may carry BOTH a plain and a scoped factory —
        `create_scoped` prefers the scoped one; `create` always uses the
        plain one, unaffected by this registration."""
        self._scoped_factories[provider] = factory

    def create(self, provider: str) -> Connector:
        try:
            factory = self._factories[provider]
        except KeyError as exc:
            raise UnknownConnectorError(provider) from exc
        return factory()

    def create_scoped(self, provider: str, ctx: ConnectorContext) -> Connector:
        """Like `create`, but gives a scoped factory (if one is registered
        for this provider) the (project, team, acting-user) triple it needs.
        Providers without a scoped factory fall back to `create` unchanged —
        this is what makes the ARQ worker process (no bridge registry, so it
        never registers scoped factories) degrade to plain construction."""
        scoped = self._scoped_factories.get(provider)
        if scoped is not None:
            return scoped(ctx)
        return self.create(provider)

    def providers(self) -> list[str]:
        return sorted(self._factories)

    def catalog(self) -> list[dict[str, Any]]:
        """Available connector types + their required config/auth shape."""
        items: list[dict[str, Any]] = []
        for provider in self.providers():
            connector = self._factories[provider]()
            items.append(
                {
                    "type": provider,
                    "auth_kind": connector.auth_kind.value,
                    "config_fields": list(connector.config_fields),
                    "scopes": list(getattr(connector, "scopes", ())),
                    # How the app lets a user choose WHAT to track after
                    # connecting (repos, documents, …), or None when there is
                    # nothing to choose. Read generically by the frontend, so a
                    # new connector needs no frontend change to become pickable.
                    "selection": getattr(connector, "selection", None),
                    # How much power the user grants at CONNECT time (read vs
                    # read+write), or None when the provider offers no choice.
                    # Same generic treatment as `selection` (SOLUS-ONS-A2).
                    "access_modes": getattr(connector, "access_modes", None),
                }
            )
        return items


#: Builds a `BridgeExportAcquirer` (or equivalent) for one EDA provider's
#: allowlisted export tool, given the run's scope. `None` (the ARQ worker
#: process, which has no bridge session registry) means the EDA family's
#: scoped factories are never registered here — every `create_scoped` call
#: for "kicad"/"altium" then falls back to the plain, acquirer-less factory
#: (T4b F2 wiring).
AcquirerFactory = Callable[[ConnectorContext, str], ExportAcquirer]

#: Builds the local-folder acquirer (`connectors/local_acquire.py`) for one sync
#: run's scope (SOLUSDEV-249). Same rule as `AcquirerFactory`: `None` where
#: there is no bridge registry (the ARQ worker) — the plain, acquirer-less
#: `local` connector then declines every sync with a no-signal error.
LocalAcquirerFactory = Callable[[ConnectorContext], FolderAcquirer]


def _onshape_meter(
    settings: Settings, redis: object | None, ctx: ConnectorContext
) -> quota.CallMeter:
    """One meter per scoped construction, bound to the account being charged.

    The year comes from the wall clock and the key embeds it, so the ledger rolls
    over on 1 January. Onshape's licence year is the subscription anniversary,
    which we do not know — documented in ADR-019's amendment rather than guessed.
    """
    return quota.CallMeter(
        redis,
        provider="onshape",
        # Never empty: a blank account id would put every such source on ONE
        # ledger key, letting one team exhaust and latch another team's quota.
        account_ref=ctx.account_ref or f"source-scope:{ctx.project_id}",
        year=datetime.now(UTC).year,
        allowance=settings.onshape_annual_call_allowance,
        degrade_ratio=settings.integration_degrade_ratio,
        # Anything but a human's explicit action is deferrable: a sweep or a
        # doorbell must not inherit the privilege to spend past the threshold.
        purpose="user" if ctx.purpose == "user" else "scheduled",
    )


def build_integration_cache(settings: Settings, store: CacheStore) -> IntegrationCache:
    """The read side of the change-signal spine (SOLUSDEV-241), over whichever
    store the app assembled — Redis when configured, per-process otherwise."""
    return IntegrationCache(
        store,
        listing_ttl_seconds=settings.integration_listing_ttl_seconds,
        signal_ttl_seconds=settings.integration_signal_ttl_seconds,
        payload_ttl_seconds=settings.integration_payload_ttl_seconds,
        max_payload_bytes=settings.integration_cache_max_payload_bytes,
        listing_refresh_cooldown_seconds=settings.integration_listing_refresh_cooldown_seconds,
    )


def _signal_window(settings: Settings, purpose: str) -> float | None:
    """How old a recorded change signal may be and still be believed.

    A human's sync trusts it for the sweep interval — the sweep is what moves
    it. The sweep reuses one only a few minutes old, so two projects tracking
    one document cost one probe per sweep rather than two. A doorbell means
    "it changed": never trust, always ask.
    """
    if purpose == "user":
        return float(settings.integration_signal_ttl_seconds)
    if purpose == "scheduled":
        return float(settings.integration_signal_sweep_reuse_seconds)
    return None


def _cache_account_ref(ctx: ConnectorContext) -> str | None:
    """The identity the connector caches under — or None, in which case the
    connector caches NOTHING. `execute_source_sync` and the routes pass
    `services.connections.account_ref_for`, which never yields an empty ref; a
    construction site that passes none must not be handed a project-shaped
    fallback (that is the METER's rule, where a shared ledger is the failure
    mode), because "source-scope:None" would be one bucket for every
    unidentified account across every tenant."""
    return ctx.account_ref or None


def _gitlab_host(base_url: str | None) -> str | None:
    """The self-hosted GitLab host a clone's remote may name (SOLUSDEV-249)."""
    if not base_url:
        return None
    from urllib.parse import urlsplit

    return urlsplit(base_url).hostname


def build_registry(
    settings: Settings,
    *,
    acquirer_factory: AcquirerFactory | None = None,
    local_acquirer_factory: LocalAcquirerFactory | None = None,
    redis: object | None = None,
    cache: IntegrationCache | None = None,
) -> ConnectorRegistry:
    """The default registry. Code hosts shipped (SOLUSDEV-103/104); the rest of
    the roster (KiCad, Onshape, ROS) registers here as each connector lands."""
    from solus_api.connectors.altium import AltiumConnector
    from solus_api.connectors.github import GitHubConnector
    from solus_api.connectors.gitlab import GitLabConnector
    from solus_api.connectors.kicad import KicadConnector
    from solus_api.connectors.local_folder import LocalFolderConnector
    from solus_api.connectors.onshape import OnshapeConnector

    registry = ConnectorRegistry()
    registry.register(
        "github",
        lambda: GitHubConnector(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
        ),
    )
    registry.register(
        "gitlab",
        lambda: GitLabConnector(
            client_id=settings.gitlab_client_id,
            client_secret=settings.gitlab_client_secret,
            base_url=settings.gitlab_base_url,
        ),
    )
    # Altium (SOLUSDEV-102) — committed-export EDA connector, parse-export scaffold.
    registry.register("altium", AltiumConnector)
    # KiCad (SOLUSDEV-100) — committed-export EDA connector, XML netlist parse.
    registry.register("kicad", KicadConnector)
    # Onshape (SOLUSDEV-96 / CAD-01) — thin-API mechanical CAD: OAuth, detect
    # change on the microversion, fetch a STEP export, then the SHARED parser.
    registry.register(
        "onshape",
        lambda: OnshapeConnector(
            client_id=settings.onshape_client_id or "",
            client_secret=settings.onshape_client_secret or "",
        ),
    )
    # SOLUSDEV-167: a SCOPED Onshape factory, so outbound calls are counted
    # against the provider account that owns the allowance. Before this, only
    # kicad and altium had scoped factories, so `create_scoped("onshape", ctx)`
    # silently fell back to `create()` and the context was discarded — which is
    # why nothing could attribute a call to a tenant.
    # SOLUSDEV-241: the same scoped construction hands the connector the
    # integration cache, keyed on the account being charged, and the trust
    # window its purpose earns.
    registry.register_scoped(
        "onshape",
        lambda ctx: OnshapeConnector(
            client_id=settings.onshape_client_id or "",
            client_secret=settings.onshape_client_secret or "",
            meter=_onshape_meter(settings, redis, ctx),
            cache=cache,
            account_ref=_cache_account_ref(ctx),
            signal_max_age_seconds=_signal_window(settings, ctx.purpose),
        ),
    )
    # Local folders (SOLUSDEV-249): a working copy on one machine, scanned over
    # the bridge. The plain factory is what the catalog and the ARQ worker see;
    # only the API process (a bridge registry) gets the scoped, acquiring one.
    gitlab_host = _gitlab_host(settings.gitlab_base_url)
    registry.register("local", lambda: LocalFolderConnector(gitlab_host=gitlab_host))
    if local_acquirer_factory is not None:
        registry.register_scoped(
            "local",
            lambda ctx: LocalFolderConnector(
                acquirer=local_acquirer_factory(ctx), gitlab_host=gitlab_host
            ),
        )
    if acquirer_factory is not None:
        # T4b (MCP-04): the EDA family's live bridge acquisition. Only
        # registered when the caller (the API process, via main.py) actually
        # has a bridge session registry to acquire through.
        registry.register_scoped(
            "kicad",
            lambda ctx: KicadConnector(acquirer=acquirer_factory(ctx, "kicad.export_netlist")),
        )
        registry.register_scoped(
            "altium",
            lambda ctx: AltiumConnector(acquirer=acquirer_factory(ctx, "altium.export_netlist")),
        )
    return registry
