"""Account-isolated immutable Onshape reads, never mutable target observations.

Callers resolve current authorization and verify the donor revision before using
this helper. Only default-configuration responses are admitted; configured donor
responses need an explicitly configuration-bound interface before reuse. The
fetch callback must raise on transport/auth/provider failures, as the connector
transport does. No mutable workspace key, target-state cache or vendor URL is
accepted here.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

import httpx

from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import ONSHAPE_ID_RE

_MAX_SPEC_BYTES = 8 * 1024 * 1024
_MAX_DONOR_BYTES = 32 * 1024 * 1024


def _snapshot(value: Any, *, max_bytes: int = _MAX_SPEC_BYTES) -> Any:
    if not isinstance(value, (dict, list)):
        raise ValueError("immutable specification must be a JSON object or array")
    encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("immutable payload exceeds the bounded acquisition size")
    return json.loads(encoded)


class OnshapeReadCache:
    """Reuse immutable default-configuration donor geometry or feature specs."""

    def __init__(self, cache: IntegrationCache, account_ref: str) -> None:
        if (
            not isinstance(account_ref, str)
            or not account_ref.strip()
            or len(account_ref) > 256
            or any(ord(char) < 32 for char in account_ref)
        ):
            raise ValueError("resolved account identity is required")
        self._cache = cache
        self._account_ref = account_ref

    async def fetch(
        self,
        *,
        document_id: str,
        element_id: str,
        revision_kind: Literal["m", "v"],
        revision_id: str,
        kind: Literal["donor_geometry", "feature_spec"],
        fetch: Callable[[], Awaitable[Any]],
        collection: Literal["partstudios", "assemblies"] | None = None,
    ) -> Any:
        if revision_kind not in ("m", "v") or kind not in ("donor_geometry", "feature_spec"):
            raise ValueError("only immutable donor revisions and specifications may be reused")
        if any(
            not isinstance(value, str) or not ONSHAPE_ID_RE.fullmatch(value)
            for value in (document_id, element_id, revision_id)
        ):
            raise ValueError("invalid immutable Onshape resource identity")
        if collection not in (None, "partstudios", "assemblies"):
            raise ValueError("invalid immutable specification collection")
        key = self._cache.payload_key(
            "onshape",
            self._account_ref,
            document_id,
            revision_id,
            "immutable-read-v1",
            revision_kind,
            element_id,
            kind,
            "default-configuration",
            *([collection] if collection else []),
        )

        # Acquisition is bounded independently of cache admission. Large donor
        # geometry remains usable; IntegrationCache still declines storage above
        # its 8 MiB limit. Feature specifications retain their smaller ceiling.
        max_bytes = _MAX_DONOR_BYTES if kind == "donor_geometry" else _MAX_SPEC_BYTES

        async def acquire() -> Any:
            return _snapshot(await fetch(), max_bytes=max_bytes)

        result = await self._cache.fetch(
            key, ttl_seconds=self._cache.payload_ttl_seconds, fetch=acquire
        )
        return _snapshot(result.value, max_bytes=max_bytes)


def validated_feature_specs(body: Any) -> dict[str, Any]:
    """Reject error/partial/malformed tables before any reusable cache entry."""
    if (
        not isinstance(body, dict)
        or body.get("errorEnum") not in (None, "NO_ERROR")
        or any(body.get(key, False) is not False for key in ("incomplete", "isIncomplete"))
        or body.get("isComplete", True) is not True
        or ("libraryVersion" in body and type(body["libraryVersion"]) is not int)
        or not isinstance(body.get("featureSpecs"), list)
    ):
        raise ConnectorError("api_error", "Onshape returned incomplete feature specifications")
    for wrapped in body["featureSpecs"]:
        spec = wrapped.get("message", wrapped) if isinstance(wrapped, dict) else None
        if (
            not isinstance(spec, dict)
            or not isinstance(spec.get("featureType"), str)
            or not spec["featureType"]
        ):
            raise ConnectorError("api_error", "Onshape returned malformed feature specifications")
        _validate_parameter_collection(spec)
    try:
        return cast(dict[str, Any], _snapshot(body))
    except (ValueError, TypeError, OverflowError):
        raise ConnectorError(
            "api_error", "Onshape returned invalid feature specification values"
        ) from None


def _validate_parameter_collection(spec: dict[str, Any]) -> None:
    """Preserve vendor visibility variants; selection still requires unique IDs."""
    from solus_api.connectors.onshape_ops import _parameter_specs_by_id, _read_messages

    if "parameters" not in spec or "parameterIdToSpec" in spec:
        _parameter_specs_by_id(spec)
        return
    for parameter in _read_messages(spec["parameters"]):
        identity = parameter.get("parameterId")
        if not isinstance(identity, str) or not identity:
            raise ConnectorError("api_error", "Onshape returned malformed parameter identities")


# ----------------------------------------------------------------------------
# ADR-038 section 5: SOL reads through the mirror.
#
# A SOL turn is one HTTP request and `deps.get_sol_registry` builds one tool
# registry per request, so the registry is the turn. `build_onshape_tools`
# creates one `TurnReadMemo` per registry; the tool layer binds it (with the
# account and the workspaces the last sync recorded) as the `ReadScope` for the
# duration of each call. No tool receives a turn id, so the memo is also capped
# at 60 seconds, which bounds it if a registry is ever reused.
# ----------------------------------------------------------------------------

#: A memoised probe or immutable read never outlives this, whatever the owner.
READ_MEMO_TTL_SECONDS: Final = 60.0
_MEMO_MAX_BYTES: Final = 64 * 1024 * 1024
_MEMO_MAX_ENTRIES: Final = 256
#: Bumped when the shape of a mirrored read changes (key namespace).
_MIRROR_KEY_VERSION: Final = "sol-read-v1"

type MemoKey = tuple[str, ...]


class TurnReadMemo:
    """Short-lived, single-flight memo of one SOL turn's provider facts.

    Keys are tuples whose FIRST element is the provider account and SECOND the
    document, so two accounts that hold the same document id can never read
    each other's entries. Failures are never stored. Payload entries are held
    as encoded JSON so every reader gets its own copy.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = READ_MEMO_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_bytes: int = _MEMO_MAX_BYTES,
    ) -> None:
        if not 0 < ttl_seconds <= READ_MEMO_TTL_SECONDS:
            raise ValueError("a turn memo may not outlive sixty seconds")
        self._ttl = ttl_seconds
        self._clock = clock
        self._max_bytes = max_bytes
        self._entries: dict[MemoKey, tuple[float, Any, int]] = {}
        self._locks: dict[MemoKey, asyncio.Lock] = {}
        self._bytes = 0

    def peek(self, key: MemoKey) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock() - entry[0] > self._ttl:
            self._drop(key)
            return None
        return entry[1]

    def remember(self, key: MemoKey, value: Any) -> None:
        self._store(key, value)

    async def once[T](
        self,
        key: MemoKey,
        factory: Callable[[], Awaitable[T]],
        *,
        keep: Callable[[T], bool] | None = None,
    ) -> T:
        hit = self.peek(key)
        if hit is not None:
            return cast(T, hit)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self.peek(key)
            if hit is not None:
                return cast(T, hit)
            value = await factory()
            if keep is None or keep(value):
                self._store(key, value)
            return value

    def forget_probes(self, document_id: str) -> None:
        """A write moved this document's microversion: no account's probe of it holds."""
        for key in [k for k in self._entries if k[1:3] == (document_id, "probe")]:
            self._drop(key)

    def _store(self, key: MemoKey, value: Any) -> None:
        size = len(value) if isinstance(value, str) else 0
        if size > self._max_bytes:
            return
        self._drop(key)
        while self._entries and (
            self._bytes + size > self._max_bytes or len(self._entries) >= _MEMO_MAX_ENTRIES
        ):
            self._drop(next(iter(self._entries)))
        self._entries[key] = (self._clock(), value, size)
        self._bytes += size

    def _drop(self, key: MemoKey) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= entry[2]


@dataclass(frozen=True)
class ReadScope:
    """What one tool call may reuse. Writes get a scope too, but never mirror."""

    memo: TurnReadMemo
    account_ref: str
    #: `Source.cursor["workspaces"]`: the default workspace the last sync resolved.
    workspaces: Mapping[str, str]
    is_write: bool


_SCOPE: ContextVar[ReadScope | None] = ContextVar("onshape_read_scope", default=None)


@contextmanager
def bind_read_scope(scope: ReadScope) -> Iterator[None]:
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def current_read_scope() -> ReadScope | None:
    return _SCOPE.get()


def recorded_workspaces(cursor: Any) -> dict[str, str]:
    """The valid `{document: workspace}` pairs a sync left on the source cursor."""
    stored = cursor.get("workspaces") if isinstance(cursor, dict) else None
    if not isinstance(stored, dict):
        return {}
    return {
        key: value
        for key, value in stored.items()
        if isinstance(key, str)
        and isinstance(value, str)
        and ONSHAPE_ID_RE.fullmatch(key)
        and ONSHAPE_ID_RE.fullmatch(value)
    }


def connector_cache(connector: Any) -> tuple[IntegrationCache, str] | None:
    """The account-keyed integration cache a scoped connector was built with.

    The single touchpoint on the connector's cache attributes; `None` for the
    unscoped connector, which then reads the provider directly as before.
    """
    cache = getattr(connector, "_cache", None)
    account_ref = getattr(connector, "_account_ref", "")
    if (
        not isinstance(cache, IntegrationCache)
        or not isinstance(account_ref, str)
        or not account_ref
    ):
        return None
    return cache, account_ref


class _Unadmitted(Exception):  # noqa: N818 - control flow, never surfaced
    def __init__(self, value: Any) -> None:
        super().__init__("not admitted to the shared cache")
        self.value = value


async def fetch_if_complete(
    cache: IntegrationCache,
    key: str,
    *,
    fetch: Callable[[], Awaitable[Any]],
    ttl_seconds: int,
    admit: Callable[[Any], bool],
    refresh: bool = False,
    min_age_seconds: float = 0,
) -> tuple[Any, bool]:
    """Single-flight cache fetch that serves, but never stores, a value `admit` refuses.

    Returns `(value, admitted)`; `admitted` is False only for a refused value.
    """

    async def guarded() -> Any:
        value = await fetch()
        if not admit(value):
            raise _Unadmitted(value)
        return value

    try:
        fetched = await cache.fetch(
            key,
            ttl_seconds=ttl_seconds,
            fetch=guarded,
            refresh=refresh,
            min_age_seconds=min_age_seconds,
        )
    except _Unadmitted as skipped:
        return skipped.value, False
    return fetched.value, True


def _is_complete(body: Any) -> bool:
    """A vendor error or partial envelope must never be pinned under an immutable key."""
    if not isinstance(body, (dict, list)):
        return False
    if isinstance(body, list):
        return True
    return (
        body.get("errorEnum") in (None, "NO_ERROR")
        and all(body.get(flag, False) is False for flag in ("incomplete", "isIncomplete"))
        and body.get("isComplete", True) is True
    )


def _microversion(body: Any) -> str:
    value = body.get("microversion") if isinstance(body, dict) else None
    if not isinstance(value, str) or not ONSHAPE_ID_RE.fullmatch(value):
        raise ConnectorError("api_error", "Onshape returned no usable current microversion")
    return value


async def document_info(
    scope: ReadScope, connector: Any, client: httpx.AsyncClient, document_id: str
) -> dict[str, Any]:
    """`{name, workspace}` from ONE `GET /documents/{d}`, shared by the whole turn."""

    async def fetch() -> dict[str, Any]:
        body = await connector.get_json(client, f"/api/v6/documents/{document_id}", what="document")
        workspace = body.get("defaultWorkspace") if isinstance(body, dict) else None
        raw = workspace.get("id", "") if isinstance(workspace, dict) else ""
        if not isinstance(raw, str) or not ONSHAPE_ID_RE.fullmatch(raw):
            raise ConnectorError("api_error", "Onshape returned no usable default workspace")
        name = body.get("name") if isinstance(body, dict) else None
        return {"name": name if isinstance(name, str) and name else None, "workspace": raw}

    return await scope.memo.once((scope.account_ref, document_id, "doc"), fetch)


async def resolve_workspace(
    scope: ReadScope, connector: Any, client: httpx.AsyncClient, document_id: str
) -> str:
    """The recorded workspace when there is one, else the document's default (once)."""
    override = scope.memo.peek((scope.account_ref, document_id, "workspace-override"))
    if isinstance(override, str):
        return override
    recorded = scope.workspaces.get(document_id)
    if recorded is not None:
        return recorded
    return str((await document_info(scope, connector, client, document_id))["workspace"])


async def _probe(
    scope: ReadScope,
    connector: Any,
    client: httpx.AsyncClient,
    document_id: str,
    workspace_id: str,
) -> str:
    async def current(workspace: str) -> str:
        return _microversion(
            await connector.get_json(
                client,
                f"/api/v6/documents/d/{document_id}/w/{workspace}/currentmicroversion",
                what="current microversion",
            )
        )

    try:
        return await current(workspace_id)
    except ConnectorError as exc:
        # A recorded workspace can go stale (the same self-heal the sync's own
        # probe performs): re-resolve ONCE before concluding the document is gone.
        if exc.code != "not_found" or scope.workspaces.get(document_id) != workspace_id:
            raise
    fresh = await document_info(scope, connector, client, document_id)
    if fresh["workspace"] == workspace_id:
        raise ConnectorError("not_found", "Onshape could not find that document")
    scope.memo.remember((scope.account_ref, document_id, "workspace-override"), fresh["workspace"])
    healed = await current(str(fresh["workspace"]))
    # Later calls in this turn resolve the healed workspace: they share this probe.
    scope.memo.remember((scope.account_ref, document_id, "probe", str(fresh["workspace"])), healed)
    return healed


async def mirrored_get(
    connector: Any,
    client: httpx.AsyncClient,
    *,
    document_id: str,
    workspace_id: str,
    path_for: Callable[[str, str], str],
    what: str,
    params: dict[str, Any] | None = None,
) -> Any:
    """A SOL READ served at an immutable microversion, or live when it may not be.

    `path_for(selector, identifier)` builds the route for `("w", workspace)` or
    `("m", microversion)`. With a read scope, a cache-equipped connector and a
    read tool: at most one `currentmicroversion` probe per document per turn,
    then every distinct read is fetched once per microversion (shared cache,
    keyed by account) and every repeat or page is a local slice. Writes, and
    connectors with no cache, read the workspace route live exactly as before.
    """
    scope = current_read_scope()
    mirror = connector_cache(connector) if scope is not None and not scope.is_write else None
    extra = {} if params is None else {"params": params}
    if scope is None or mirror is None:
        return await connector.get_json(client, path_for("w", workspace_id), what=what, **extra)
    cache, account_ref = mirror
    probe_key = (scope.account_ref, document_id, "probe", workspace_id)
    microversion = await scope.memo.once(
        probe_key, lambda: _probe(scope, connector, client, document_id, workspace_id)
    )
    path = path_for("m", microversion)
    params_text = json.dumps(params or {}, sort_keys=True, separators=(",", ":"))

    admitted_flag = [True]

    async def acquire() -> str:
        key = IntegrationCache.payload_key(
            "onshape",
            account_ref,
            document_id,
            microversion,
            _MIRROR_KEY_VERSION,
            path,
            params_text,
        )
        body, admitted = await fetch_if_complete(
            cache,
            key,
            ttl_seconds=cache.payload_ttl_seconds,
            admit=_is_complete,
            fetch=lambda: connector.get_json(client, path, what=what, **extra),
        )
        admitted_flag[0] = admitted
        return json.dumps(body, separators=(",", ":"))

    memo_key = (scope.account_ref, document_id, "read", microversion, path, params_text)
    # The memo holds the encoded text (a private copy per reader), and like the
    # shared cache it never keeps a refused (partial or error) body.
    encoded = await scope.memo.once(memo_key, acquire, keep=lambda _: admitted_flag[0])
    return json.loads(encoded)
