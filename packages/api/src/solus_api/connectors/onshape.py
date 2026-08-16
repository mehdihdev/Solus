"""The Onshape connector — SOLUS-CAD-01.

`docs/contracts/metadata-extraction.md` §2 fixes this connector's shape, and it
is deliberately NOT the deep live-API integration the ticket text imagined:

    **Thin API** — Onshape uses its API ONLY for the thin layer: authenticate,
    DETECT CHANGES, and FETCH/GENERATE a STEP/STL export — then routes that
    export into the SHARED CAD parser (same parser the other CAD tools use).
    Onshape is **NOT** a deep live-API integration.

So there are exactly four API concerns here — OAuth, microversion change
detection, the translation→poll→download export dance, and a parts-metadata read
for part numbers — and everything after that is `parse_step` +
`build_mechanical_graph`, shared with every other CAD tool.

**Why OAuth, not an API key pair.** Onshape's own docs: *"API keys are used to
authenticate an application, NOT its users. OAuth2 authenticates an application
AND users."* A key pair acts as THE DEVELOPER and reaches only the developer's
own documents, so it can never serve a customer's. `supports_token_connect`
stays False for exactly that reason (CLAUDE.md §7 — no bypass of the OAuth flow).

**Why refresh matters here.** Onshape access tokens live **60 minutes** and the
refresh token ROTATES on every use. The runtime owns persistence and calls
`refresh_credentials` once on `invalid_credentials` (see
`runtime._sync_with_refresh`); this connector's job is to return both new tokens.

`ponytail:` part numbers are joined to STEP products by NAME, the only key both
sides share — STEP has no MPN slot and Onshape's parts API has no STEP product
id. Swap for a real id if a future export format carries one.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx

from solus_api.connectors.contracts import (
    AccountInfo,
    ConnectorError,
    Credentials,
    OAuthConnector,
    SyncContext,
    SyncError,
    SyncResult,
)
from solus_api.connectors.export_common import ErrorRecorder, label
from solus_api.connectors.mechanical import (
    MAX_CAD_EXPORT_BYTES,
    CadModel,
    CadNode,
    build_mechanical_graph,
)
from solus_api.connectors.step_parser import parse_step

logger = logging.getLogger("solus.connectors.onshape")

ONSHAPE_API_BASE = "https://cad.onshape.com"
ONSHAPE_OAUTH_BASE = "https://oauth.onshape.com"

#: Onshape document/workspace/element ids are opaque hex-ish handles. Validated
#: before any URL interpolation so a crafted config value cannot reshape the
#: request path (CLAUDE.md §7 — ingested config is untrusted input).
_ID_RE = re.compile(r"^[A-Za-z0-9]{1,40}$")
#: PUBLIC alias (SOLUS-ONS-A1): the operations layer validates model-supplied ids
#: with the SAME pattern the connector uses, so there is one definition of what
#: an Onshape id may look like and no second, weaker gate.
ONSHAPE_ID_RE = _ID_RE

_REQUEST_TIMEOUT = 30.0
#: Onshape rate-caps private OAuth apps, and one sync fires a translation job
#: per assembly plus ~1/s status polls — so a 429 is an expected operating
#: condition, not a failure. Retries are bounded (§7: never an unbounded loop
#: against a third-party API) and the server's Retry-After is honored but
#: capped, because the header is untrusted upstream input and must never park
#: a sync worker.
_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_MAX_WAIT_SECONDS = 30.0
_RATE_LIMIT_BACKOFF_SECONDS = 1.0
#: httpx's timeout is per-read, so a slow trickle never trips it. The download
#: carries its own total deadline on top.
_DOWNLOAD_DEADLINE_SECONDS = 300.0
_EXPORT_FORMAT = "STEP"
_TOO_LARGE = f"export exceeds the {MAX_CAD_EXPORT_BYTES // (1024 * 1024)} MiB parse limit"

#: Longest metadata string kept from Onshape. `properties`/`modality_hints` are
#: unbounded `dict[str, Any]`, unlike `EntityOut.name`, and flow onward into the
#: graph AND into model context via `get_entity` — so ingested values are cut
#: here rather than becoming a DB-bloat and token-cost channel.
_METADATA_LIMIT = 128

#: Config key holding the tracked documents: a LIST of document ids. A list (not
#: a dict keyed by id) because `PATCH /sources/{id}` merges config and cannot
#: delete keys — a list value replaces wholesale, so deselecting actually shrinks
#: the selection.
SELECTION_KEY = "documents"

#: Cursor value for a tracked document Onshape no longer has. Recorded so the
#: selection and the cursor keep the same key set — otherwise `detect_changes`
#: would report "changed" on every poll and re-sync forever.
_GONE = "__gone__"

#: Legacy per-source config from CAD-01, when a source named ONE element.
_LEGACY_KEYS = ("document_id", "workspace_id", "element_id")

#: Bounds on an account-level sync. Onshape rate-caps a private OAuth app, and
#: each element costs a translation job — so both the selection and the expanded
#: element set are bounded rather than "whatever the account holds".
_MAX_DOCUMENTS = 50
_MAX_ELEMENTS = 25
_MAX_DOCUMENT_PAGES = 10
#: Onshape CAPS `limit` at 20 on /documents and answers 400 for anything higher
#: — confirmed against a live tenant, which is what the fixtures could not tell
#: us (`docs/integrations/onshape-setup.md` §9). Paging covers the rest.
_PAGE_LIMIT = 20
#: Onshape's own ceiling for that parameter; the request must never exceed it.
ONSHAPE_MAX_PAGE_LIMIT = 20


@dataclasses.dataclass(frozen=True)
class _Target:
    """One exportable assembly: the (document, workspace, element) triple the
    translation API needs."""

    document_id: str
    workspace_id: str
    element_id: str

    @property
    def scope(self) -> str:
        """Namespace for this element's entity keys — see `build_mechanical_graph`."""
        return f"{self.document_id}:{self.element_id}"

    @property
    def provenance(self) -> dict[str, str]:
        return {"document_id": self.document_id, "element_id": self.element_id}


#: Ids Onshape hands back (translation request, external data). Interpolated
#: into request paths just like config ids, so they get validated too rather
#: than trusted for being ours-adjacent. Slightly wider than `_ID_RE` because
#: these are server-generated handles that may carry `-`/`_`; still no `/`,
#: `.` or `?`, so a path cannot be reshaped.
_UPSTREAM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _text(value: Any) -> str:
    """A bounded display string from untrusted upstream JSON."""
    return label(str(value or "").strip(), _METADATA_LIMIT)


def _owner_name(document: dict[str, Any]) -> str:
    owner = document.get("owner")
    return _text(owner.get("name")) if isinstance(owner, dict) else ""


def _retry_wait(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retrying a 429. Honors Retry-After when it is a
    plain integer, falls back to exponential backoff — capped either way,
    because the header is untrusted upstream input (CLAUDE.md §7)."""
    header = response.headers.get("Retry-After", "").strip()
    wait = float(header) if header.isdigit() else _RATE_LIMIT_BACKOFF_SECONDS * (2**attempt)
    return min(wait, _RATE_LIMIT_MAX_WAIT_SECONDS)


def _safe_upstream_id(value: str) -> str:
    if not _UPSTREAM_ID_RE.fullmatch(value):
        raise ConnectorError("export_unavailable", "Onshape returned an unusable resource id")
    return value


class OnshapeConnector(OAuthConnector):
    """Thin-API CAD connector: fetch a STEP export, parse it with the shared
    mechanical parser, enrich part numbers from Onshape's parts metadata."""

    provider: ClassVar[str] = "onshape"
    #: READ ONLY. Every operation here is a read — the translation POST sets
    #: `storeInDocument: False` precisely so it writes nothing to the customer's
    #: document. Requesting write scope would mean a leaked Solus token could
    #: modify or destroy live CAD, for no capability we use. If a live run shows
    #: `/translations` rejects a read-only token, record that evidence in
    #: `docs/integrations/onshape-setup.md` before widening this.
    scopes: ClassVar[tuple[str, ...]] = ("OAuth2Read",)
    #: SOLUS-ONS-A2. Editing CAD is the product, so the capability is offered
    #: rather than withheld — but an Onshape grant is ACCOUNT-WIDE (verified:
    #: there is no per-document, per-workspace or per-company scope, and no
    #: share-with-app mechanism), so the customer chooses at connect time.
    #: `OAuth2Delete` is deliberately never requested: it covers destroying
    #: documents and workspaces, while feature and instance deletion are both
    #: `OAuth2Write` — so it buys nothing and would let a confused agent wipe a
    #: customer's document.
    access_modes: ClassVar[dict[str, Any] | None] = {
        "default": "read",
        "modes": [
            {
                "id": "read",
                "label": "Read only",
                "description": "Solus can read your documents and export geometry.",
                "scopes": ["OAuth2Read"],
            },
            {
                "id": "write",
                "label": "Read and edit",
                "description": (
                    "Solus can also change your models. Every edit is shown to you "
                    "for approval before it is applied."
                ),
                "scopes": ["OAuth2Read", "OAuth2Write"],
            },
        ],
    }
    #: EMPTY, and deliberately so. The OAuth grant is ACCOUNT-level, so nothing
    #: has to be typed in to connect: authorize once, then pick documents from
    #: the account (`list_selectable`). The picked ids live in config under
    #: `SELECTION_KEY`, which is a SELECTION rather than user-entered config —
    #: `config_fields` drives the app's typed-config form, and Onshape must not
    #: show one. (CAD-01 required a document/workspace/element triple here; that
    #: shape is still accepted, see `_legacy_target`.)
    config_fields: ClassVar[tuple[str, ...]] = ()
    #: How the app lets a user choose what to track. Read generically by the
    #: catalog, so a new CAD connector needs no frontend change.
    selection: ClassVar[dict[str, str]] = {
        "mode": "multi",
        "config_key": SELECTION_KEY,
        "label": "document",
    }
    #: OAuth-only: an API key pair could only ever read OUR documents.
    supports_token_connect: ClassVar[bool] = False

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        poll_attempts: int = 30,
        poll_interval: float = 1.0,
        max_documents: int = _MAX_DOCUMENTS,
        max_elements: int = _MAX_ELEMENTS,
        max_document_pages: int = _MAX_DOCUMENT_PAGES,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._poll_attempts = poll_attempts
        self._poll_interval = poll_interval
        self._max_documents = max_documents
        self._max_elements = max_elements
        self._max_document_pages = max_document_pages

    # ----------------------------------------------------------- oauth

    def authorize_url(self, *, state: str, redirect_uri: str, access: str | None = None) -> str:
        if not self._client_id:
            raise ConnectorError("oauth_not_configured", "Onshape OAuth is not configured")
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(self.scopes_for(access)),
                "state": state,
            }
        )
        return f"{ONSHAPE_OAUTH_BASE}/oauth/authorize?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> Credentials:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            failure_code="oauth_exchange_failed",
        )

    async def refresh_credentials(self, creds: Credentials) -> Credentials:
        if not creds.refresh_token:
            raise ConnectorError("oauth_refresh_failed", "no stored Onshape refresh token")
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": creds.refresh_token},
            failure_code="oauth_refresh_failed",
        )

    async def _token_request(self, form: dict[str, str], *, failure_code: str) -> Credentials:
        if not self._client_id or not self._client_secret:
            raise ConnectorError("oauth_not_configured", "Onshape OAuth is not configured")
        payload = {**form, "client_id": self._client_id, "client_secret": self._client_secret}
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                response = await client.post(f"{ONSHAPE_OAUTH_BASE}/oauth/token", data=payload)
        except httpx.HTTPError as exc:
            raise ConnectorError(failure_code, "could not reach Onshape's token endpoint") from exc
        if response.status_code >= 400:
            raise ConnectorError(
                failure_code, f"Onshape rejected the token request ({response.status_code})"
            )
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise ConnectorError(failure_code, "Onshape returned no access token")
        # The rotated refresh token MUST travel back: Onshape issues a new one on
        # every refresh and invalidates the old, so dropping it breaks the chain.
        return Credentials(token=token, refresh_token=body.get("refresh_token"))

    # ----------------------------------------------------------- identity

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        """Identify the authorized account.

        `OAuth2Read` alone carries NO PII: `sessioninfo` returns `email`/`name`
        as empty, and only the opaque user `id` is populated (confirmed against a
        live tenant — `oauth2Scopes: 1`). The old fallback invented the string
        "onshape-user", which then became the source's display name and told the
        user nothing about which account they had connected. Fall back to the
        real account id instead: opaque, but true and distinguishable. Widening
        to the PII scope for a nicer label is deliberately NOT done —
        `docs/integrations/onshape-setup.md` §2 forbids it.
        """
        async with self.http(creds) as client:
            body = await self.get_json(client, "/api/users/sessioninfo", what="session info")
        external_id = _text(body.get("id"))
        return AccountInfo(
            external_id=external_id,
            # `login` must be non-empty (connector conformance), so the id is the
            # last resort rather than a fabricated name.
            login=_text(body.get("email")) or _text(body.get("name")) or external_id or "onshape",
            name=_text(body.get("name")) or None,
        )

    # ----------------------------------------------------------- sync

    async def detect_changes(self, ctx: SyncContext) -> bool:
        """Cheap probe on each tracked document's MICROVERSION — Onshape's own
        change token. There is no account-level change feed, so this is one probe
        per selected document, bounded by the selection cap.

        A change to the SELECTION itself counts as changed, so newly picked
        documents are ingested and deselected ones are reconciled away.

        Fails SAFE: an unreachable API counts as changed, so a transient outage
        schedules a sync rather than silently skipping one.
        """
        try:
            document_ids = self._selected_document_ids(ctx)
            stored = self._stored_microversions(ctx, document_ids)
            if set(stored) != set(document_ids):
                return True
            async with self.http(ctx.credentials) as client:
                for document_id in document_ids:
                    current = await self._probe(client, ctx, document_id)
                    if current != stored.get(document_id):
                        return True
        except ConnectorError:
            return True
        return False

    async def sync(self, ctx: SyncContext) -> SyncResult:
        """Ingest every tracked document. One source now spans many documents, so
        each element's entities are namespaced by `(document, element)`.

        Partial-failure rule: `apply_sync_result` treats a result as a COMPLETE
        snapshot and soft-deletes anything absent from it, so a document that
        merely failed to fetch must never be silently omitted — that would
        tombstone its whole subtree. Only a document Onshape reports as GONE
        (404) is dropped, which is exactly the case where tombstoning is right.
        Every other failure aborts the sync and leaves the graph untouched.
        """
        recorder = ErrorRecorder()
        entities: list[Any] = []
        relations: list[Any] = []
        microversions: dict[str, str] = {}

        async with self.http(ctx.credentials) as client:
            targets, workspaces = await self._resolve_targets(client, ctx, recorder)
            # A cursor entry for EVERY selected document, including ones that hold
            # no assemblies and ones that are gone. `detect_changes` compares the
            # cursor's key set with the selection, so a document missing an entry
            # would read as "selection changed" on every poll — an endless
            # re-sync loop.
            for document_id in self._selected_document_ids(ctx):
                workspace_id = workspaces.get(document_id)
                microversions[document_id] = (
                    _GONE
                    if workspace_id is None
                    else await self._current_microversion(client, document_id, workspace_id)
                )
            for target in targets:
                target_entities, target_relations = await self._ingest(client, target, recorder)
                entities.extend(target_entities)
                relations.extend(target_relations)

        return SyncResult(
            entities=entities,
            relations=relations,
            cursor={"microversions": microversions},
            errors=recorder.finish(),
        )

    async def _ingest(
        self, client: httpx.AsyncClient, target: _Target, recorder: ErrorRecorder
    ) -> tuple[list[Any], list[Any]]:
        """One element → graph records, namespaced to its document."""
        export = await self._fetch_step(
            client, target.document_id, target.workspace_id, target.element_id
        )
        metadata = await self._fetch_part_metadata(
            client, target.document_id, target.workspace_id, target.element_id, recorder
        )
        model = self._enrich(parse_step(export), metadata)
        # ONE recorder across every stage and every document, so the
        # MAX_SYNC_ERRORS bound is the documented per-sync cap rather than one
        # cap per document silently multiplied by the selection size.
        target_entities, target_relations, _ = build_mechanical_graph(
            model, recorder, scope=target.scope, provenance=target.provenance
        )
        return target_entities, target_relations

    # ----------------------------------------------------------- selection

    def _selected_document_ids(self, ctx: SyncContext) -> list[str]:
        """The tracked document ids. Empty is VALID — a connected, idle source.

        Ingested config is untrusted (CLAUDE.md §7): every id is validated before
        it can reach a request path, and the list is bounded.
        """
        legacy = self._legacy_target(ctx)
        if legacy is not None:
            return [legacy.document_id]

        raw = ctx.config.get(SELECTION_KEY, [])
        if not isinstance(raw, list):
            raise ConnectorError("config_invalid", f"{SELECTION_KEY} must be a list of Onshape ids")
        if len(raw) > self._max_documents:
            raise ConnectorError(
                "config_invalid", f"at most {self._max_documents} documents can be tracked"
            )
        for value in raw:
            if not isinstance(value, str) or not _ID_RE.fullmatch(value):
                raise ConnectorError(
                    "config_invalid",
                    f"{SELECTION_KEY} entries must be Onshape ids (letters and digits only)",
                )
        return list(raw)

    def _legacy_target(self, ctx: SyncContext) -> _Target | None:
        """CAD-01 config named ONE element by its three ids. Read-time shim: such
        a source keeps working, pinned to exactly that element, until it is
        re-picked. A new-style selection always wins."""
        if ctx.config.get(SELECTION_KEY) is not None:
            return None
        values = []
        for field_name in _LEGACY_KEYS:
            raw = ctx.config.get(field_name)
            if raw is None:
                return None
            if not isinstance(raw, str) or not _ID_RE.fullmatch(raw):
                raise ConnectorError(
                    "config_invalid",
                    f"{field_name} must be an Onshape id (letters and digits only)",
                )
            values.append(raw)
        return _Target(document_id=values[0], workspace_id=values[1], element_id=values[2])

    def _stored_microversions(self, ctx: SyncContext, document_ids: list[str]) -> dict[str, str]:
        """The per-document change cursor, reading the CAD-01 scalar cursor as a
        one-document map so a legacy source doesn't re-sync needlessly."""
        stored = ctx.cursor.get("microversions")
        if isinstance(stored, dict):
            return {k: str(v) for k, v in stored.items()}
        legacy = ctx.cursor.get("microversion")
        if isinstance(legacy, str) and len(document_ids) == 1:
            return {document_ids[0]: legacy}
        return {}

    async def _resolve_targets(
        self, client: httpx.AsyncClient, ctx: SyncContext, recorder: ErrorRecorder
    ) -> tuple[list[_Target], dict[str, str]]:
        """Expand the selection into exportable elements: each document's default
        workspace, then every assembly in it.

        Also returns the resolved workspace per document — including documents
        that hold no assemblies — so the caller can cursor every live document.
        A document absent from that map is GONE.
        """
        legacy = self._legacy_target(ctx)
        if legacy is not None:
            return [legacy], {legacy.document_id: legacy.workspace_id}

        targets: list[_Target] = []
        workspaces: dict[str, str] = {}
        for document_id in self._selected_document_ids(ctx):
            try:
                workspace_id = await self.default_workspace(client, document_id)
                element_ids = await self._assembly_elements(client, document_id, workspace_id)
            except ConnectorError as exc:
                if exc.code != "not_found":
                    raise
                # Deleted upstream: dropping it (and letting its entities be
                # reconciled away) is the correct reading of "gone".
                recorder.record(label(document_id), "document is no longer available; skipped")
                continue
            workspaces[document_id] = workspace_id
            for element_id in element_ids:
                if len(targets) >= self._max_elements:
                    recorder.record(
                        "selection",
                        f"more than {self._max_elements} assemblies selected; rest skipped",
                    )
                    return targets, workspaces
                targets.append(
                    _Target(
                        document_id=document_id,
                        workspace_id=workspace_id,
                        element_id=element_id,
                    )
                )
        return targets, workspaces

    async def _probe(self, client: httpx.AsyncClient, ctx: SyncContext, document_id: str) -> str:
        """This document's current change token, or `_GONE` when Onshape no
        longer has it — matching what `sync` records, so a deleted document that
        is still selected settles instead of scheduling a sync forever."""
        try:
            legacy = self._legacy_target(ctx)
            workspace_id = (
                legacy.workspace_id
                if legacy is not None
                else await self.default_workspace(client, document_id)
            )
            return await self._current_microversion(client, document_id, workspace_id)
        except ConnectorError as exc:
            if exc.code != "not_found":
                raise
            return _GONE

    async def default_workspace(self, client: httpx.AsyncClient, document_id: str) -> str:
        body = await self.get_json(client, f"/api/v6/documents/{document_id}", what="document")
        workspace = body.get("defaultWorkspace") if isinstance(body, dict) else None
        raw = workspace.get("id", "") if isinstance(workspace, dict) else ""
        if not isinstance(raw, str) or not _ID_RE.fullmatch(raw):
            raise ConnectorError("api_error", "Onshape returned no usable default workspace")
        return raw

    async def _assembly_elements(
        self, client: httpx.AsyncClient, document_id: str, workspace_id: str
    ) -> list[str]:
        body = await self.get_json(
            client,
            f"/api/v6/documents/d/{document_id}/w/{workspace_id}/elements",
            what="document elements",
            params={"elementType": "ASSEMBLY"},
        )
        element_ids: list[str] = []
        for element in body if isinstance(body, list) else []:
            if not isinstance(element, dict):
                continue
            raw = element.get("id", "")
            if isinstance(raw, str) and _ID_RE.fullmatch(raw):
                element_ids.append(raw)
        return element_ids

    async def list_selectable(self, creds: Credentials) -> list[dict[str, Any]]:
        """Documents the authorized account can reach, for the app's picker.

        Bounded: paging follows Onshape's `next` link, but never unboundedly
        against a third-party API (§7).
        """
        items: list[dict[str, Any]] = []
        async with self.http(creds) as client:
            path: str | None = "/api/v6/documents"
            params: dict[str, Any] | None = {"limit": _PAGE_LIMIT}
            for _ in range(self._max_document_pages):
                if path is None:
                    break
                body = await self.get_json(client, path, what="documents", params=params)
                if not isinstance(body, dict):
                    break
                for document in body.get("items") or []:
                    if not isinstance(document, dict):
                        continue
                    raw = document.get("id", "")
                    if not isinstance(raw, str) or not _ID_RE.fullmatch(raw):
                        continue
                    items.append(
                        {
                            "id": raw,
                            "name": _text(document.get("name")) or raw,
                            "subtitle": _owner_name(document),
                        }
                    )
                    if len(items) >= self._max_documents:
                        return items
                next_link = body.get("next")
                path = next_link if isinstance(next_link, str) and next_link else None
                params = None
        return items

    # ----------------------------------------------------------- acquisition

    async def _current_microversion(
        self, client: httpx.AsyncClient, document_id: str, workspace_id: str
    ) -> str:
        body = await self.get_json(
            client,
            f"/api/v6/documents/d/{document_id}/w/{workspace_id}/currentmicroversion",
            what="current microversion",
        )
        return str(body.get("microversion", ""))

    async def _fetch_step(
        self,
        client: httpx.AsyncClient,
        document_id: str,
        workspace_id: str,
        element_id: str,
    ) -> str:
        """Onshape's async translation dance: request → poll → download."""
        started = await self.post_json(
            client,
            f"/api/v6/assemblies/d/{document_id}/w/{workspace_id}/e/{element_id}/translations",
            {"formatName": _EXPORT_FORMAT, "storeInDocument": False},
            what="STEP translation request",
        )
        request_id = _safe_upstream_id(str(started.get("id", "")))

        external_id = _safe_upstream_id(await self._poll_translation(client, request_id))
        return await self._download_bounded(
            client, f"/api/v6/documents/d/{document_id}/externaldata/{external_id}"
        )

    async def _download_bounded(self, client: httpx.AsyncClient, path: str) -> str:
        """Stream the export, aborting the moment it exceeds the cap.

        Buffering first and measuring after cannot work: the bound exists to stop
        a huge body exhausting the worker, and by the time `response.content` is
        populated the damage is done. A trickling response would also never trip
        httpx's per-read timeout, so the whole download carries a hard deadline
        — covering the 429 retry waits too, so retries can never stretch the
        download past it.
        """
        try:
            async with asyncio.timeout(_DOWNLOAD_DEADLINE_SECONDS):
                for attempt in range(_RATE_LIMIT_RETRIES + 1):
                    async with client.stream("GET", path) as response:
                        if response.status_code != 429:
                            return await self._read_export(response)
                        wait = _retry_wait(response, attempt)
                    if attempt < _RATE_LIMIT_RETRIES:
                        await asyncio.sleep(wait)
        except TimeoutError as exc:
            raise ConnectorError("export_timeout", "the STEP download did not complete") from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(
                "api_unreachable", "could not reach Onshape for the export"
            ) from exc
        raise ConnectorError(
            "rate_limited", "Onshape's rate limit outlasted every retry of the STEP download"
        )

    @staticmethod
    async def _read_export(response: httpx.Response) -> str:
        """One download attempt's body, bounded as it streams."""
        if response.status_code in (401, 403):
            raise ConnectorError("invalid_credentials", "Onshape rejected the credentials")
        if response.status_code >= 400:
            raise ConnectorError(
                "api_error", f"Onshape returned {response.status_code} for STEP download"
            )
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_CAD_EXPORT_BYTES:
            raise ConnectorError("export_too_large", _TOO_LARGE)
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_CAD_EXPORT_BYTES:
                raise ConnectorError("export_too_large", _TOO_LARGE)
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", "replace")

    async def _poll_translation(self, client: httpx.AsyncClient, request_id: str) -> str:
        """Bounded poll — never an unbounded loop against a third-party API (§7)."""
        for attempt in range(self._poll_attempts):
            body = await self.get_json(
                client, f"/api/v8/translations/{request_id}", what="translation status"
            )
            state = str(body.get("requestState", ""))
            if state == "DONE":
                ids = body.get("resultExternalDataIds") or []
                if not ids:
                    raise ConnectorError(
                        "export_unavailable",
                        "Onshape reported a finished translation with no result",
                    )
                return str(ids[0])
            if state == "FAILED":
                raise ConnectorError(
                    "export_unavailable",
                    f"Onshape could not translate the element to {_EXPORT_FORMAT}",
                )
            if attempt + 1 < self._poll_attempts:
                await asyncio.sleep(self._poll_interval)
        raise ConnectorError(
            "export_timeout",
            f"Onshape did not finish the {_EXPORT_FORMAT} translation in time",
        )

    async def _fetch_part_metadata(
        self,
        client: httpx.AsyncClient,
        document_id: str,
        workspace_id: str,
        element_id: str,
        recorder: ErrorRecorder,
    ) -> dict[str, tuple[str | None, str | None]]:
        """Part number + material per part NAME.

        Enrichment, not structure: if this call fails the team still gets their
        assembly tree, with the loss recorded on the Sync row.
        """
        try:
            body = await self.get_json(
                client,
                f"/api/v6/parts/d/{document_id}/w/{workspace_id}/e/{element_id}",
                what="part metadata",
            )
        except ConnectorError as exc:
            recorder.record(
                "metadata", f"part metadata unavailable ({exc.code}); part numbers skipped"
            )
            return {}

        table: dict[str, tuple[str | None, str | None]] = {}
        for part in body if isinstance(body, list) else []:
            if not isinstance(part, dict):
                continue
            name = label(str(part.get("name", "")).strip(), _METADATA_LIMIT)
            if not name:
                continue
            raw_number = str(part.get("partNumber", "")).strip()
            number = label(raw_number, _METADATA_LIMIT) if raw_number else None
            material_block = part.get("material")
            material = None
            if isinstance(material_block, dict):
                raw_material = str(material_block.get("displayName", "")).strip()
                material = label(raw_material, _METADATA_LIMIT) if raw_material else None
            table[name] = (number, material)
        return table

    @staticmethod
    def _enrich(model: CadModel, metadata: dict[str, tuple[str | None, str | None]]) -> CadModel:
        """Graft Onshape part numbers onto the STEP product structure.

        STEP has no MPN slot (see `test_step_carries_no_part_numbers`), so this
        join is what lets a CAD part ever collapse onto its schematic symbol in
        the fingerprint. Missing metadata leaves the node untouched — a part
        number is never invented from a CAD id.
        """
        if not metadata:
            return model
        nodes: list[CadNode] = []
        for node in model.nodes:
            number, material = metadata.get(node.name, (None, None))
            if number is None and material is None:
                nodes.append(node)
                continue
            nodes.append(dataclasses.replace(node, part_number=number, material=material))
        return CadModel(nodes=tuple(nodes), warnings=model.warnings)

    # ----------------------------------------------------------- http

    @staticmethod
    def http(creds: Credentials) -> httpx.AsyncClient:
        """An authenticated Onshape client. PUBLIC (SOLUS-ONS-A1): the operations
        layer and the SOL tool path reuse this rather than growing a second auth
        path — there is exactly one way to talk to Onshape as a customer."""
        return httpx.AsyncClient(
            base_url=ONSHAPE_API_BASE,
            timeout=_REQUEST_TIMEOUT,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {creds.token}",
            },
        )

    async def request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        what: str,
        # A list, not just an object: Onshape's variable endpoint takes a bare
        # JSON array as its whole body.
        json_body: dict[str, Any] | list[Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                response = await client.request(method, path, json=json_body, params=params)
            except httpx.HTTPError as exc:
                raise ConnectorError(
                    "api_unreachable", f"could not reach Onshape for {what}"
                ) from exc
            if response.status_code != 429:
                break
            if attempt < _RATE_LIMIT_RETRIES:
                await asyncio.sleep(_retry_wait(response, attempt))
        if response.status_code == 429:
            raise ConnectorError(
                "rate_limited", f"Onshape's rate limit outlasted every retry of the {what}"
            )
        if response.status_code in (401, 403):
            # The exact code `runtime._sync_with_refresh` keys off to refresh
            # the 60-minute token and retry once.
            raise ConnectorError("invalid_credentials", "Onshape rejected the credentials")
        if response.status_code == 404:
            # Distinct from a generic api_error: a tracked document that is GONE
            # is dropped from the sync, and only a 404 may be read that way —
            # every other failure aborts rather than tombstoning live entities.
            raise ConnectorError("not_found", f"Onshape has no {what}")
        if response.status_code >= 400:
            # Upstream text is untrusted and may echo request material — never
            # surface it; the status and our own label are enough to debug.
            raise ConnectorError("api_error", f"Onshape returned {response.status_code} for {what}")
        return response

    async def get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        what: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await self.request(client, "GET", path, what=what, params=params)
        return self._json(response, what)

    async def post_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        body: dict[str, Any] | list[Any],
        *,
        what: str,
    ) -> Any:
        response = await self.request(client, "POST", path, what=what, json_body=body)
        return self._json(response, what)

    @staticmethod
    def _json(response: httpx.Response, what: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError(
                "api_error", f"Onshape returned malformed JSON for {what}"
            ) from exc


__all__ = [
    "ONSHAPE_API_BASE",
    "ONSHAPE_ID_RE",
    "ONSHAPE_MAX_PAGE_LIMIT",
    "ONSHAPE_OAUTH_BASE",
    "SELECTION_KEY",
    "OnshapeConnector",
    "SyncError",
]
