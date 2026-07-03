"""Connector registry — maps a provider id to its connector (CLAUDE.md §2.1).

The runtime resolves connectors only through here, never by importing a
concrete class, so the roster (GitLab, KiCad, Onshape, ROS) plugs in by
registration. The catalog feeds `GET /api/v1/integrations` (API.md §2.5).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from solus_api.connectors.contracts import Connector

if TYPE_CHECKING:
    from solus_api.core.config import Settings

ConnectorFactory = Callable[[], Connector]


class UnknownConnectorError(KeyError):
    """No connector registered for the given provider id."""


class ConnectorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}

    def register(self, provider: str, factory: ConnectorFactory) -> None:
        self._factories[provider] = factory

    def create(self, provider: str) -> Connector:
        try:
            factory = self._factories[provider]
        except KeyError as exc:
            raise UnknownConnectorError(provider) from exc
        return factory()

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
                }
            )
        return items


def build_registry(settings: Settings) -> ConnectorRegistry:
    """The default registry. GitHub ships first (SOLUSDEV-103); the rest of the
    roster registers here as each connector lands."""
    from solus_api.connectors.github import GitHubConnector

    registry = ConnectorRegistry()
    registry.register(
        "github",
        lambda: GitHubConnector(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
        ),
    )
    return registry
