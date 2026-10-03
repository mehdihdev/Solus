"""Onshape operations exposed to SOL as in-process tools — SOLUS-ONS-A1.

The bridge between two things that already existed and had never been joined:
`connectors/onshape_ops.py` (transport-free operations) and the W0-04
`ToolRegistry`. Wrapping them as `InProcessTool`s rather than an `MCPTool` is
deliberate — `MCPServerSpec` requires a stdio command or an HTTP url, so an
in-process server would mean editing a security-reviewed module's core contract
to gain nothing. Going through `InProcessTool` inherits JSON-Schema arg
validation, the registry timeout, the never-raises envelope and
`confirmation_refusal` for free.

**Tenant scope is bound HERE, by Solus code, before the model sees anything**
(the `get_entity` idiom). `project_id` is a closure variable, never an argument,
so no model output can reach another team's Onshape. A source in a different
project is reported as NOT_FOUND rather than a permission error — no existence
oracle.

**Credentials.** A tool call is not a sync, so the sync path's credential
resolution does not apply. Instead: project → the connected Onshape `Source` →
its `secret_ref` → `resolve_credentials` → `call_with_refresh`, the same
refresh-once-and-retry seam `/selectable` uses. Onshape access tokens live 60
minutes, so an expired token during a tool call is ordinary, not an error.
Resolution happens per CALL, not at build time — a token can rotate mid-request.

**The connect-time grant is enforced here, not just in the picker** (SOLUS-ONS-A3).
Onshape scopes are account-wide, so a customer who chose read-only has a token
that could technically write; the refusal is ours to make. It is re-read from the
source on every call, so revoking edit rights takes effect immediately, and an
absent grant (a source connected before the choice existed) reads as read-only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_ID_RE, tracked_document_ids
from solus_api.connectors.onshape_confirmation import ConfirmedOnshapeTool, PreviewBinding
from solus_api.connectors.onshape_ops import OnshapeOperation, every_operation
from solus_api.connectors.onshape_read_cache import (
    ReadScope,
    TurnReadMemo,
    bind_read_scope,
    connector_cache,
    recorded_workspaces,
)
from solus_api.connectors.registry import ConnectorContext, ConnectorRegistry, UnknownConnectorError
from solus_api.connectors.runtime import call_with_refresh, refresh_secret_ref, resolve_credentials
from solus_api.connectors.secrets import SecretNotFoundError, SecretStore
from solus_api.models import (
    AccountConnection,
    ConnectionStatus,
    GraphEntity,
    Source,
    SourceStatus,
    SourceType,
)
from solus_api.services.connections import onshape_application_for

if TYPE_CHECKING:
    from solus_api.connectors.onshape import OnshapeConnector

logger = logging.getLogger("solus.agent.tools.onshape")

#: One authenticated step against Onshape — an operation's `run` or its
#: `preview`. Both need identical credential resolution and the same grant check.
type _Step[T] = Callable[["OnshapeConnector", httpx.AsyncClient, dict[str, Any]], Awaitable[T]]

#: `ConnectorError.code` → the W0-04 error code a model can branch on. Anything
#: unlisted is a TOOL_ERROR, so a new connector code can never leak as a crash.
_ERROR_CODES: dict[str, ToolErrorCode] = {
    "config_invalid": ToolErrorCode.INVALID_ARGS,
    "stale_state": ToolErrorCode.UNAUTHORIZED,
    "invalid_credentials": ToolErrorCode.UNAUTHORIZED,
    "oauth_refresh_failed": ToolErrorCode.UNAUTHORIZED,
    "oauth_not_configured": ToolErrorCode.UNAUTHORIZED,
    "not_found": ToolErrorCode.NOT_FOUND,
}

#: Codes worth retrying: a transport blip, not a bad request.
_RETRYABLE = frozenset({"api_unreachable", "api_error"})


# A graph refresh is activity, not revocation of the existing source grant.
_USABLE_SOURCE_STATES = (SourceStatus.CONNECTED, SourceStatus.SYNCING)


def _usable_source() -> ColumnElement[bool]:
    # A raced graph snapshot does not revoke live account authority.
    return or_(
        Source.status.in_(_USABLE_SOURCE_STATES),
        and_(
            Source.status == SourceStatus.ERROR,
            Source.last_error["code"].as_string() == "revision_changed",
        ),
    )


async def _connected_source(
    session_factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> Source | None:
    """The project's connected Onshape source, or None.

    Scoped to `project_id` — the closure-bound one — so a source belonging to any
    other project is simply not visible.
    """
    async with session_factory() as session:
        source: Source | None = await session.scalar(
            select(Source).where(
                Source.project_id == project_id,
                Source.type == SourceType.ONSHAPE,
                _usable_source(),
            )
        )
        return source


def _tool_error(exc: ConnectorError, *, preview_only: bool = False) -> ToolException:
    """Map a connector failure to the model-facing envelope.

    The message is the connector's own — which never echoes upstream text or
    credential material (its `request` helper drops both deliberately).
    """
    if preview_only and exc.code in {"quota_degraded", "quota_exhausted"}:
        from solus_api.agent.confirmations import QuotaPreviewUnavailable

        return QuotaPreviewUnavailable(exhausted=exc.code == "quota_exhausted")
    return ToolException(
        exc.message,
        code=_ERROR_CODES.get(exc.code, ToolErrorCode.TOOL_ERROR),
        retryable=exc.code in _RETRYABLE,
    )


#: The value `Source.config["access"]` carries when the customer granted edit
#: rights. Anything else — including nothing — is read-only.
_WRITE_ACCESS = "write"


async def _may_write(session_factory: async_sessionmaker[AsyncSession], source: Source) -> bool:
    """Whether the customer granted edit rights. SOLUSDEV-241: a source bound to
    an account connection answers from the CONNECTION's record — the grant is
    the account's, and `source.config` is member-editable — so a patched-in
    `access` on the source can never widen what the owner granted."""
    if source.connection_id is not None:
        async with session_factory() as session:
            connection = await session.get(AccountConnection, source.connection_id)
        config = (
            connection.config
            if connection is not None and isinstance(connection.config, dict)
            else {}
        )
        return config.get("access") == _WRITE_ACCESS
    config = source.config if isinstance(source.config, dict) else {}
    return config.get("access") == _WRITE_ACCESS


async def _prepare(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    secret_store: SecretStore,
    connectors: ConnectorRegistry,
    *,
    is_write: bool,
) -> tuple[OnshapeConnector, Credentials, Source]:
    """The connected source and its live credentials, with the grant checked.

    Re-read per call rather than bound at build time: an access token rotates
    inside 60 minutes, and revoking edit rights must take effect immediately.
    """
    source = await _connected_source(session_factory, project_id)
    if source is None or not source.secret_ref:
        raise ToolException(
            "No Onshape source is connected to this project. Connect one in Sources first.",
            code=ToolErrorCode.NOT_FOUND,
            retryable=False,
        )
    onshape_application = onshape_application_for(source)
    account_ref = source.account_external_id or f"source:{source.id}"
    if source.connection_id is not None:
        async with session_factory() as session:
            account = await session.get(AccountConnection, source.connection_id)
        if (
            account is None
            or account.status is not ConnectionStatus.CONNECTED
            or account.provider is not SourceType.ONSHAPE
            or not account.secret_ref
        ):
            raise ToolException(
                "The connected Onshape account is unavailable",
                code=ToolErrorCode.UNAUTHORIZED,
                retryable=False,
            )
        # Detached per-call source snapshot; never persisted to source config.
        source.secret_ref = account.secret_ref
        onshape_application = onshape_application_for(account)
        account_ref = account.account_external_id or f"connection:{account.id}"
    if is_write and not await _may_write(session_factory, source):
        raise ToolException(
            "This Onshape source is connected read-only. Reconnect it and choose "
            "'Read and edit' to let Solus change your models.",
            code=ToolErrorCode.UNAUTHORIZED,
            retryable=False,
        )
    try:
        connector = connectors.create_scoped(
            "onshape",
            ConnectorContext(
                project_id=project_id,
                team_id=source.team_id,
                acting_user_id=source.created_by,
                account_ref=account_ref,
                onshape_application=onshape_application,
                # ADR-038 section 4: SOL's calls are attributed (and, past the
                # degrade band, deferrable) as agent reads or agent writes.
                purpose="agent",
                label="agent_write" if is_write else "agent_read",
            ),
        )
    except UnknownConnectorError as exc:  # pragma: no cover - registry always has it
        raise ToolException(
            "The Onshape connector is not available.",
            code=ToolErrorCode.TOOL_ERROR,
            retryable=False,
        ) from exc
    try:
        credentials = await resolve_credentials(secret_store, source.secret_ref)
    except SecretNotFoundError as exc:
        raise ToolException(
            "The stored Onshape credentials are missing; reconnect the source.",
            code=ToolErrorCode.UNAUTHORIZED,
            retryable=False,
        ) from exc
    onshape: OnshapeConnector = connector  # type: ignore[assignment]
    return onshape, credentials, source


def _refuse_untracked_document(source: Source, args: dict[str, Any]) -> list[str]:
    """Refuse any call naming a document this project does not track; return the
    tracked set so the caller can bind it as the model's menu.

    THE addressing guard, and it is on the READ path too, deliberately: without
    it `get_body_details` could read any document in the customer's whole Onshape
    account. `list_documents` is the model's menu and is scoped separately; this
    is the floor under every operation, because they all route through `_call`.

    Answers NOT_FOUND, never UNAUTHORIZED — a permission error would confirm the
    document exists, the same no-existence-oracle rule `get_entity` follows.

    Runs on the APPROVAL path too, for free: `_prepare` re-reads the source per
    call, so a document deselected between park and approve refuses at approve.
    """
    try:
        tracked = tracked_document_ids(source.config if isinstance(source.config, dict) else {})
    except ConnectorError as exc:  # a selection we cannot read is not a licence
        raise _tool_error(exc) from exc
    document_id = args.get("document_id")
    if not isinstance(document_id, str):
        return tracked
    if ONSHAPE_ID_RE.fullmatch(document_id) is None:
        # A MALFORMED id is a mistake the model can fix, and the connector's own
        # validation says so with INVALID_ARGS. Answering NOT_FOUND here instead
        # would teach it the document merely does not exist and send it hunting.
        # Untracked and unparseable are different answers.
        return tracked
    if not tracked:
        # FAIL CLOSED. A connected but idle source tracks nothing, and "nothing
        # tracked" must never read as "everything allowed".
        raise ToolException(
            "No Onshape documents are being tracked for this project yet. "
            "Pick the documents to track in Sources first.",
            code=ToolErrorCode.NOT_FOUND,
            retryable=False,
        )
    if document_id not in tracked:
        raise ToolException(
            "That Onshape document is not one this project tracks. "
            "Add it in Sources if you meant to work on it.",
            code=ToolErrorCode.NOT_FOUND,
            retryable=False,
        )
    return tracked


class _AccountRefreshStore(SecretStore):
    """Fence refreshed credentials and their retry against account revocation.

    The vendor refresh runs without a database lock. Before its first secret
    write, reacquire the account and source's live authority; keep that account
    lock through both token writes and the retried operation. Revoke uses the
    same lock, so it either wins first (no writes/retry) or deletes the resulting
    family after this operation completes.
    """

    def __init__(
        self,
        session: AsyncSession,
        store: SecretStore,
        source: Source,
        args: dict[str, Any],
        *,
        is_write: bool,
    ) -> None:
        self._session = session
        self._store = store
        self._source = source
        self._args = args
        self._is_write = is_write
        self._admitted = False

    async def _admit(self) -> None:
        account = await self._session.scalar(
            select(AccountConnection)
            .where(
                AccountConnection.id == self._source.connection_id,
                AccountConnection.provider == SourceType.ONSHAPE,
                AccountConnection.status == ConnectionStatus.CONNECTED,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current = await self._session.scalar(
            select(Source)
            .where(
                Source.id == self._source.id,
                Source.project_id == self._source.project_id,
                Source.connection_id == self._source.connection_id,
                Source.type == SourceType.ONSHAPE,
                _usable_source(),
            )
            .execution_options(populate_existing=True)
        )
        if (
            account is None
            or current is None
            or not account.secret_ref
            or account.secret_ref != self._source.secret_ref
            or (self._is_write and (account.config or {}).get("access") != _WRITE_ACCESS)
        ):
            raise ToolException(
                "The Onshape grant changed during sign-in; reconnect the account",
                code=ToolErrorCode.UNAUTHORIZED,
                retryable=False,
            )
        tracked = _refuse_untracked_document(current, self._args)
        if "source_document_id" in self._args:
            _refuse_untracked_document(current, {"document_id": self._args["source_document_id"]})
        self._args["_documents"] = tracked
        self._admitted = True

    async def put(self, ref: str, value: str) -> None:
        if not self._admitted:
            await self._admit()
        expected = self._source.secret_ref or ""
        if ref not in {expected, refresh_secret_ref(expected)}:
            raise ToolException(
                "Invalid Onshape credential scope", code=ToolErrorCode.UNAUTHORIZED, retryable=False
            )
        await self._store.put(ref, value)

    async def get(self, ref: str) -> str:
        return await self._store.get(ref)

    async def delete(self, ref: str) -> None:
        await self._store.delete(ref)


async def _run_with_refresh[T](
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    connector: OnshapeConnector,
    credentials: Credentials,
    secret_store: SecretStore,
    args: dict[str, Any],
    run: Callable[[Credentials], Awaitable[T]],
    *,
    is_write: bool,
) -> T:
    async def invoke(store: SecretStore) -> T:
        return await call_with_refresh(
            connector=connector,
            credentials=credentials,
            secret_store=store,
            secret_ref=source.secret_ref or "",
            run=run,
        )

    if source.connection_id is not None:
        async with session_factory() as session:
            result = await invoke(
                _AccountRefreshStore(session, secret_store, source, args, is_write=is_write)
            )
            await session.commit()
            return result
    return await invoke(secret_store)


async def _invoke_bound(
    binding: PreviewBinding,
    args: dict[str, Any],
    invoke: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    try:
        with binding.execution(args):
            return await invoke()
    except ConnectorError as exc:
        raise _tool_error(exc) from exc


def _retire_probes(memo: TurnReadMemo, args: dict[str, Any], *, retire: bool) -> None:
    """Even a failed write may have moved the microversion: the next read of the
    document in this turn must ask Onshape again."""
    document_id = args.get("document_id")
    if retire and isinstance(document_id, str):
        memo.forget_probes(document_id)


def _account_ref(connector: OnshapeConnector, source: Source) -> str:
    """The provider account the connector's cache and meter are keyed by."""
    mirror = connector_cache(connector)
    return mirror[1] if mirror is not None else f"source:{getattr(source, 'id', '')}"


async def _known_document_name(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    secret_store: SecretStore,
    connectors: ConnectorRegistry,
    memo: TurnReadMemo,
    document_id: str,
) -> str | None:
    """A document's name from local knowledge only — no provider call."""
    connector, _credentials, source = await _prepare(
        session_factory, project_id, secret_store, connectors, is_write=False
    )
    account_ref = _account_ref(connector, source)
    info = memo.peek((account_ref, document_id, "doc"))
    named = info.get("name") if isinstance(info, dict) else None
    if isinstance(named, str) and named:
        return named
    async with session_factory() as session:
        node = await session.scalar(
            select(GraphEntity.name).where(
                GraphEntity.project_id == project_id,
                GraphEntity.source_id == source.id,
                GraphEntity.external_ref == f"{document_id}:document",
                GraphEntity.deleted_at.is_(None),
            )
        )
    if node:
        return node
    mirror = connector_cache(connector)
    listing = await mirror[0].cached_listing("onshape", mirror[1]) if mirror else None
    return (
        next((item["name"] for item in listing.value if item["id"] == document_id), None)
        if listing
        else None
    )


def _build_tool(
    operation: OnshapeOperation,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    secret_store: SecretStore,
    connectors: ConnectorRegistry,
    turn_memo: TurnReadMemo | None = None,
) -> Tool:
    memo = turn_memo if turn_memo is not None else TurnReadMemo()
    is_write = "write" in operation.tags
    binding = PreviewBinding(
        enabled=operation.name
        in {
            "onshape.set_variable",
            "onshape.insert_part",
            "onshape.update_feature",
            "onshape.extrude_cut",
            "onshape.create_circle_sketch",
            "onshape.create_face_mate_connector",
            "onshape.create_circle_mate_connector",
            "onshape.create_fastened_mate",
            "onshape.restore_fastened_pose",
            "onshape.create_revolute_mate",
        }
    )

    async def _call[T](args: dict[str, Any], step: _Step[T], *, preview_only: bool = False) -> T:
        connector, credentials, source = await _prepare(
            session_factory, project_id, secret_store, connectors, is_write=is_write
        )
        tracked = _refuse_untracked_document(source, args)
        if "source_document_id" in args:
            _refuse_untracked_document(source, {"document_id": args["source_document_id"]})
        # The model's MENU, bound by Solus code exactly like `project_id` — never
        # an argument it could supply. Every operation schema forbids extra
        # properties, so a model that tried to send `_documents` is rejected at
        # registry validation before this runs.
        args = {**args, "_documents": tracked}

        async def run(creds: Credentials) -> T:
            async with connector.http(creds) as client:
                return await step(connector, client, args)

        scope = ReadScope(
            memo=memo,
            account_ref=_account_ref(connector, source),
            workspaces=recorded_workspaces(getattr(source, "cursor", None)),
            is_write=is_write,
        )
        try:
            with bind_read_scope(scope):
                return await _run_with_refresh(
                    session_factory,
                    source,
                    connector,
                    credentials,
                    secret_store,
                    args,
                    run,
                    is_write=is_write,
                )
        except ConnectorError as exc:
            logger.info("onshape tool %s failed: %s", operation.name, exc.code)
            raise _tool_error(exc, preview_only=preview_only) from exc
        finally:
            _retire_probes(memo, args, retire=is_write and not preview_only)

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        return await _invoke_bound(binding, args, lambda: _call(args, operation.run))

    async def preview(args: dict[str, Any]) -> list[dict[str, Any]]:
        assert operation.preview is not None
        binding.clear()
        rows = await _call(args, operation.preview, preview_only=True)
        complete = [*await _document_row(args), *rows]
        binding.remember(args, rows)
        return complete

    async def _document_row(args: dict[str, Any]) -> list[dict[str, Any]]:
        """WHICH document this change lands in, by NAME, as the card's first row.

        Without it the summary named the document by a 24-hex id, which no human
        can recognise — so "approve" meant approving an edit to a document the
        person could not actually identify. Added here rather than in
        `confirmations._summarize`, which is deliberately domain-free: a CAD
        edit, a firmware flash and a robot command all render the same rows, and
        an Onshape lookup in that function would be a domain leak.

        ADR-038 section 5: the name is NEVER fetched for the card. It comes from
        what this turn already read, the graph's document node, or the account's
        cached listing, in that order; a card whose name is unknown degrades to
        the id rather than blocking the park — a weaker card beats an unreachable
        action. The name is Onshape-supplied, so it rides the same `_single_line`
        + `redact_text` gate as every other row.

        Stable by construction, so it cannot manufacture a false STALE: a
        document's name does not change under a model edit.
        """
        document_id = args.get("document_id")
        if not isinstance(document_id, str) or not is_write:
            return []
        try:
            name = await _known_document_name(
                session_factory, project_id, secret_store, connectors, memo, document_id
            )
        except Exception:
            logger.info("could not name Onshape document for the consent card")
            name = None
        return [{"label": "document", "before": None, "after": name or document_id}]

    tool_class = ConfirmedOnshapeTool if binding.enabled else InProcessTool
    return tool_class(
        ToolDescriptor(
            name=operation.name,
            description=operation.description,
            params=operation.params,
            returns=operation.returns,
            requires_confirmation=operation.requires_confirmation,
        ),
        handler,
        preview if operation.preview is not None else None,
    )


def build_onshape_tools(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    secret_store: SecretStore | None,
    connectors: ConnectorRegistry,
) -> list[Tool]:
    """Every Onshape operation, bound to ONE project.

    Returns `[]` without a secret store — there would be no way to authenticate,
    and offering tools that always fail is worse than not offering them (the same
    fail-closed rule MCP-05's license preflight follows).
    """
    if secret_store is None:
        return []
    # One registry is one SOL turn (`deps.get_sol_registry` builds it per
    # request), so this memo lives exactly as long as the turn does.
    memo = TurnReadMemo()
    return [
        _build_tool(operation, session_factory, project_id, secret_store, connectors, memo)
        for operation in every_operation()
    ]


__all__ = ["build_onshape_tools"]
