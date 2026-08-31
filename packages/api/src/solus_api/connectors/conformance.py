"""The reusable connector conformance suite (W0-05 §10).

Package-importable — every `Connector`'s own test imports `assert_connector_contract`
and runs it (CLAUDE.md §6: "every connector passes the connector contract suite"), so the
invariants are checked identically across the roster (GitHub, GitLab, KiCad, Onshape, ROS).
It asserts the contract's invariants and raises `AssertionError` on the first violation.
Asserts are the tool here on purpose (this IS a test helper); `S101` is ignored repo-wide.

It also guards the credential boundary: `SyncContext.config` is a free dict, so a token
accidentally placed there would be persisted plaintext. Credentials must arrive resolved as
`Credentials` from the secret store, never through config (CLAUDE.md §7) — the suite scans
config keys for anything that looks like a secret.
"""

from __future__ import annotations

import json
from typing import Any

from solus_api.connectors.contracts import (
    AccountInfo,
    Connector,
    SyncContext,
    SyncResult,
)

# Substrings marking a config key as a plaintext credential. Matched case-insensitively as
# SUBSTRINGS (not exact names) so `client_secret`/`private_key`/an `access_key` are caught, not
# just literal `token`. Deliberately conservative at the credential boundary (CLAUDE.md §7).
_CRED_SUBSTRINGS = (
    "password",
    "passwd",
    "passphrase",
    "token",
    "api_key",
    "apikey",
    "secret",
    "credential",
    "access_key",
    "private_key",
    "bearer",
    "ssh_key",
)


def _looks_like_credential(name: str) -> bool:
    normalized = name.lower().replace("-", "_")
    return any(sub in normalized for sub in _CRED_SUBSTRINGS)


def _assert_credential_hygiene(config: dict[str, Any]) -> None:
    # `config` is the free per-sync dict on SyncContext. Credentials must NOT ride here —
    # they arrive resolved as `Credentials` from the secret store (CLAUDE.md §7).
    # ponytail: one-level key scan; recurse if a connector ever nests credential-bearing dicts.
    suspicious = {k for k in config if _looks_like_credential(k)}
    assert not suspicious, (
        f"credentials must come from the secret store, not plaintext config keys {suspicious}"
    )


async def assert_connector_contract(connector: Connector, ctx: SyncContext) -> SyncResult:
    """Run the full contract suite against `connector` using `ctx`. Raises `AssertionError`
    on the first violated invariant; returns the `SyncResult` on success.

    Built on `assert`, so it MUST run with assertions enabled — never under `python -O` /
    PYTHONOPTIMIZE, which strips asserts and would turn every check into a silent no-op (a false
    "conforms"). The guard below fails loudly instead.
    """
    if not __debug__:
        raise RuntimeError("assert_connector_contract requires assertions enabled (not under -O)")

    _assert_credential_hygiene(ctx.config)

    account = await connector.validate_credentials(ctx.credentials)
    assert isinstance(account, AccountInfo), "validate_credentials() must return an AccountInfo"
    assert account.login, "AccountInfo.login must be non-empty"

    result = await connector.sync(ctx)
    assert isinstance(result, SyncResult), "sync() must return a SyncResult"

    keys = [entity.source_key for entity in result.entities]
    assert len(keys) == len(set(keys)), "entity source_keys must be unique within a sync"
    key_set = set(keys)
    for relation in result.relations:
        # Connectors emit ONLY intra-source relations — both ends must be entities this
        # connector produced (keeps connectors parallelizable and the graph sound).
        assert relation.from_key in key_set, f"relation from unknown key: {relation.from_key}"
        assert relation.to_key in key_set, f"relation to unknown key: {relation.to_key}"

    # The cursor is persisted as JSON between syncs — it must round-trip.
    assert json.loads(json.dumps(result.cursor)) == result.cursor, "cursor must be JSON round-trip"

    changed = await connector.detect_changes(ctx)
    assert isinstance(changed, bool), "detect_changes() must return a bool"

    # --- SOLUSDEV-167: cheap change detection is a CONTRACT, not a courtesy ---
    #
    # A connector that cannot answer "nothing changed" without doing the full
    # sync re-syncs forever and burns the provider's quota. That is what cost
    # ~80% of an ANNUAL Onshape allowance in a single afternoon, so it is
    # enforced mechanically here rather than left to each connector's diligence.
    # These assertions are what make the caching/freshness layer general: a new
    # integration inherits it by satisfying the contract, with no bespoke code.

    assert result.cursor, (
        "sync() must return a non-empty cursor — a connector with no cursor can "
        "never answer 'nothing changed', so every sync pays full price"
    )

    settled = SyncContext(
        credentials=ctx.credentials, config=ctx.config, cursor=dict(result.cursor)
    )
    assert await connector.detect_changes(settled) is False, (
        "detect_changes() must return False for the cursor sync() just produced; "
        "otherwise the source re-syncs on every sweep forever"
    )

    empty = SyncContext(credentials=ctx.credentials, config=ctx.config, cursor={})
    assert await connector.detect_changes(empty) is True, (
        "an empty cursor means 'never synced' and must report changed, or a new "
        "source would never make its first sync"
    )
    return result
