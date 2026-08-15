"""Connector registry — maps a provider id to its connector (CLAUDE.md §2.1).

The runtime resolves connectors only through here, never by importing a
concrete class, so the roster (GitLab, KiCad, Onshape, ROS) plugs in by
registration. The catalog feeds `GET /api/v1/integrations` (API.md §2.5).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from solus_api.connectors.acquisition import ExportAcquirer
from solus_api.connectors.contracts import Connector

if TYPE_CHECKING:
    from solus_api.core.config import Settings

ConnectorFactory = Callable[[], Connector]


@dataclass(frozen=True)
class ConnectorContext:
    """Per-sync-run scoping for a SCOPED factory (SOLUSDEV-100 T4b): the
    (project, team, acting-user) triple a live-acquisition-capable connector
    (the EDA family's bridge export acquirer) needs. `acting_user_id` is the
    F3-resolved acting user for THIS run — `None` when neither the manual
    requester nor `source.created_by` resolved to one, in which case live
    acquisition is skipped (the acquirer itself declines cleanly)."""

    project_id: uuid.UUID
    team_id: uuid.UUID
    acting_user_id: uuid.UUID | None = None


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


def build_registry(
    settings: Settings,
    *,
    acquirer_factory: AcquirerFactory | None = None,
) -> ConnectorRegistry:
    """The default registry. Code hosts shipped (SOLUSDEV-103/104); the rest of
    the roster (KiCad, Onshape, ROS) registers here as each connector lands."""
    from solus_api.connectors.altium import AltiumConnector
    from solus_api.connectors.github import GitHubConnector
    from solus_api.connectors.gitlab import GitLabConnector
    from solus_api.connectors.kicad import KicadConnector
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
