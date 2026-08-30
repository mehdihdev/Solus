"""Solus interface contracts (human-owned, ADR-028) — the connector interface (W0-05).

Ratified by SOLUSDEV-72 Decision B. Re-exports the canonical connector shape so
implementations import from one place: `from solus_contracts import Connector, EntityOut, ...`.

SOLUSDEV-166 (ADR-034) adds the machine-local ~/.solus state shapes
(`local_state`), ratified in-session at the SOLUSDEV-166 MR.
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
from solus_contracts.local_state import (
    PROJECT_ID_PATTERN,
    PROJECT_REGISTRY_SCHEMA_VERSION,
    PROJECTS_FILENAME,
    SOLUS_HOME_DIRNAME,
    SOLUS_HOME_MODE,
    ProjectFolderLink,
    ProjectRegistry,
)

__all__ = [
    "PROJECT_ID_PATTERN",
    "PROJECT_REGISTRY_SCHEMA_VERSION",
    "PROJECTS_FILENAME",
    "SOLUS_HOME_DIRNAME",
    "SOLUS_HOME_MODE",
    "AccountInfo",
    "AuthKind",
    "Connector",
    "ConnectorError",
    "Credentials",
    "EntityOut",
    "OAuthConnector",
    "ProjectFolderLink",
    "ProjectRegistry",
    "RelationOut",
    "SyncContext",
    "SyncError",
    "SyncResult",
]
