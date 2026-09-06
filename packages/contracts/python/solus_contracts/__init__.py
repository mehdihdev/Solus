"""Solus interface contracts (human-owned, ADR-028) — the connector interface (W0-05).

Ratified by SOLUSDEV-72 Decision B. Re-exports the canonical connector shape so
implementations import from one place: `from solus_contracts import Connector, EntityOut, ...`.

SOLUSDEV-166 (ADR-034) adds the machine-local ~/.solus state shapes
(`local_state`), ratified in-session at the SOLUSDEV-166 MR.

SOLUSDEV-235 (ADR-035) adds the ``extension.toml`` manifest shape
(`extension_manifest`), ratified in-session at the Store backend design review.
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
from solus_contracts.extension_manifest import (
    EXTENSION_ID_PATTERN,
    EXTENSION_MANIFEST_FILENAME,
    EXTENSION_MANIFEST_SCHEMA_VERSION,
    FIRST_PARTY_TABLES,
    LIMITS,
    PERMISSION_SCOPES,
    SUPPORTED_SCHEMA_VERSIONS,
    ExtensionManifest,
    composed_tool_name,
    declares_first_party,
    graph_kind_name,
    is_safe_bundle_path,
    is_safe_extension_id,
    manifest_document,
    manifest_problems,
    parse_extension_manifest,
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
    "EXTENSION_ID_PATTERN",
    "EXTENSION_MANIFEST_FILENAME",
    "EXTENSION_MANIFEST_SCHEMA_VERSION",
    "FIRST_PARTY_TABLES",
    "LIMITS",
    "PERMISSION_SCOPES",
    "SUPPORTED_SCHEMA_VERSIONS",
    "ExtensionManifest",
    "composed_tool_name",
    "declares_first_party",
    "graph_kind_name",
    "is_safe_bundle_path",
    "manifest_document",
    "is_safe_extension_id",
    "manifest_problems",
    "parse_extension_manifest",
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
