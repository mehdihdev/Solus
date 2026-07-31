"""Connectors — the canonical connector interface (W0-05, ratified by Decision B).

`solus_api.connectors` is the single import surface for connector development: the
`Connector`/`OAuthConnector` ABCs and their normalized `EntityOut`/`RelationOut`/`SyncResult`
output shapes, the per-sync `SyncContext`, resolved `Credentials`/`AccountInfo`, the
`SecretStore` credential seam, and the package-importable `assert_connector_contract`
conformance suite. Every connector (GitHub, GitLab, and future KiCad/Onshape/ROS) implements
`Connector`, sources credentials through the secret store, and its own test runs
`assert_connector_contract`.

The shipped framework shape won the SOLUSDEV-72 reconciliation (Decision B): flat, stateless
connectors driven by the ARQ runtime, with `detect_changes(ctx) -> bool` + a JSON `cursor`
(the `Delta`/incremental path is a documented forward extension, not built yet). The interface
is human-owned and mirrored to `packages/contracts/python/` (CLAUDE.md §9, ADR-028); this
module re-exports it so every implementation imports the one canonical shape.
"""

# The LiveConnection sibling (MCP-02) is deliberately NOT re-exported here: `live.py`
# imports the W0-07 shapes from `solus_api.agent.interfaces`, whose own import chain
# reaches this package — an eager re-export closes that cycle and breaks a bare
# `import solus_api.agent.runtime`. Import `solus_api.connectors.live` /
# `solus_api.connectors.live_conformance` directly (same pattern as agent.tools.mcp_tool).
from solus_api.connectors.conformance import assert_connector_contract
from solus_api.connectors.contracts import (
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
from solus_api.connectors.secrets import (
    SecretNotFoundError,
    SecretStore,
    build_secret_store,
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
    "SecretNotFoundError",
    "SecretStore",
    "SyncContext",
    "SyncError",
    "SyncResult",
    "assert_connector_contract",
    "build_secret_store",
]
