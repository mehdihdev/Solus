"""Hosted MCP tools bound to ONE project's connected Source (SOLUSDEV-168).

The `onshape_tools.py` idiom, applied to a vendor-hosted server: tenant scope is
bound HERE, by Solus code, before the model sees anything. `project_id` is a
closure variable, never an argument, so no model output can reach another team's
Onshape.

**Discovery is live, but it does not run here.** `build_sol_registry` is
synchronous and does zero I/O (`runtime.py:74`), it is rebuilt on every message,
every `POST /confirmations/{id}` and every `GET /sol/tools` — an endpoint with no
role floor — and there is no cache anywhere in `agent/`. Putting a 30s-bounded
network round-trip there would make `build_sol_registry` async across three
routers and hand any project-resolving caller an outbound-request amplifier. So
the server is discovered live at CONNECT time and the vetted descriptors are
persisted on the Source; this module replays them. It is the same shape the
bridge already uses — `BridgeTool`s are built from a cloud-validated inventory
captured once at bind, read from memory per request (`runtime.py:176-200`).

**The diff is the whole point.** `put_featurescript` overwrites an ENTIRE Feature
Studio, and the brief requires the approval card show what changes, in which
feature. Two properties matter and neither is free:

* the card must be READABLE — `confirmations._single_line` DELETES every
  non-printable character, newlines and tabs included, and caps at 500, so a
  whole-file `before`/`after` renders as one glued, truncated run-on where a
  `//` comment swallows the following statement. Hence per-HUNK rows.
* the R1 staleness check must be EXACT — `_diverged` compares those *rendered*
  rows, so two different sources sharing their first 500 printable characters
  compare equal and a stale approval would overwrite a teammate's edit silently.
  Hence the checksum row, which is derived from the FULL text and fits well
  inside the cap.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from solus_api.agent.tools.mcp_tool import MCPServerSpec, MCPTool, call_remote
from solus_api.agent.tools.remote_mcp import HOSTED_SERVERS, RemoteAuthError, RemoteMCPSpec
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import Tool, ToolException
from solus_api.connectors import hosted_oauth
from solus_api.connectors.hosted_oauth import HostedToken
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    Source,
    SourceStatus,
    SourceType,
    utcnow,
)

logger = logging.getLogger("solus.agent.tools.hosted")

#: Where the vetted descriptor set lives on the Source. Underscore-prefixed so
#: `serialize_source` strips it (`schemas.py:224-229`) — server-authored schemas
#: are not something any API response should hand back out.
INVENTORY_KEY = "_hosted"
#: The customer-visible state, deliberately NOT underscore-prefixed.
STATE_KEY = "hosted"

#: Preview bounds. `_LABEL_CAP` is 200 and `_VALUE_CAP` 500 in the gate; a hunk
#: line is well inside both, and `_MAX_PREVIEW_ROWS` is 50 — one of which the
#: checksum row spends.
_MAX_HUNK_ROWS = 40
#: What a hosted READ may put in front of the model, overriding the prompt
#: layer's shared 4 000. A Feature Studio truncated to 4 000 characters is not a
#: Feature Studio: SOL cannot reason about source it has seen only a prefix of,
#: let alone rewrite it, and it would confidently propose an overwrite built on
#: the part it could see. Reads only — a MUTATING tool returns a status, not a
#: payload, so it keeps the default.
#: ponytail: one number for every hosted server; move it onto `RemoteMCPSpec` as
#: data when a second server wants a different one.
HOSTED_READ_RESULT_CAP = 60_000
_HUNK_CONTEXT = 0


def _tool_error(exc: RemoteAuthError) -> ToolException:
    """A credential failure names what the human must DO. `TOOL_ERROR` +
    `retryable=True` — the old behaviour for anything that was not a missing
    secret — would make SOL spin against a permanently dead grant."""
    return ToolException(
        exc.message,
        code=ToolErrorCode.UNAUTHORIZED if not exc.retryable else ToolErrorCode.TOOL_ERROR,
        retryable=exc.retryable,
    )


def _hosted_source_available() -> ColumnElement[bool]:
    """A REST quota failure does not revoke the separate hosted OAuth grant.

    Only the trusted runtime's exact Onshape quota error is exempted. All other
    source failures remain blocked; account/grant checks still run separately.
    """
    return or_(
        Source.status == SourceStatus.CONNECTED,
        and_(
            Source.type == SourceType.ONSHAPE,
            Source.status == SourceStatus.ERROR,
            Source.last_error["code"].as_string() == "quota_exhausted",
        ),
    )


class SourceHostedAuth:
    """Resolves ONE Source's hosted-server bearer token, refreshing on expiry.

    Re-read per call rather than bound at build time: the token lives ~1h, and a
    disconnect must take effect immediately rather than at the next registry
    build. Satisfies `remote_mcp.RemoteAuth` structurally.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        project_id: uuid.UUID,
        spec: RemoteMCPSpec,
        secret_store: SecretStore,
        source_id: str | None = None,
        connection_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._project_id = project_id
        self._spec = spec
        self._secret_store = secret_store
        self._source_id = source_id
        self._connection_id = connection_id

    async def _secret_ref(self, session: AsyncSession) -> tuple[str, Source | AccountConnection]:
        query = (
            select(Source)
            .where(
                Source.project_id == self._project_id,
                Source.type == self._spec.source_type,
                _hosted_source_available(),
            )
            .order_by(Source.id)
        )
        if self._source_id is not None:
            query = query.where(Source.id == uuid.UUID(self._source_id))
        source = await session.scalar(query)
        if source is None or not source.secret_ref:
            raise RemoteAuthError(
                "not_connected",
                "No Onshape source is connected to this project. Connect one in Sources first.",
            )
        if self._source_id is not None and str(source.connection_id or "") != str(
            self._connection_id or ""
        ):
            raise RemoteAuthError(
                "not_connected", "The connected account changed; reload the tools"
            )
        ref = source.secret_ref
        owner: Source | AccountConnection = source
        if source.connection_id is not None:
            account = await session.scalar(
                select(AccountConnection)
                .where(
                    AccountConnection.id == source.connection_id,
                    AccountConnection.provider == self._spec.source_type,
                    AccountConnection.status == ConnectionStatus.CONNECTED,
                )
                .with_for_update()
            )
            if account is None or not account.secret_ref:
                raise RemoteAuthError(
                    "not_connected", "The connected account is no longer available"
                )
            stored = account.config.get(INVENTORY_KEY) if isinstance(account.config, dict) else None
            if not isinstance(stored, dict) or self._spec.name not in stored:
                raise RemoteAuthError(
                    "not_enabled", "Enable the hosted add-on on the connected account"
                )
            ref = account.secret_ref
            owner = account
        return hosted_oauth.token_secret_ref(ref, self._spec.name), owner

    async def headers(self) -> Mapping[str, str]:
        async with self._session_factory() as session:
            ref, owner = await self._secret_ref(session)
            try:
                headers = await self._token_headers(ref)
            except RemoteAuthError as exc:
                if exc.code in {"reconnect_required", "scope_escalation", "not_enabled"}:
                    self._invalidate_readiness(owner)
                    await session.commit()
                raise
            await session.commit()
            return headers

    def _invalidate_readiness(self, owner: Source | AccountConnection) -> None:
        config = dict(owner.config or {})
        states = dict(config.get(STATE_KEY) or {})
        states[self._spec.name] = {
            "state": "not_enabled",
            "tool_count": 0,
            "checked_at": utcnow().isoformat(),
            "detail": "Reconnect FeatureScript from the connected Onshape account.",
        }
        inventory = dict(config.get(INVENTORY_KEY) or {})
        inventory.pop(self._spec.name, None)
        owner.config = {**config, STATE_KEY: states, INVENTORY_KEY: inventory}

    async def _token_headers(self, ref: str) -> Mapping[str, str]:
        try:
            token = HostedToken.from_json(await self._secret_store.get(ref))
        except SecretNotFoundError as exc:
            raise RemoteAuthError(
                "not_enabled",
                "FeatureScript is not enabled for this Onshape source yet. Enable "
                "it on the source in Sources.",
            ) from exc
        except ValueError as exc:  # a corrupt stored value is not a live grant
            raise RemoteAuthError(
                "reconnect_required",
                "The stored FeatureScript sign-in is unreadable. Reconnect "
                "FeatureScript on the Onshape source.",
            ) from exc
        if token.expired(now=time.time()):
            client = await hosted_oauth.ensure_client(
                self._secret_store,
                self._spec,
                redirect_uri=hosted_oauth.registered_redirect_uri(self._spec),
            )
            token = await hosted_oauth.refresh_token(self._spec, client, token)
            # One ref, one write: the pair can never half-land, which is the
            # failure the connector path avoids only by write ORDERING.
            await self._secret_store.put(ref, token.to_json())
        return {"Authorization": f"Bearer {token.access_token}"}

    async def headers_or_refuse(self) -> Mapping[str, str]:
        """`headers`, with a credential failure translated into the W0-04
        vocabulary. `MCPTool` re-raises a `ToolException` untouched, so the
        model is told to reconnect rather than "the server is unavailable,
        retry" — which is what made SOL spin against a dead grant."""
        try:
            return await self.headers()
        except RemoteAuthError as exc:
            raise _tool_error(exc) from exc


async def load_hosted_inventory(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Every hosted server's vetted tool set for one project, for the registry.

    The registry build is synchronous and does zero I/O by design — live
    discovery there would put a 30s network call on every message and on
    `GET /sol/tools`, which has no role floor. So the CALLER loads this and
    passes it in, and this is the one function that reads `INVENTORY_KEY`.

    It lives here, beside the key it reads and the builder that consumes it,
    because a router hand-rolling the config read is how the two drift.

    A malformed row is dropped rather than trusted: the inventory is a JSON
    column, and `build_hosted_tools` re-validates every descriptor anyway.
    """
    sources = (
        await session.scalars(
            select(Source)
            .where(
                Source.project_id == project_id,
                _hosted_source_available(),
                Source.type.in_({spec.source_type for spec in HOSTED_SERVERS.values()}),
            )
            .order_by(Source.id)
        )
    ).all()
    inventory: dict[str, Any] = {}
    for source in sources:
        account = None
        if source.connection_id is not None:
            account = await session.scalar(
                select(AccountConnection)
                .where(
                    AccountConnection.id == source.connection_id,
                    AccountConnection.provider == source.type,
                    AccountConnection.status == ConnectionStatus.CONNECTED,
                )
                .execution_options(populate_existing=True)
            )
            if account is None or not account.secret_ref:
                continue
        owner = account or source
        config = owner.config if isinstance(owner.config, dict) else {}
        stored = config.get(INVENTORY_KEY)
        if not isinstance(stored, Mapping):
            continue
        for server, entry in stored.items():
            # Re-checked against the LIVE registry: a grant for a server Solus no
            # longer speaks to must not resurrect it.
            spec = HOSTED_SERVERS.get(server)
            if spec is not None and spec.source_type == source.type and isinstance(entry, Mapping):
                inventory.setdefault(
                    server,
                    {
                        **entry,
                        "source_id": str(source.id),
                        "connection_id": str(source.connection_id)
                        if source.connection_id
                        else None,
                        "account_ref": owner.account_external_id or f"source:{source.id}",
                    },
                )
    return inventory


async def connected_source(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    spec: RemoteMCPSpec,
) -> Source | None:
    """The project's connected Source for this hosted server's connector.

    Scoped to the closure-bound `project_id`, so a Source in any other project is
    simply not visible — a source elsewhere reads as absent, never as forbidden
    (the `get_entity` no-existence-oracle rule).
    """
    async with session_factory() as session:
        source: Source | None = await session.scalar(
            select(Source).where(
                Source.project_id == project_id,
                Source.type == spec.source_type,
                _hosted_source_available(),
            )
        )
        return source


# ------------------------------------------------------------------- the diff


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def featurescript_rows(*, target: str, before: str, after: str) -> list[dict[str, Any]]:
    """`[{label, before, after}]` for a whole-Feature-Studio overwrite.

    One row per changed hunk so the card is readable, plus ONE checksum row so
    the gate's divergence check is exact past the 500-character render cap. Pure
    and deterministic: the same three inputs always produce byte-identical rows,
    which is what stops a re-render at decide time from manufacturing a false
    STALE (every status but PENDING is terminal, so a false STALE burns the
    approval permanently).
    """
    old_lines = before.splitlines()
    new_lines = after.splitlines()
    rows: list[dict[str, Any]] = [
        {
            "label": f"{target} — content checksum",
            "before": _checksum(before),
            "after": _checksum(after),
        }
    ]
    if before == after:
        rows.append({"label": f"{target} — no change", "before": None, "after": None})
        return rows
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    changed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed += 1
        if len(rows) > _MAX_HUNK_ROWS:
            continue
        rows.append(
            {
                "label": f"{target} — line {i1 + 1}",
                "before": "\n".join(old_lines[i1:i2]) or None,
                "after": "\n".join(new_lines[j1:j2]) or None,
            }
        )
    if changed > _MAX_HUNK_ROWS:
        # NEVER a silent cap: the checksum row still makes divergence exact, but
        # the human must know the card is not showing every change.
        rows.append(
            {
                "label": f"{target} — {changed - _MAX_HUNK_ROWS} further change(s) not shown",
                "before": None,
                "after": None,
            }
        )
    return rows


# ------------------------------------------------------- resolving the diff args


def content_argument(
    put_schema: dict[str, Any], read_schema: dict[str, Any], args: dict[str, Any]
) -> str | None:
    """Which argument carries the NEW script — derived, never guessed.

    The overwrite tool takes everything the read tool takes (which document, which
    Feature Studio) PLUS the source to write. So the content argument is exactly
    the property the write schema declares and the read schema does not. Where
    more than one qualifies, the longest string value wins, since the script
    dwarfs any flag beside it.

    Deriving it this way means this code does not depend on the vendor's field
    NAMES, which the spike captured only by size — and a schema change that
    invalidated a hardcoded name would fail closed here rather than quietly
    previewing the wrong thing.
    """
    read_props = set(_properties(read_schema))
    candidates = [
        key
        for key in _properties(put_schema)
        if key not in read_props and isinstance(args.get(key), str)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda key: len(str(args.get(key, ""))))


def _properties(schema: Mapping[str, Any] | None) -> dict[str, Any]:
    props = (schema or {}).get("properties")
    return props if isinstance(props, dict) else {}


def read_arguments(read_schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """The subset of the write call's arguments the READ tool accepts — the same
    document, workspace and Feature Studio, so `before` describes the very thing
    `after` replaces."""
    return {key: args[key] for key in _properties(read_schema) if key in args}


def _target_label(read_args: dict[str, Any]) -> str:
    """A stable, human-ish name for what is being changed. Sorted so the label is
    deterministic — a label that reordered would read as divergence."""
    parts = [f"{k}={v}" for k, v in sorted(read_args.items()) if isinstance(v, str | int)]
    return " ".join(parts)[:150] or "Feature Studio"


# --------------------------------------------------------------- the tool set


def _descriptor(entry: Mapping[str, Any]) -> ToolDescriptor | None:
    """Rebuild a descriptor from the persisted inventory, or None if unusable.

    The stored rows were already vetted at discovery (safe name, bounded schema,
    no `$ref`, prose stripped, Solus-authored consent), but they came off a JSON
    column — so a row that no longer validates is DROPPED rather than trusted.
    """
    try:
        return ToolDescriptor(
            name=str(entry["name"]),
            description=str(entry.get("description", "")),
            params=dict(entry["params"]),
            returns=dict(entry.get("returns") or {"type": "object"}),
            description_trusted=False,
            requires_confirmation=bool(entry.get("requires_confirmation", True)),
            consent_summary=entry.get("consent_summary"),
        )
    except Exception:
        logger.warning("dropping an unusable stored hosted-tool descriptor")
        return None


def build_hosted_tools(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    secret_store: SecretStore | None,
    inventory: Mapping[str, Any] | None,
    redis: Any | None = None,
) -> list[Tool]:
    """Every hosted-server tool for ONE project, from the PERSISTED inventory.

    Synchronous and I/O-free, like every other branch of `build_sol_registry`:
    the network work happened at connect time. Returns `[]` without a secret
    store — offering tools that can only ever fail is worse than not offering
    them (the same fail-closed rule `build_onshape_tools` follows).

    Hosted service limits are observed from the vendor, not inferred from one
    account sample. No annual entitlement has been verified for this service.
    `redis` remains a caller-compatible argument, not an active hosted quota
    policy. Vendor refusals and the shared transport's rate/retry/auth controls
    are unchanged; the separate REST quota meter is not consulted here.
    """
    if secret_store is None or not inventory:
        return []
    tools: list[Tool] = []
    for server_name, stored in inventory.items():
        spec = HOSTED_SERVERS.get(server_name)
        if spec is None:
            # The registry shrank between releases; a grant for a server Solus no
            # longer speaks to must not resurrect it.
            continue
        if not isinstance(stored, Mapping):
            continue
        auth = SourceHostedAuth(
            session_factory=session_factory,
            project_id=project_id,
            spec=spec,
            secret_store=secret_store,
            source_id=stored.get("source_id"),
            connection_id=stored.get("connection_id"),
        )
        previews = _previews(spec, stored, auth)
        for entry in stored.get("tools") or []:
            if not isinstance(entry, Mapping):
                continue
            descriptor = _descriptor(entry)
            if descriptor is None:
                continue
            remote_name = str(entry.get("remote_name") or "")
            # Re-checked against the LIVE policy, never trusted from storage: a
            # tool dropped from the allowlist since the inventory was captured
            # must not keep working, and its gating must not be a stale value.
            if not spec.exposes(remote_name):
                continue
            tools.append(
                MCPTool(
                    spec=_server_spec(spec),
                    remote_name=remote_name,
                    descriptor=descriptor.model_copy(
                        update={
                            "requires_confirmation": spec.requires_confirmation(remote_name),
                            "consent_summary": spec.consent_summary(remote_name),
                            "result_cap": None
                            if spec.requires_confirmation(remote_name)
                            else HOSTED_READ_RESULT_CAP,
                        }
                    ),
                    secret_store=secret_store,
                    headers_provider=auth.headers_or_refuse,
                    preview=previews.get(remote_name),
                )
            )
    return tools


def _server_spec(spec: RemoteMCPSpec) -> MCPServerSpec:
    """The transport-level spec. Separate from `RemoteMCPSpec` on purpose:
    `MCPServerSpec.url` means loopback in the catalog (CAD-02), so the two
    registries stay distinct and only this function bridges them."""
    return MCPServerSpec(name=spec.name, url=spec.url)


def _previews(
    spec: RemoteMCPSpec, stored: Mapping[str, Any], auth: SourceHostedAuth
) -> dict[str, Any]:
    """The `preview(args)` builders for this server's destructive tools.

    Only the whole-file overwrite gets one today: it is the tool that replaces
    content, so it is the only one with a real before → after. The others are
    creates and evaluations, for which the gate's argument rows already show
    exactly what will run.
    """
    schemas = {
        str(e.get("remote_name")): dict(e.get("params") or {})
        for e in (stored.get("tools") or [])
        if isinstance(e, Mapping)
    }
    write_name, read_name = _OVERWRITE_PAIR.get(spec.name, (None, None))
    if write_name is None or read_name is None:
        return {}
    if write_name not in schemas or read_name not in schemas:
        return {}
    put_schema, read_schema = schemas[write_name], schemas[read_name]

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        content_key = content_argument(put_schema, read_schema, args)
        if content_key is None:
            # FAIL CLOSED. Returning nothing would let `_build_preview` fall back
            # to argument rows, which cannot drift — so the R1 check would pass
            # and a whole-file overwrite would execute on a card that showed a
            # mangled 500-character truncation of the new source.
            raise ToolException(
                "Solus could not work out which argument carries the new "
                "FeatureScript, so it will not show you a diff to approve.",
                code=ToolErrorCode.INVALID_ARGS,
            )
        read_args = read_arguments(read_schema, args)
        headers = await auth.headers()
        current = await call_remote(_server_spec(spec), read_name, read_args, headers=headers)
        return featurescript_rows(
            target=_target_label(read_args),
            before=_as_text(current),
            after=str(args.get(content_key, "")),
        )

    return {write_name: preview}


#: (overwrite tool, the read that shows what it replaces), per hosted server.
_OVERWRITE_PAIR: dict[str, tuple[str, str]] = {
    "onshape_fs": ("put_featurescript", "get_featurescript"),
}


def _as_text(value: Mapping[str, Any]) -> str:
    """The script out of a remote read result, whatever shape it came back in.

    `_map_result` yields either the server's `structuredContent` or
    `{"content": [text blocks]}`, so both are handled rather than assuming one.
    """
    blocks = value.get("content")
    if isinstance(blocks, list):
        return "\n".join(
            str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("text")
        )
    for key in ("contents", "content", "featurescript", "source", "text"):
        found = value.get(key)
        if isinstance(found, str):
            return found
    return ""


__all__ = [
    "INVENTORY_KEY",
    "STATE_KEY",
    "SourceHostedAuth",
    "build_hosted_tools",
    "connected_source",
    "load_hosted_inventory",
    "content_argument",
    "featurescript_rows",
    "read_arguments",
]
