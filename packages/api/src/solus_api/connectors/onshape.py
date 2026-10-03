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
import hashlib
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx

from solus_api.connectors.contracts import (
    AccountInfo,
    ConnectorError,
    Credentials,
    EntityOut,
    OAuthConnector,
    RelationOut,
    SyncContext,
    SyncError,
    SyncResult,
)
from solus_api.connectors.document_graph import document_contains, document_root
from solus_api.connectors.export_common import ErrorRecorder, label
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.mechanical import (
    MAX_CAD_EXPORT_BYTES,
    CadModel,
    CadNode,
    build_mechanical_graph,
)
from solus_api.connectors.quota import CallMeter, QuotaBlockedError
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


def element_base_path(kind: str, document_id: str, workspace_id: str, element_id: str) -> str:
    """The `/{kind}/d/{did}/w/{wid}/e/{eid}` prefix every element call hangs off.

    `kind` is the Onshape collection for the element's family — "assemblies" or
    "partstudios". Lives here, not in `onshape_ops`, because that module already
    imports from this one; the dependency runs one way.
    """
    return f"/api/v6/{kind}/d/{document_id}/w/{workspace_id}/e/{element_id}"


_REQUEST_TIMEOUT = 30.0
#: Onshape rate-caps private OAuth apps, and one sync fires a translation job
#: per assembly plus ~1/s status polls — so a 429 is an expected operating
#: condition, not a failure. Retries are bounded (§7: never an unbounded loop
#: against a third-party API). Retry-After is honored; waits beyond the worker
#: bound fail without retrying early or parking a sync worker.
#: SOLUSDEV-167: was 3 (four attempts). Two ladders hang off this — `request`
#: and `_download_bounded` — so one export's worst case was 16 attempts against
#: a provider already telling us to stop. Against an ANNUAL quota, retrying into
#: a 429 storm buys nothing a later sync would not get for free.
_RATE_LIMIT_RETRIES = 1
_RATE_LIMIT_MAX_WAIT_SECONDS = 30.0
_RATE_LIMIT_BACKOFF_SECONDS = 1.0
#: httpx's timeout is per-read, so a slow trickle never trips it. The download
#: carries its own total deadline on top.
_DOWNLOAD_DEADLINE_SECONDS = 300.0
#: The translation poll's own deadline. `_DOWNLOAD_DEADLINE_SECONDS` covers the
#: download only, so before SOLUSDEV-167 the poll loop had none at all.
_POLL_DEADLINE_SECONDS = 45.0
_POLL_MAX_INTERVAL_SECONDS = 8.0
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
# Reparse existing revision-keyed exports when the graph projection changes.
PROJECTION_VERSION = "cad-geometry-v3"

#: Cursor key holding the resolved default workspace per document (SOLUSDEV-167).
#: Lives beside the microversions rather than in a cache — see `_probe`.
WORKSPACES_KEY = "workspaces"

#: Cursor value for a tracked document Onshape no longer has. Recorded so the
#: selection and the cursor keep the same key set — otherwise `detect_changes`
#: would report "changed" on every poll and re-sync forever.
_GONE = "__gone__"

#: Legacy per-source config from CAD-01, when a source named ONE element.
_LEGACY_KEYS = ("document_id", "workspace_id", "element_id")

#: The element families the mechanical parser can read, mapped to the Onshape
#: collection their translation hangs off. A document also holds drawings, BOMs
#: and blobs; exporting those would spend a translation job to fail.
_ASSEMBLIES = "assemblies"
EXPORTABLE_COLLECTIONS: dict[str, str] = {"ASSEMBLY": _ASSEMBLIES, "PARTSTUDIO": "partstudios"}

#: ADR-038 §3 — the in-document elements an export may depend on. A Part Studio
#: derives from other Part Studios and Variable Studios; an assembly additionally
#: instantiates other assemblies. Drawings, blobs and app elements never feed an
#: export, so editing one must not invalidate it.
_STUDIO_TYPES = frozenset({"PARTSTUDIO", "VARIABLESTUDIO"})
_ASSEMBLY_TYPE = "ASSEMBLY"
_TRACKED_TYPES = _STUDIO_TYPES | {_ASSEMBLY_TYPE}
#: Export-key fingerprint used when the listing carries no usable per-element
#: microversion: the key then degrades to document granularity (the old, safe one).
_DOCUMENT_KEYED = "doc"
#: How long a probe's observation may be handed to the plan of the SAME sync.
_OBSERVATION_TTL_SECONDS = 120.0

#: Bounds on an account-level sync. Onshape rate-caps a private OAuth app, and
#: each element costs a translation job — so both the selection and the expanded
#: element set are bounded rather than "whatever the account holds".
_MAX_DOCUMENTS = 50
_MAX_ELEMENTS = 256
_MAX_STAGED_RECORDS = 100_000
_MAX_STAGED_BYTES = 64 * 1024 * 1024
_MAX_DOCUMENT_PAGES = 10
#: Onshape CAPS `limit` at 20 on /documents and answers 400 for anything higher
#: — confirmed against a live tenant, which is what the fixtures could not tell
#: us (`docs/integrations/onshape-setup.md` §9). Paging covers the rest.
_PAGE_LIMIT = 20
#: Onshape's own ceiling for that parameter; the request must never exceed it.
ONSHAPE_MAX_PAGE_LIMIT = 20


class _StagingBudget:
    """Bound complete graph staging independently of the per-element CAD parse cap."""

    def __init__(self, records: int, byte_count: int) -> None:
        self.records_left = records
        self.bytes_left = byte_count

    def consume(self, records: list[EntityOut] | list[RelationOut]) -> None:
        if len(records) > self.records_left:
            raise ConnectorError(
                "selection_too_large", "Complete graph exceeds the staged record limit"
            )
        for record in records:
            self.bytes_left -= len(record.model_dump_json().encode("utf-8"))
            if self.bytes_left < 0:
                raise ConnectorError(
                    "selection_too_large", "Complete graph exceeds the staged byte limit"
                )
        self.records_left -= len(records)


def _document_page_url(path: str) -> httpx.URL:
    """Accept vendor pagination only on the trusted document-list endpoints."""
    base = httpx.URL(ONSHAPE_API_BASE)
    try:
        url = base.join(path)
    except httpx.InvalidURL as exc:
        raise ConnectorError("api_error", "Onshape returned an invalid document page") from exc
    if (
        (url.scheme, url.host, url.port) != (base.scheme, base.host, base.port)
        or url.userinfo
        or url.fragment
        or url.path not in {"/api/v6/documents", "/api/documents"}
    ):
        raise ConnectorError("api_error", "Onshape returned an unsafe document page")
    return url


def _raise_for_status(response: httpx.Response, what: str) -> None:
    """Map an Onshape status onto the connector's error vocabulary.

    Split out of `request` so the retry/metering mechanics and the status
    taxonomy can each be read on their own.
    """
    if response.status_code < 400:
        return
    if response.status_code == 429:
        raise ConnectorError(
            "rate_limited", f"Onshape's rate limit outlasted every retry of the {what}"
        )
    if response.status_code in (401, 403):
        # The exact code `runtime._sync_with_refresh` keys off to refresh
        # the 60-minute token and retry once.
        raise ConnectorError("invalid_credentials", "Onshape rejected the credentials")
    if response.status_code == 402:
        # SOLUSDEV-167. Onshape answers 402 when the account's ANNUAL call
        # allowance is spent. It had no branch here, so it read as a generic
        # api_error — which `detect_changes` then swallowed into "changed",
        # enqueuing a full sync. Being out of quota must never buy MORE
        # requests, so it gets its own terminal code.
        raise ConnectorError("quota_exhausted", "the Onshape account's API allowance is exhausted")
    if response.status_code == 404:
        # Distinct from a generic api_error: a tracked document that is GONE is
        # dropped from the sync, and only a 404 may be read that way — every
        # other failure aborts rather than tombstoning live entities.
        raise ConnectorError("not_found", f"Onshape has no {what}")
    if response.status_code == 400:
        raise _BadRequestError("api_error", f"Onshape returned 400 for {what}")
    # Upstream text is untrusted and may echo request material — never surface
    # it; the status and our own label are enough to debug.
    raise ConnectorError("api_error", f"Onshape returned {response.status_code} for {what}")


@dataclasses.dataclass(frozen=True)
class _Target:
    """One exportable assembly: the (document, workspace, element) triple the
    translation API needs."""

    document_id: str
    workspace_id: str
    element_id: str
    #: Which Onshape collection this element exports through — "assemblies" or
    #: "partstudios". Only Part Studios support the optional parts metadata
    #: enrichment; both collections share STEP parsing and graph projection.
    collection: str = _ASSEMBLIES
    #: ADR-038 §3 export-cache identity: this element's own microversion and a
    #: fingerprint of the in-document elements it may depend on. None when the
    #: listing did not carry them (the export is then keyed by the document).
    revision: str | None = None
    fingerprint: str | None = None

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


@dataclasses.dataclass(frozen=True)
class _DocumentPlan:
    """One selected document, resolved: where it lives, which version it is
    at, and the elements to export. `workspace_id` is None and `microversion`
    is `_GONE` for a document Onshape no longer has."""

    document_id: str
    workspace_id: str | None
    microversion: str
    targets: list[_Target]


def _fingerprint(domain: str, elements: list[tuple[str, str]]) -> str | None:
    """sha256 over the sorted `(element_id, microversion)` pairs an export may depend
    on, or None when any pair lacks a microversion (the caller then keys by document)."""
    if any(not micro for _, micro in elements):
        return None
    digest = hashlib.sha256(domain.encode())
    for element_id, micro in sorted(elements):
        digest.update(f"\n{element_id}:{micro}".encode())
    return digest.hexdigest()


def _text(value: Any) -> str:
    """A bounded display string from untrusted upstream JSON."""
    return label(str(value or "").strip(), _METADATA_LIMIT)


def _owner_name(document: dict[str, Any]) -> str:
    owner = document.get("owner")
    return _text(owner.get("name")) if isinstance(owner, dict) else ""


def _retry_wait(response: httpx.Response, attempt: int) -> float:
    """Honor the server's minimum delay or defer the operation without retrying."""
    header = response.headers.get("Retry-After", "").strip()
    wait: float | None = None
    if header.isascii() and header.isdigit():
        wait = float(header)
    elif header:
        try:
            deadline = parsedate_to_datetime(header)
            if deadline.tzinfo is not None:
                wait = max(0.0, (deadline - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    if wait is None:
        ceiling = min(_RATE_LIMIT_BACKOFF_SECONDS * (2**attempt), _RATE_LIMIT_MAX_WAIT_SECONDS)
        wait = random.uniform(ceiling / 2, ceiling)  # noqa: S311 — scheduling jitter, not a secret
    if wait > _RATE_LIMIT_MAX_WAIT_SECONDS:
        raise ConnectorError("rate_limited", "Onshape requested a longer wait; try again later.")
    return wait


class _BadRequestError(ConnectorError):
    """Typed HTTP 400, retaining the public connector error taxonomy."""


class _RejectedTranslationError(ConnectorError):
    """A translation submission was rejected before an export was created."""


class _InvalidExportResourceError(ConnectorError):
    """Malformed vendor identity must never be reinterpreted as empty geometry."""


def _safe_upstream_id(value: str) -> str:
    if not _UPSTREAM_ID_RE.fullmatch(value):
        raise _InvalidExportResourceError(
            "export_unavailable", "Onshape returned an unusable resource id"
        )
    return value


def tracked_document_ids(
    config: Mapping[str, Any], *, max_documents: int = _MAX_DOCUMENTS
) -> list[str]:
    """The Onshape documents a source tracks. Empty is VALID — a connected, idle source.

    THE one definition of that predicate, because it is now a security boundary
    and not only a sync input: `agent/tools/onshape_tools.py` refuses any tool
    call naming a document outside this list, so a second, weaker copy of the
    rule would be a way around the refusal.

    Ingested config is untrusted (CLAUDE.md §7): every id is validated before it
    can reach a request path, and the list is bounded. Anything malformed raises
    rather than being skipped — a source whose selection cannot be read must not
    silently read as "tracks nothing", which would look identical to a source
    that legitimately tracks nothing.
    """
    legacy = _legacy_document_id(config)
    if legacy is not None:
        return [legacy]
    raw = config.get(SELECTION_KEY, [])
    if not isinstance(raw, list):
        raise ConnectorError("config_invalid", f"{SELECTION_KEY} must be a list of Onshape ids")
    if len(raw) > max_documents:
        raise ConnectorError("config_invalid", f"at most {max_documents} documents can be tracked")
    for value in raw:
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise ConnectorError(
                "config_invalid",
                f"{SELECTION_KEY} entries must be Onshape ids (letters and digits only)",
            )
    return list(raw)


def _legacy_document_id(config: Mapping[str, Any]) -> str | None:
    """CAD-01 config named ONE element by its three ids. A new-style selection
    always wins; such a source keeps working until it is re-picked."""
    if config.get(SELECTION_KEY) is not None:
        return None
    value = config.get("document_id")
    return value if isinstance(value, str) and _ID_RE.fullmatch(value) else None


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
    supports_document_tree: ClassVar[bool] = True

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        poll_attempts: int = 10,
        poll_interval: float = 1.0,
        max_documents: int = _MAX_DOCUMENTS,
        max_elements: int = _MAX_ELEMENTS,
        max_staged_records: int = _MAX_STAGED_RECORDS,
        max_staged_bytes: int = _MAX_STAGED_BYTES,
        max_document_pages: int = _MAX_DOCUMENT_PAGES,
        meter: CallMeter | None = None,
        cache: IntegrationCache | None = None,
        account_ref: str | None = None,
        signal_max_age_seconds: float | None = None,
    ) -> None:
        self.scene_export_observer: Callable[[str, str, str, str], None] | None = None
        self._client_id = client_id
        self._client_secret = client_secret
        self._poll_attempts = poll_attempts
        self._poll_interval = poll_interval
        self._max_documents = max_documents
        for name, value, cap in (
            ("max_elements", max_elements, _MAX_ELEMENTS),
            ("max_staged_records", max_staged_records, _MAX_STAGED_RECORDS),
            ("max_staged_bytes", max_staged_bytes, _MAX_STAGED_BYTES),
        ):
            if type(value) is not int or not 1 <= value <= cap:
                raise ValueError(f"{name} must be an integer between 1 and {cap}")
        self._max_elements = max_elements
        self._max_staged_records = max_staged_records
        self._max_staged_bytes = max_staged_bytes
        self._max_document_pages = max_document_pages
        # SOLUSDEV-167. Defaulted to None so every existing construction —
        # tests, the picker, the plain registry factory — keeps working
        # unmetered; the scoped factory supplies a real one.
        self._meter = meter
        # SOLUSDEV-241. The integration cache, keyed on the ACCOUNT whose
        # credentials this connector holds, and how old a recorded change
        # signal may be before this caller must ask Onshape again (`None`:
        # always ask — the webhook posture). Same opt-in as the meter: absent,
        # every read goes upstream exactly as before.
        self._cache = cache if account_ref else None
        self._account_ref = account_ref or ""
        self._signal_max_age = signal_max_age_seconds
        #: ADR-038 §3: the latest element listing per document (version, rows), handed
        #: from `_elements_at` to `_plan` so one listing serves both the target
        #: list and the export keys.
        self._listings: dict[str, tuple[str, list[tuple[str, str, str]]]] = {}
        #: ADR-038 §5c: what this sync's change probe already learned per document —
        #: `(workspace_id, microversion, observed_at)` — consumed once by `_plan`.
        self._observed: dict[str, tuple[str, str, float]] = {}

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
        """Prefer the provider's display name, then email, without exposing its id.

        Read-only grants may return neither. Keep the stable external id for
        matching while presenting a neutral label; do not widen OAuth scope.
        """
        async with self.http(creds) as client:
            body = await self.get_json(client, "/api/users/sessioninfo", what="session info")
        external_id = _text(body.get("id"))
        return AccountInfo(
            external_id=external_id,
            login=_text(body.get("name")) or _text(body.get("email")) or "Onshape account",
            name=_text(body.get("name")) or None,
        )

    # ----------------------------------------------------------- sync

    async def detect_changes(self, ctx: SyncContext) -> bool:
        """Cheap probe on each tracked document's MICROVERSION — Onshape's own
        change token. There is no account-level change feed, so this is one probe
        per selected document, bounded by the selection cap.

        A change to the SELECTION itself counts as changed, so newly picked
        documents are ingested and deselected ones are reconciled away.

        Probe errors propagate to the shared refresh/defer policy. An
        unreachable provider supplies no change evidence and must not trigger
        a full export.
        """
        document_ids = self._selected_document_ids(ctx)
        stored = self._stored_microversions(ctx, document_ids)
        if set(stored) != set(document_ids):
            return True
        async with self.http(ctx.credentials) as client:
            for document_id in document_ids:
                current = await self._probe(client, ctx, document_id)
                if current != stored.get(document_id):
                    return True

        changed = bool(document_ids) and ctx.cursor.get("projection_version") != PROJECTION_VERSION
        if not changed:
            self._observed.clear()  # nothing follows this probe; leave no stale evidence
        return changed

    async def sync(self, ctx: SyncContext) -> SyncResult:
        """Ingest every tracked document. One source now spans many documents, so
        each element's entities are namespaced by `(document, element)`.

        Partial-failure rule: `apply_sync_result` treats a result as a COMPLETE
        snapshot and soft-deletes anything absent from it, so a document that
        merely failed to fetch must never be silently omitted — that would
        tombstone its whole subtree. Only a document Onshape reports as GONE
        (404) is dropped, which is exactly the case where tombstoning is right.
        Every other failure aborts the sync and leaves the graph untouched.

        SOLUSDEV-241: every read is keyed by the document's microversion and
        served through the integration cache when one is attached, so a second
        project on the same account — or a teammate — at the same version
        costs zero calls.
        """
        recorder = ErrorRecorder()
        budget = _StagingBudget(self._max_staged_records, self._max_staged_bytes)
        entities: list[Any] = []
        relations: list[Any] = []
        microversions: dict[str, str] = {}
        resolved_workspaces: dict[str, str] = {}

        listing = (
            await self._cache.cached_listing(self.provider, self._account_ref)
            if self._cache
            else None
        )
        names = {item["id"]: item["name"] for item in listing.value} if listing else {}
        async with self.http(ctx.credentials) as client:
            for plan in await self._plan(client, ctx, recorder):
                # A cursor entry for EVERY selected document, including ones
                # that hold no assemblies and ones that are gone.
                # `detect_changes` compares the cursor's key set with the
                # selection, so a document missing an entry would read as
                # "selection changed" on every poll — an endless re-sync loop.
                microversions[plan.document_id] = plan.microversion
                if plan.workspace_id is not None:
                    resolved_workspaces[plan.document_id] = plan.workspace_id
                if plan.microversion == _GONE:
                    continue
                root = document_root(plan.document_id, names.get(plan.document_id))
                root.properties["observed_microversion"] = plan.microversion
                budget.consume([root])
                entities.append(root)
                for target in plan.targets:
                    target_entities, target_relations = await self._ingest(
                        client, target, recorder, version=plan.microversion
                    )
                    contained = document_contains(root, target_entities, target_relations)
                    budget.consume(target_entities)
                    budget.consume(target_relations)
                    budget.consume(contained)
                    entities.extend(target_entities)
                    relations.extend(target_relations)
                    relations.extend(contained)

        return SyncResult(
            entities=entities,
            relations=relations,
            # `workspaces` rides beside the change tokens so the next probe costs
            # ONE call instead of two (SOLUSDEV-167). `detect_changes` compares
            # only the `microversions` key set, so the extra key is inert to it.
            cursor={
                "microversions": microversions,
                WORKSPACES_KEY: resolved_workspaces,
                "projection_version": PROJECTION_VERSION,
            },
            errors=recorder.finish(),
        )

    async def _ingest(
        self,
        client: httpx.AsyncClient,
        target: _Target,
        recorder: ErrorRecorder,
        *,
        version: str,
    ) -> tuple[list[Any], list[Any]]:
        """One element → graph records, namespaced to its document."""
        # ADR-038 §3: keyed by the ELEMENT's microversion + a dependency fingerprint,
        # so an edit elsewhere in the document does not re-export this tab. The
        # bracketing inside `_geometry_export` still proves the bytes match `version`.
        export = await self._cached(
            self._payload_key(
                "export",
                target.document_id,
                target.revision or version,
                target.element_id,
                target.fingerprint or _DOCUMENT_KEYED,
            ),
            lambda: self._geometry_export(client, target, version),
        )
        if export is None:
            return [], []
        if self.scene_export_observer is not None:
            self.scene_export_observer(target.document_id, target.element_id, version, export)
        metadata = (
            await self._fetch_part_metadata(
                client,
                target.document_id,
                target.workspace_id,
                target.element_id,
                recorder,
                version=version,
            )
            if target.collection == "partstudios"
            else {}
        )
        model = self._enrich(await asyncio.to_thread(parse_step, export), metadata)
        # ONE recorder across every stage and every document, so the
        # MAX_SYNC_ERRORS bound is the documented per-sync cap rather than one
        # cap per document silently multiplied by the selection size.
        target_entities, target_relations, _ = build_mechanical_graph(
            model,
            recorder,
            scope=target.scope,
            provenance={**target.provenance, "observed_microversion": version},
        )
        return target_entities, target_relations

    async def _geometry_export(
        self, client: httpx.AsyncClient, target: _Target, version: str
    ) -> str | None:
        """Bracket workspace-only translation before publishing its revision cache."""
        await self._require_export_revision(client, target, version)
        try:
            export = await self._fetch_step(
                client,
                target.document_id,
                target.workspace_id,
                target.element_id,
                target.collection,
            )
        except ConnectorError as exc:
            if isinstance(exc, _InvalidExportResourceError) or (
                exc.code != "export_unavailable" and not isinstance(exc, _RejectedTranslationError)
            ):
                raise
            if not await self._confirmed_empty(client, target, version):
                raise
            export = None
        await self._require_export_revision(client, target, version)
        return export

    async def _require_export_revision(
        self, client: httpx.AsyncClient, target: _Target, version: str
    ) -> None:
        self._validate_revision(version)
        observed = await self._current_microversion(client, target.document_id, target.workspace_id)
        if observed != version:
            if self._cache is not None:
                # The next explicit sync must probe again, never replay this
                # known-stale plan or overwrite a concurrently observed signal.
                await self._cache.invalidate(self._signal_key(target.document_id))
            raise ConnectorError(
                "revision_changed",
                "Onshape workspace revision changed during export; snapshot was not applied",
            )

    @staticmethod
    def _validate_revision(version: str) -> None:
        if not isinstance(version, str) or not _ID_RE.fullmatch(version):
            raise ConnectorError("revision_changed", "Onshape acquisition revision is invalid")

    async def _confirmed_empty(
        self, client: httpx.AsyncClient, target: _Target, version: str
    ) -> bool:
        # Read the plan's immutable microversion, so a concurrent deletion cannot
        # turn an unrelated failed export into permission to drop graph geometry.
        collection = "parts" if target.collection == "partstudios" else "assemblies"
        if not _ID_RE.fullmatch(version):
            return False
        path = f"/api/v6/{collection}/d/{target.document_id}/m/{version}/e/{target.element_id}"
        try:
            body = await self.get_json(client, path, what="empty element check")
        except ConnectorError:
            return False
        if collection == "parts":
            return isinstance(body, list) and not body
        root = body.get("rootAssembly") if isinstance(body, dict) else None
        return isinstance(root, dict) and root.get("instances") == []

    # ----------------------------------------------------------- the cache

    def _signal_key(self, document_id: str) -> str:
        return IntegrationCache.signal_key(self.provider, self._account_ref, document_id)

    def _payload_key(self, kind: str, document_id: str, version: str, *parts: str) -> str:
        return IntegrationCache.payload_key(
            self.provider, self._account_ref, document_id, version, f"revision-v3-{kind}", *parts
        )

    async def _cached[T](self, key: str, fetch: Callable[[], Awaitable[T]]) -> T:
        """`fetch()` through the integration cache, or directly when none is
        attached. A payload is keyed by the document's change token, so a hit
        can never be stale — a change makes the key unreachable."""
        if self._cache is None:
            return await fetch()
        fetched = await self._cache.fetch(
            key, ttl_seconds=self._cache.payload_ttl_seconds, fetch=fetch
        )
        return fetched.value

    # ----------------------------------------------------------- selection

    def _selected_document_ids(self, ctx: SyncContext) -> list[str]:
        """The tracked document ids. Empty is VALID — a connected, idle source.

        Ingested config is untrusted (CLAUDE.md §7): every id is validated before
        it can reach a request path, and the list is bounded.
        """
        return tracked_document_ids(ctx.config, max_documents=self._max_documents)

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

    async def _plan(
        self, client: httpx.AsyncClient, ctx: SyncContext, recorder: ErrorRecorder
    ) -> list[_DocumentPlan]:
        """Expand the selection into exportable elements: each document's default
        workspace and current microversion, then every exportable element in it.

        Every selected document gets a plan — including ones that hold no
        assemblies and ones that are GONE (workspace `None`, microversion
        `_GONE`) — so the caller can cursor all of them.
        """
        legacy = self._legacy_target(ctx)
        if legacy is not None:
            observed = self._take_observed(legacy.document_id)
            microversion = (
                observed[1]
                if observed is not None
                else await self._current_microversion(
                    client, legacy.document_id, legacy.workspace_id
                )
            )
            return [_DocumentPlan(legacy.document_id, legacy.workspace_id, microversion, [legacy])]

        plans: list[_DocumentPlan] = []
        seen = 0
        for document_id in self._selected_document_ids(ctx):
            try:
                # ADR-038 §5c: the change probe of THIS sync already asked; the
                # webhook posture trusts no recorded signal and would pay twice.
                located = self._take_observed(document_id) or await self._locate(
                    client, ctx, document_id
                )
                workspace_id, microversion = located
                elements = await self._elements_at(client, document_id, workspace_id, microversion)
            except ConnectorError as exc:
                if exc.code != "not_found":
                    raise
                # Deleted upstream: dropping it (and letting its entities be
                # reconciled away) is the correct reading of "gone".
                recorder.record(label(document_id), "document is no longer available; skipped")
                plans.append(_DocumentPlan(document_id, None, _GONE, []))
                continue
            targets: list[_Target] = []
            revisions = self._export_revisions(document_id, microversion)
            for element_id, collection in elements:
                seen += 1
                if seen > self._max_elements:
                    # NOT a truncation. `sync` treats its result as a COMPLETE
                    # snapshot, so returning a partial target list would leave
                    # every document past the cap reading as GONE — its live
                    # entities soft-deleted, and a `_GONE` cursor that never
                    # matches the real microversion again, so `detect_changes`
                    # says "changed" forever: silent data loss plus a re-sync
                    # loop against an annual allowance. A snapshot that cannot
                    # be complete must fail instead.
                    raise ConnectorError(
                        "selection_too_large",
                        f"This selection expands to more than {self._max_elements} "
                        "exportable elements, which is more than one sync can cover. "
                        "Track fewer documents.",
                    )
                targets.append(
                    _Target(
                        document_id=document_id,
                        workspace_id=workspace_id,
                        element_id=str(element_id),
                        collection=str(collection),
                        revision=revisions.get(str(element_id), (None, None))[0],
                        fingerprint=revisions.get(str(element_id), (None, None))[1],
                    )
                )
            plans.append(_DocumentPlan(document_id, workspace_id, microversion, targets))
        return plans

    async def _elements_at(
        self, client: httpx.AsyncClient, document_id: str, workspace_id: str, version: str
    ) -> list[tuple[str, str]]:
        """The exportable elements at one version — cached by it."""
        self._validate_revision(version)

        async def fetch() -> list[tuple[str, str, str]]:
            return await self._exportable_elements(client, document_id, version)

        cached = await self._cached(self._payload_key("elements", document_id, version), fetch)
        # A cached list comes back as JSON lists; keep only well-formed rows.
        rows = [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in cached
            if isinstance(row, list | tuple) and len(row) == 3
        ]
        self._listings[document_id] = (version, rows)
        return [
            (element_id, EXPORTABLE_COLLECTIONS[kind])
            for element_id, kind, _ in rows
            if kind in EXPORTABLE_COLLECTIONS
        ]

    def _export_revisions(self, document_id: str, version: str) -> dict[str, tuple[str, str]]:
        """`element_id -> (element microversion, dependency fingerprint)` from the
        listing `_elements_at` just read (ADR-038 §3).

        A Part Studio's fingerprint covers every Part/Variable Studio in the
        document; an assembly's adds every assembly. An element — or any element
        its fingerprint covers — without a usable microversion is simply absent,
        so its export falls back to document-level keys rather than trusting
        data Onshape did not give us."""
        held = self._listings.pop(document_id, None)
        if held is None or held[0] != version:
            return {}
        rows = held[1]
        studios = [(i, m) for i, kind, m in rows if kind in _STUDIO_TYPES]
        assemblies = [(i, m) for i, kind, m in rows if kind == _ASSEMBLY_TYPE]
        studio_print = _fingerprint("ps", studios)
        assembly_print = _fingerprint("as", [*studios, *assemblies])
        revisions: dict[str, tuple[str, str]] = {}
        for element_id, kind, micro in rows:
            print_ = studio_print if kind == "PARTSTUDIO" else assembly_print
            if kind in EXPORTABLE_COLLECTIONS and micro and print_:
                revisions[element_id] = (micro, print_)
        return revisions

    def _take_observed(self, document_id: str) -> tuple[str, str] | None:
        """This sync's own probe result for `document_id`, once, if still young."""
        held = self._observed.pop(document_id, None)
        if held is None or time.monotonic() - held[2] > _OBSERVATION_TTL_SECONDS:
            return None
        return held[0], held[1]

    async def _locate(
        self, client: httpx.AsyncClient, ctx: SyncContext, document_id: str
    ) -> tuple[str, str]:
        """`(workspace_id, microversion)` for a live document — raising
        `not_found` for a gone one.

        SOLUSDEV-241: the recorded signal answers first when this caller's
        purpose may trust it (a human's sync inside the sweep window; the sweep
        inside its own short reuse window; a webhook never). Otherwise ONE
        probe call — the workspace id rides the cursor (SOLUSDEV-167) or the
        last recorded signal, so it is fetched only on first sight — and the
        answer is recorded for everyone else on this account.

        A stale workspace is self-healing: the microversion read 404s and we
        re-resolve once before concluding GONE, so a moved default workspace
        does not tombstone a live document's subtree.
        """
        recorded = await self._recorded_signal(document_id)
        if recorded is not None and self._cache is not None:
            observed = recorded.get("observed_at")
            if self._cache.is_fresh(observed, max_age_seconds=self._signal_max_age):
                return str(recorded["workspace"]), str(recorded["version"])
        workspace_id = self._known_workspace(ctx, document_id)
        if workspace_id is None and recorded is not None:
            workspace_id = str(recorded["workspace"])
        if workspace_id is None:
            workspace_id = await self.default_workspace(client, document_id)
        try:
            microversion = await self._current_microversion(client, document_id, workspace_id)
        except ConnectorError as exc:
            if exc.code != "not_found":
                raise
            # Either the document is gone or the remembered workspace is.
            fresh = await self.default_workspace(client, document_id)
            if fresh == workspace_id:
                raise
            workspace_id = fresh
            microversion = await self._current_microversion(client, document_id, fresh)
        if self._cache is not None:
            await self._cache.record_signal(
                self._signal_key(document_id),
                {"workspace": workspace_id, "version": microversion},
            )
        return workspace_id, microversion

    async def _recorded_signal(self, document_id: str) -> dict[str, Any] | None:
        """The last signal anyone recorded for this document, however old — the
        workspace in it is still worth a call even when the version is not."""
        if self._cache is None:
            return None
        entry = await self._cache.get(self._signal_key(document_id))
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("workspace"), str)
            and _ID_RE.fullmatch(entry["workspace"])
            and isinstance(entry.get("version"), str)
            and entry["version"]
        ):
            return entry
        return None

    async def _probe(self, client: httpx.AsyncClient, ctx: SyncContext, document_id: str) -> str:
        """This document's current change token, or `_GONE` when Onshape no
        longer has it — matching what `sync` records, so a deleted document that
        is still selected settles instead of scheduling a sync forever.

        SOLUSDEV-167: costs ONE call, not two — the workspace id rides the
        cursor. SOLUSDEV-241: costs ZERO when a trusted signal is recorded.
        """
        try:
            workspace_id, microversion = await self._locate(client, ctx, document_id)
        except ConnectorError as exc:
            if exc.code != "not_found":
                raise
            return _GONE
        self._observed[document_id] = (workspace_id, microversion, time.monotonic())
        return microversion

    def _known_workspace(self, ctx: SyncContext, document_id: str) -> str | None:
        """The workspace id a previous sync or probe already resolved."""
        legacy = self._legacy_target(ctx)
        if legacy is not None:
            return legacy.workspace_id
        stored = ctx.cursor.get(WORKSPACES_KEY)
        if not isinstance(stored, dict):
            return None
        value = stored.get(document_id)
        return value if isinstance(value, str) and _ID_RE.fullmatch(value) else None

    async def default_workspace(self, client: httpx.AsyncClient, document_id: str) -> str:
        body = await self.get_json(client, f"/api/v6/documents/{document_id}", what="document")
        workspace = body.get("defaultWorkspace") if isinstance(body, dict) else None
        raw = workspace.get("id", "") if isinstance(workspace, dict) else ""
        if not isinstance(raw, str) or not _ID_RE.fullmatch(raw):
            raise ConnectorError("api_error", "Onshape returned no usable default workspace")
        return raw

    async def _exportable_elements(
        self, client: httpx.AsyncClient, document_id: str, version: str
    ) -> list[tuple[str, str, str]]:
        """Every export-relevant element as `(element_id, elementType, microversion)`.

        Exportable ones (Part Studios, assemblies) become targets; Variable
        Studios ride along only to fingerprint what an export depends on. The
        microversion is Onshape's per-element `microversionId` ("" when the
        listing omits or mangles it).

        Onshape's `elementType` filter is SINGLE-VALUED, so asking for both
        families would cost a second request per document against an annual
        allowance. The filter is dropped and applied here instead — same one
        call, both families, and unexportable tabs never reach a translation.
        """
        self._validate_revision(version)
        body = await self.get_json(
            client,
            f"/api/v6/documents/d/{document_id}/m/{version}/elements",
            what="document elements",
        )
        elements: list[tuple[str, str, str]] = []
        for element in body if isinstance(body, list) else []:
            if not isinstance(element, dict):
                continue
            kind = str(element.get("elementType", ""))
            raw = element.get("id", "")
            if kind not in _TRACKED_TYPES or not isinstance(raw, str) or not _ID_RE.fullmatch(raw):
                continue
            micro = element.get("microversionId", "")
            elements.append(
                (raw, kind, micro if isinstance(micro, str) and _ID_RE.fullmatch(micro) else "")
            )
        return elements

    def validate_selection(self, ids: list[str]) -> None:
        """The selection rule, for the routes that edit a project's document
        list (SOLUSDEV-241). Duck-typed like `list_selectable`; raises
        `ConnectorError('config_invalid')` — the SAME gate `sync` and the SOL
        tools apply, so nothing malformed can be stored under `SELECTION_KEY`."""
        tracked_document_ids({SELECTION_KEY: ids}, max_documents=self._max_documents)

    async def list_document_tree(
        self, creds: Credentials, node: str = "root", offset: int = 0
    ) -> dict[str, Any]:
        """Browse one validated folder page through the existing quota meter."""
        from solus_api.connectors.onshape_tree import list_document_tree

        return await list_document_tree(self, creds, node, offset)

    async def list_selectable(self, creds: Credentials) -> list[dict[str, Any]]:
        """Documents the authorized account can reach, for the app's picker.

        Bounded: paging follows Onshape's `next` link, but never unboundedly
        against a third-party API (§7).
        """
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_pages: set[httpx.URL] = set()
        async with self.http(creds) as client:
            path: str | None = "/api/v6/documents"
            params: dict[str, Any] | None = {"limit": _PAGE_LIMIT}
            for _ in range(self._max_document_pages):
                if path is None:
                    break
                url = _document_page_url(path)
                page_url = url.copy_merge_params(params or {})
                if page_url in seen_pages:
                    raise ConnectorError(
                        "api_error", "Onshape repeated a document page; refresh the listing"
                    )
                seen_pages.add(page_url)
                body = await self.get_json(client, str(url), what="documents", params=params)
                if not isinstance(body, dict):
                    break
                for document in body.get("items") or []:
                    if not isinstance(document, dict):
                        continue
                    raw = document.get("id", "")
                    if not isinstance(raw, str) or not _ID_RE.fullmatch(raw):
                        continue
                    if raw in seen_ids:
                        continue
                    seen_ids.add(raw)
                    items.append(
                        {
                            "id": raw,
                            "name": _text(document.get("name")) or raw,
                            "subtitle": _owner_name(document),
                        }
                    )
                next_link = body.get("next")
                path = next_link if isinstance(next_link, str) and next_link else None
                params = None
            if path is not None:
                raise ConnectorError(
                    "listing_incomplete",
                    "Onshape's document listing exceeded the page limit; "
                    "contact support to expand the listing limit",
                )
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
        collection: str = _ASSEMBLIES,
    ) -> str:
        """Onshape's async translation dance: request → poll → download.

        `collection` is the only element-type-specific part: a Part Studio
        translates through `/partstudios/`, an assembly through `/assemblies/`.
        """
        path = element_base_path(collection, document_id, workspace_id, element_id)
        try:
            started = await self.post_json(
                client,
                f"{path}/translations",
                {"formatName": _EXPORT_FORMAT, "storeInDocument": False},
                what="STEP translation request",
            )
        except _BadRequestError as exc:
            # Only submission rejection may be an empty Part Studio. Polling,
            # malformed JSON/IDs, auth and quota failures remain terminal.
            raise _RejectedTranslationError(exc.code, str(exc)) from exc
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
                if self._meter is not None:
                    await self._admit()
                for attempt in range(_RATE_LIMIT_RETRIES + 1):
                    async with client.stream("GET", path) as response:
                        if self._meter is not None:
                            # This path does NOT go through `request()`, which is
                            # exactly why the audit found it uncounted.
                            await self._meter.record(response.status_code)
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
        """Bounded poll — never an unbounded loop against a third-party API (§7).

        SOLUSDEV-167: this was the single largest per-sync cost — a flat 1 s
        interval for up to 30 attempts, i.e. up to 30 QUOTA-COUNTED GETs per
        assembly. Backing off doubles the wait each time so a slow translation
        costs ~4 calls instead of ~30, and the loop now carries its own deadline:
        without one, backoff would make a stuck translation take LONGER to fail
        rather than bounding it, and with `sync_inline` that time is held inside
        an HTTP request.
        """
        try:
            async with asyncio.timeout(_POLL_DEADLINE_SECONDS):
                return await self._poll_until_done(client, request_id)
        except TimeoutError as exc:
            raise ConnectorError(
                "export_timeout",
                f"Onshape did not finish the {_EXPORT_FORMAT} translation in time",
            ) from exc

    async def _poll_until_done(self, client: httpx.AsyncClient, request_id: str) -> str:
        delay = self._poll_interval
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
                await asyncio.sleep(delay)
                delay = min(delay * 2, _POLL_MAX_INTERVAL_SECONDS)
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
        *,
        version: str,
    ) -> dict[str, tuple[str | None, str | None]]:
        """Part number + material per part NAME.

        Enrichment, not structure: if this call fails the team still gets their
        assembly tree, with the loss recorded on the Sync row. A failure is
        never cached — only a table Onshape actually returned is.
        """
        self._validate_revision(version)
        try:
            rows = await self._cached(
                self._payload_key("parts", document_id, version, element_id),
                lambda: self._read_part_metadata(client, document_id, version, element_id),
            )
        except ConnectorError as exc:
            recorder.record(
                "metadata", f"part metadata unavailable ({exc.code}); part numbers skipped"
            )
            return {}
        return {
            str(name): (number, material)
            for name, number, material in rows
            if isinstance(name, str)
        }

    async def _read_part_metadata(
        self, client: httpx.AsyncClient, document_id: str, version: str, element_id: str
    ) -> list[tuple[str, str | None, str | None]]:
        """The raw table as `(name, part number, material)` rows — a JSON-safe
        shape, since it is what the cache stores."""
        self._validate_revision(version)
        body = await self.get_json(
            client,
            f"/api/v6/parts/d/{document_id}/m/{version}/e/{element_id}",
            what="part metadata",
        )
        table: list[tuple[str, str | None, str | None]] = []
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
            table.append((name, number, material))
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

    async def _admit(self) -> None:
        """Ask the meter before spending. Its error is translated into a
        `ConnectorError` so no caller has to learn a second exception type — and
        both codes are in NO_SIGNAL_CODES, so a refusal reads as "could not ask"
        rather than "it changed" and never buys a full re-sync."""
        assert self._meter is not None
        try:
            await self._meter.admit()
        except QuotaBlockedError as exc:
            raise ConnectorError(exc.code, exc.message) from exc

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
        if self._meter is not None:
            # Admission is UNCONDITIONAL — before the retry ladder, so a refused
            # call is refused once rather than four times.
            await self._admit()
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                response = await client.request(method, path, json=json_body, params=params)
            except httpx.HTTPError as exc:
                raise ConnectorError(
                    "api_unreachable", f"could not reach Onshape for {what}"
                ) from exc
            if self._meter is not None:
                # Recorded per ATTEMPT, because the provider counts attempts —
                # and only 2xx/3xx move the ledger, so the 429 retries below are
                # free in quota terms even though they cost wall-clock.
                await self._meter.record(response.status_code)
            if response.status_code != 429:
                break
            if attempt < _RATE_LIMIT_RETRIES:
                await asyncio.sleep(_retry_wait(response, attempt))
        _raise_for_status(response, what)
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

    async def immutable_feature_specs(
        self,
        client: httpx.AsyncClient,
        *,
        document_id: str,
        element_id: str,
        microversion_id: str,
        collection: str,
    ) -> dict[str, Any]:
        """Default-configuration specs at the caller's freshly observed tree revision."""
        from solus_api.connectors.onshape_read_cache import (
            OnshapeReadCache,
            validated_feature_specs,
        )

        if collection not in ("partstudios", "assemblies"):
            raise ConnectorError("config_invalid", "Unsupported feature specification collection")
        for identity in (document_id, element_id, microversion_id):
            self._validate_revision(identity)

        async def acquire() -> dict[str, Any]:
            body = await self.get_json(
                client,
                f"/api/v6/{collection}/d/{document_id}/m/{microversion_id}/e/{element_id}/featurespecs",
                what="immutable feature specifications",
            )
            return validated_feature_specs(body)

        if self._cache is None:
            return await acquire()
        return validated_feature_specs(
            await OnshapeReadCache(self._cache, self._account_ref).fetch(
                document_id=document_id,
                element_id=element_id,
                revision_kind="m",
                revision_id=microversion_id,
                kind="feature_spec",
                collection="assemblies" if collection == "assemblies" else "partstudios",
                fetch=acquire,
            )
        )

    async def immutable_body_details(
        self,
        client: httpx.AsyncClient,
        *,
        document_id: str,
        element_id: str,
        microversion_id: str,
    ) -> Any:
        """Default-configuration donor geometry at an immutable verified revision.

        Callers still authorize the tracked donor and refresh mutable target state.
        Both the route and returned revision are pinned before a cache entry exists.
        """
        from solus_api.connectors.onshape_read_cache import OnshapeReadCache

        if any(
            not isinstance(value, str) or not _ID_RE.fullmatch(value)
            for value in (document_id, element_id, microversion_id)
        ):
            raise ConnectorError("invalid_config", "Invalid immutable donor identity")

        async def fetch() -> Any:
            body = await self.get_json(
                client,
                f"/api/v6/partstudios/d/{document_id}/m/{microversion_id}/e/{element_id}/bodydetails",
                what="mate connector face",
                params={"includeGeometricData": "true"},
            )
            observed = body.get("microversionId") if isinstance(body, dict) else None
            if isinstance(observed, dict) and observed.get("btType") == "BTMicroversionId-366":
                observed = observed.get("theId")
            if (
                not isinstance(body, dict)
                or body.get("errorEnum", "NO_ERROR") != "NO_ERROR"
                or not isinstance(body.get("bodies"), list)
                or any(
                    body.get(flag, False) is not False for flag in ("incomplete", "isIncomplete")
                )
                or body.get("isComplete", True) is not True
                or observed != microversion_id
            ):
                raise ConnectorError("api_error", "Onshape returned an invalid donor revision")
            return body

        if self._cache is None:
            return await fetch()
        return await OnshapeReadCache(self._cache, self._account_ref).fetch(
            document_id=document_id,
            element_id=element_id,
            revision_kind="m",
            revision_id=microversion_id,
            kind="donor_geometry",
            fetch=fetch,
        )

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
