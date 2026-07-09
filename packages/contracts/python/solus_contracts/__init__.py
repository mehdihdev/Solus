"""Solus interface contracts (human-owned, ADR-028) — the connector interface (W0-05).

Ratified by SOLUSDEV-72 Decision B. Re-exports the canonical connector shape so
implementations import from one place: `from solus_contracts import Connector, EntityOut, ...`.
"""

from solus_contracts.connector import (
    AccountInfo,
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    EntityOut,
    OAuthConnector,
    RelationOut,
    SyncContext,
    SyncError,
    SyncResult,
)

__all__ = [
    "AccountInfo",
    "AuthKind",
    "Connector",
    "ConnectorError",
    "Credentials",
    "EntityOut",
    "OAuthConnector",
    "RelationOut",
    "SyncContext",
    "SyncError",
    "SyncResult",
]
