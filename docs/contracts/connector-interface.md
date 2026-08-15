# Connector Interface — Design Contract (SOLUS-W0-05)

**Status:** Design contract + base classes + a reference `FakeConnector` + a reusable conformance
suite. Ships the `Integration`/`Connector` hierarchy, the normalized output shapes, the diff
helper, `read_secret` (a stubbed Secrets Manager seam), and `assert_connector_conforms`. The real
connectors, the `LiveConnection` streaming sibling, the webhook/event plumbing, and the ingestion
pipeline are separate tickets.
**Authority:** CLAUDE.md §1 (one common connector interface → graph entities+relations,
SDK-extractable later) + §7 (credentials & untrusted-ingest security), ADR-001 (graph-centric —
connectors write, everything else reads), ADR-027 + `models.py` (`graph_entity.source_connector` /
`external_ref` provenance; `graph_edge` `(src, dst, relation_type, domain_pair)`), ADR-028
(Week-0 human-owned contract), `docs/api/API.md §2.5` (the sources/sync/webhook API surface this
interface must satisfy). Code: `packages/api/src/solus_api/connectors/`.

Consumers: the connector authors building the ~9 design-artifact connectors (code hosts, mechanical
CAD, EDA) implement this once so a family mirrors itself; **ingestion** writes the normalized output
to the graph; **linking (LNK-01) + the fingerprint (W0-06)** consume `EntityOut.source_id` and
`modality_hints` to produce cross-connector links. This contract is the blocking dependency for API
Phase 3 (Sources & sync — `API.md:454`).

> ⚠ **Unrecorded decision (flag for the founders):** the metadata-extraction strategy this contract
> is built around — **v1 = parse committed Git exports (Gerber/STEP/JSON netlist/SPICE), NOT live
> tool plugins** — is stated in the ticket but is not yet an ADR. It should be ratified as a
> human-authored ADR-030 so the contract can cite it durably. Likewise `integrations/CLAUDE.md`
> (planned in the repo tree) does not exist yet; connector rules currently live in the root CLAUDE.md.

---

## 1. The class hierarchy

```
Integration (ABC)      — connect to an external application (+ credentials via Secrets Manager)
  Connector            — THIS ticket: the design-artifact branch (sync + detect_changes)
  LiveConnection       — DOCUMENTED SIBLING, NOT built here: Live Bench sim/telemetry streaming
```

- **`Integration`** is the shared parent — "connect to an external application." Both branches
  connect-to-an-app; that is the only behavior they share.
- **`Connector`** (this ticket) is the design-artifact branch: it SYNCS design artifacts into the
  graph. GitHub, GitLab (code hosts), Onshape + proprietary STEP/DWG parsing (mechanical CAD), and
  KiCad/LTspice/NgSpice/Altium (EDA) are all `Connector`s.
- **`LiveConnection`** (documented, not built) is the sim/telemetry branch: Gazebo, Isaac Sim,
  Foxglove, a real-robot connection — **streaming live sensor data**, not syncing design artifacts.
  It belongs to **Live Bench** (the real-time seam, ADR-014/029), shares the `Integration` parent
  (connecting to the app), but adds STREAMING behavior instead of `sync`/`detect_changes`, and its
  data rides a **separate telemetry packet-format contract** — not this one. Sim/viz tools are NOT
  Connectors; they do not sync design artifacts.

**Why an ABC (the repo's first).** The codebase otherwise uses `typing.Protocol` for interfaces.
This design needs a NOMINAL hierarchy with INHERITED implementation — a shared parent, the inherited
`diff_entities` helper on `Connector`, and a sibling branch — which a structural Protocol cannot
provide. So `Integration` is an `abc.ABC` with `@abstractmethod async def` members.

---

## 2. `Integration` — the parent + the Secrets Manager seam

```python
class Integration(abc.ABC):
    @abstractmethod
    async def connect(self, config: ConnectorConfig) -> Session: ...
    @abstractmethod
    async def disconnect(self, session: Session) -> None: ...
```

**Credentials via AWS Secrets Manager, NEVER in code, env literals, or config values.** `connect`
sources credentials by a `secret_ref` on the config, through the one sanctioned seam:

```python
async def read_secret(secret_ref: str) -> Mapping[str, str]:  # STUB — boto3 wired in a later infra ticket
```

`ConnectorConfig.secret_ref` is the ONLY credential channel. The conformance suite enforces this
**structurally**: it rejects any config whose field names OR `options` keys look like a plaintext
credential (a substring scan over `token`/`secret`/`password`/`private_key`/… — see §10). What it
CANNOT enforce is how a connector internally sources the secret inside `connect()` — an interface
contract can't observe that. That `connect()` sources credentials only via `read_secret(secret_ref)`
is upheld by this being the sole provided channel, CI secret-scanning (no literals in code/tests),
and review. Credentials are encrypted at rest, never logged, and never returned by any API response
(CLAUDE.md §7, `API.md:154`).

---

## 3. `Session` — a uniform interface over varying contents

`Session` is the abstraction whose **contents vary by connector** while the interface (connect →
session → sync) stays uniform:

- **API connectors** (GitHub, GitLab, Onshape): the session holds the authenticated API client.
- **File-parse connectors** (KiCad, LTspice, NgSpice; proprietary STEP/DWG): the session holds the
  resolved location (repo ref + path) and the auth to reach the repo.

It is a **live handle**, not a wire value, so it is a `@dataclass` base (holding `config`) that
connectors subclass to add their specific contents — not a frozen Pydantic model.

---

## 4. `Connector` — sync + detect_changes

```python
class Connector(Integration):
    @abstractmethod
    async def sync(self, session: Session) -> SyncResult: ...        # FULL current state
    @abstractmethod
    async def detect_changes(self, session: Session) -> Delta: ...   # the delta path
```

- **`sync()`** returns the FULL current entity/relation set for the source. Full-sync is v1;
  incremental sync is a later optimization. Ingestion runs it as a background job (`API.md §2.5`:
  `POST …/sources/{id}/sync` → `202` + a Job), never in the request path.
- **`detect_changes()`** returns a `Delta` keyed by stable `source_id`. This is the method
  automatic event-driven sync calls (§8).

---

## 5. Normalized output shapes

Pydantic v2 value objects, house style `ConfigDict(frozen=True, extra="forbid")`.

**`EntityOut`**

| field            | meaning                                                                       |
| ---------------- | ----------------------------------------------------------------------------- |
| `kind`           | maps to `graph_entity.kind` (`code_file`, `component`, `part`, `cad_body`, …) |
| `source_id`      | **THE LINCHPIN** — see below                                                  |
| `attrs`          | `dict` — type-specific attributes                                             |
| `modality_hints` | `dict` — the bridge to the fingerprint matcher (W0-06)                        |

**`source_id` — the linchpin.** The stable per-tool identifier of an entity within its source
(KiCad ref designator `U1`, a GitHub file path, an Onshape part id). It MUST be **deterministic
across re-syncs** (so diffing works) and **unique within the connector's scope**. It is the SAME
value as the fingerprint's `SourceRef.external_ref` and `graph_entity.external_ref` — that identity
is what lets the fingerprint and API-provenance line up.

**`modality_hints` — the bridge to the fingerprint.** Modality-relevant data the connector
extracted that helps identify the physical part: part numbers, schematic symbol names, datasheet
refs, CAD model ids. It is how connector output FEEDS the fingerprint matcher (W0-06), which groups
one physical part observed across modalities into a canonical entity.

**`RelationOut`**

| field           | meaning                                                                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `src_source_id` | references an `EntityOut.source_id` WITHIN THIS CONNECTOR's output                                                                          |
| `dst_source_id` | same — intra-source only                                                                                                                    |
| `relation_type` | maps to `graph_edge.relation_type`                                                                                                          |
| `domain_pair`   | lowercase `Domain` values joined by `<->`, matching `graph_edge.domain_pair` — e.g. `code<->code`, `electrical<->electrical` (intra-source) |

**`SyncResult`** = `entities: list[EntityOut]` + `relations: list[RelationOut]`.

**`Delta`** = `added: list[EntityOut]` + `changed: list[EntityOut]` + `removed: list[str]`
(source_ids). **v1 tracks ENTITY changes**; relation changes reconcile via a full `sync()`. Relation
deltas (`added_relations`/`removed_relations`) are a documented forward extension for when a
connector needs them.

- The domain vocabulary is now the single canonical `Domain` enum owned by `models.py`
  (`code`, `electrical`, `mechanical`, `simulation`, `runtime`), re-exported from
  `connectors/contracts.py`. Any doc text using `software` for the code domain should read `code`
  (e.g. `domain_pair` examples: `code<->code`). The connector layer's former rival `Domain`
  (`software`/…) is gone.
- Make the linchpin naming explicit and consistent: the connector's stable per-source id is
  `EntityOut.source_key`; it is persisted to `graph_entity.external_ref` and is the SAME value the
  fingerprint reads as `SourceRef.external_ref`. `source_key` (output field) ≡ `external_ref`
  (graph/fingerprint column). The runtime maps `source_key → external_ref` at write time.

---

## 6. Intra-source relations only — cross-connector linking is downstream

**Connectors emit ONLY intra-source relations** — relations between entities THEY produced. A
connector never references another connector's entities (it does not know about them). This
independence is exactly what makes connectors parallelizable, and the conformance suite enforces it
(every `RelationOut` end must be a `source_id` present in the connector's own entity set).

**Cross-connector / cross-domain relations are NOT the connector's job.** The op-amp in the
schematic, the op-amp referenced in code, and the op-amp in CAD are linked to ONE canonical entity
**downstream** by linking (LNK-01) using the fingerprint (W0-06) — via `graph_entity.canonical_part_id`

- a `SAME_AS` edge. Connector-owned entities/relations are read-only through the API (the connector
  is the source of truth; edits happen in the source tool and arrive via sync — `API.md:129`), which
  is why the output carries `source_connector` + `source_id` provenance.

---

## 7. Two change-detection patterns + the diff helper

Connectors get changes two ways behind the SAME `Delta` interface:

- **Native change-feed:** the source tells you what changed (code-host webhooks, Onshape API
  notifications). The connector maps the feed to a `Delta`.
- **Diff-based (re-parse-and-compare):** file-parse connectors have no push feed — they re-parse
  current state and diff against last-known state (by `source_id`) to emit added/changed/removed.

`Connector` provides a **base-class helper** for the diff pattern (~half the connectors need it —
this is what lets file-parse connectors mirror each other):

```python
@staticmethod
def diff_entities(current: list[EntityOut], prior: list[EntityOut]) -> Delta
```

It keys both sides by `source_id`; `changed` is by value inequality of the whole `EntityOut`. Each
concrete connector still implements its OWN delta method — the base provides the reusable diff and
the interface.

---

## 8. Automatic, event-driven sync (designed-for)

Connectors are DESIGNED to be driven automatically so syncs feel real-time after a change in the
integrated service:

- **Native-feed connectors** (GitHub/GitLab/Onshape): event-driven via signature-verified inbound
  webhooks (`API.md:163`, `POST /api/v1/webhooks/{provider}`) → `detect_changes`/`sync` fires on the
  event.
- **File-parse connectors** (EDA/CAD): "automatic" via the GIT repo's change events — a new commit
  containing the exported artifact (netlist/STEP) fires the same path → re-parse-and-diff.

`detect_changes` is the interface automatic-sync calls. The webhook receiver, event queue, and
sync-on-change plumbing are PER-CONNECTOR IMPLEMENTATION (later tickets) — documented here as the
intended pattern so connectors are built **event-driven, not poll-only**. This contract does not
build that plumbing.

---

## 9. Security (binds this contract — CLAUDE.md §7)

- **Ingested content is UNTRUSTED input to the model layer.** Everything a connector extracts — code
  comments, README/commit text, CAD part names, schematic field values, datasheet text — flows into
  `EntityOut.attrs`/`modality_hints`. Downstream, it is always wrapped, delimited, and framed as
  DATA to be analyzed, never as instructions to follow (CLAUDE.md:336). A connector's output is data,
  not commands.
- **File-parse connectors handle files defensively:** validate type and size, never execute an
  uploaded artifact, never unzip blindly (zip-bomb and path-traversal guards), and call subprocess
  parsers/converters with argument lists only — never `shell=True` with tool-influenced strings.
- **Credentials** come only from Secrets Manager via `read_secret(secret_ref)`; they never appear in
  code, tests, fixtures, logs, config values, or any API response, and never enter model context.

---

## 10. The reference `FakeConnector` + the conformance suite

`assert_connector_conforms(connector, config)` is the **connector contract suite** every `Connector`
subclass must pass (CLAUDE.md §6). It ships in the package so each connector's own test imports it,
and it asserts:

- credential hygiene — the config exposes credentials only via `secret_ref`, with no plaintext
  credential in a field name OR an `options` key (substring scan);
- `connect` returns a `Session`; `disconnect` does not raise (a raising `disconnect` is a failure);
- `sync` returns a `SyncResult` with well-formed entities (non-empty `kind`+`source_id`, unique
  `source_id`);
- the **intra-source invariant** — every `RelationOut` end is a `source_id` present in the entity set;
- `detect_changes` returns a `Delta` keyed by `source_id`.

The reference `FakeConnector` passes it; a `_BadConnector` in the test proves the suite CATCHES a
cross-source relation and duplicate `source_id`s.

---

## 11. Functional vs. future in W0-05

| Component                                                                  | W0-05 status                        |
| -------------------------------------------------------------------------- | ----------------------------------- |
| `Integration` ABC + `Connector` (connect/disconnect/sync/detect_changes)   | **Functional**                      |
| `EntityOut`/`RelationOut`/`SyncResult`/`Delta`/`ConnectorConfig`/`Session` | **Functional**                      |
| `diff_entities` helper + the reusable conformance suite                    | **Functional**                      |
| `read_secret` (Secrets Manager seam)                                       | **Stub — boto3 in an infra ticket** |
| `LiveConnection` streaming sibling (Live Bench)                            | **Documented, not built**           |
| The ~9 real connectors                                                     | **Separate tickets (one each)**     |
| Webhook receiver / event queue / sync-on-change plumbing                   | **Per-connector, later**            |
| Ingestion pipeline consuming `SyncResult`/`Delta`                          | **Downstream**                      |
| Relation deltas on `Delta`                                                 | **Forward extension**               |

---

**Cross-references:** CLAUDE.md §1 (common connector interface) + §7 (security), ADR-001
(graph-centric), ADR-027 + `packages/api/src/solus_api/models.py` (`graph_entity`/`graph_edge`
provenance), ADR-028 (human-owned contract), ADR-014/029 (Live Bench — the `LiveConnection` sibling
and its separate telemetry packet-format contract), `docs/api/API.md §2.5` (sources/sync/webhook
surface). Code: `packages/api/src/solus_api/connectors/` (`base.py`, `conformance.py`). Downstream:
the real connectors (each must pass the conformance suite), fingerprint (W0-06 — `modality_hints` →
`SourceRef`), linking (LNK-01 — cross-connector links). Sibling contracts: `fingerprint-output.md`,
`agent-tool.md`, `model-orchestration.md`. **Pending:** ADR-030 (git-exports-v1 metadata strategy).

---

## Edit 6 — OAuth token refresh (SOLUSDEV-96 / CAD-01)

The shipped OAuth path stored only the ACCESS token: `_complete_oauth` persisted `creds.token` and
`run_sync` rebuilt `Credentials(token=...)`, dropping `refresh_token`. GitHub and GitLab tokens are
long-lived so nothing surfaced the gap — but **Onshape access tokens expire after 60 minutes**, so
an Onshape source would have stopped syncing within the hour. This edit adds the refresh seam.

**`OAuthConnector.refresh_credentials(creds) -> Credentials`** — non-abstract, default REFUSES with
`ConnectorError('oauth_refresh_failed', ...)`. A provider that has not opted in can therefore never
appear to refresh silently. Providers with expiring tokens MUST override it.

**Division of responsibility.** The RUNTIME owns persistence (it holds the `SecretStore`); the
CONNECTOR owns the provider-specific refresh call. `runtime._sync_with_refresh` runs one sync and,
**only** when it fails with `invalid_credentials` **and** the connector is an `OAuthConnector`
**and** a refresh token is stored, calls `refresh_credentials` **at most once**, persists the
result, and retries the sync **once**. A permanently-broken credential can never spin against a
provider's token endpoint.

**Rotation is mandatory to honour.** Onshape issues a NEW refresh token on every refresh and
invalidates the old one, so an implementation MUST return the rotated `refresh_token` and the
runtime MUST persist it — dropping it breaks the chain at the _next_ refresh, not this one.

**Storage.** `runtime.refresh_secret_ref(secret_ref) -> f"{secret_ref}/refresh"` is the ONE
definition, shared by the OAuth-completion write and both reads, so the refs cannot drift (the same
rule MCP-05's `license_secret_ref` follows). Sources connected before this edit simply have no such
secret; its absence is not an error and the access-token read path is unchanged.

**Error codes.** `invalid_credentials` is the code a connector raises for an expired or rejected
token — it is the trigger the runtime keys off, so a connector that reports expiry any other way
will not be refreshed. `oauth_refresh_failed` means the refresh token itself was rejected; the
runtime then leaves the stored credentials untouched and records the sync failure.

## Edit 7 — the selection capability (SOLUSDEV-96 follow-up)

A connector may let a user choose **what** it tracks after connecting: a repository for a code
host, CAD documents for an account-level tool. That is one optional capability, not a per-provider
route or a per-provider UI.

**`Connector.selection: ClassVar[dict] | None`** — declared metadata, surfaced verbatim by
`GET /api/v1/integrations`:

```python
selection = {"mode": "single" | "multi", "config_key": "repo", "label": "repository"}
```

`mode` decides whether the picker takes one item or many, `config_key` names the source-config key
the choice writes, and `label` is the noun shown to the user. Absent (`None`) means there is
nothing to pick — the app then falls back to a generated form over `config_fields`.

**`async list_selectable(self, creds: Credentials) -> list[dict]`** — duck-typed, resolved with
`getattr` by `GET /api/v1/projects/{p}/sources/{s}/selectable`, exactly as `list_repositories` was.
It is deliberately NOT on the `Connector` ABC: not every connector has anything to list, and the
route already treats its absence as `400 unsupported`. Item shape:

```json
{ "id": "...", "name": "...", "subtitle": "...", "config": { "...": "..." } }
```

`config` is optional and is the exact source config choosing that item writes — it exists so a
single-select connector can contribute more than an id (GitHub needs `repo` AND `branch`) without
the caller knowing what the item means. Multi-select ignores it and writes
`{config_key: [id, …]}`.

**Credentials go through the refresh path.** The route resolves credentials with
`runtime.resolve_credentials` and calls the lister through `runtime.call_with_refresh` — the same
refresh-once-and-retry machinery `_sync_with_refresh` uses. Without it, a 60-minute Onshape token
would make "edit my selection" fail an hour after connecting.

**Why this shape.** Nothing in the frontend may branch on a provider id: the next CAD connector
(Fusion, SolidWorks, AutoCAD) becomes fully pickable by declaring `selection` and implementing
`list_selectable`, with no route, no picker, and no catalog change.

---

## Edit 8 — the access-mode capability (SOLUS-ONS-A2)

A connector may let a user choose **how much power** it grants at connect time, the same way
`selection` lets them choose **what** it tracks. One optional capability, not a per-provider route
and not a per-provider UI.

**`OAuthConnector.access_modes: ClassVar[dict] | None`** — declared metadata, surfaced verbatim by
`GET /api/v1/integrations` beside `selection`:

```python
access_modes = {
    "default": "read",
    "modes": [
        {"id": "read",  "label": "Read only",     "description": "...", "scopes": ["OAuth2Read"]},
        {"id": "write", "label": "Read and edit", "description": "...", "scopes": ["OAuth2Read", "OAuth2Write"]},
    ],
}
```

`None` (the default) means there is no choice — `scopes` is the whole story, which is the case for
GitHub and GitLab.

**`scopes_for(access: str | None) -> tuple[str, ...]`** resolves a mode to its scopes. `None` means
the declared **default**, never the widest option, so an omitted choice can only ever under-grant.
An **unknown mode raises** rather than falling back: silently downgrading a typo would connect a
source with powers the user did not choose, in either direction. The route maps that to
`400 invalid_access_mode`.

**`authorize_url(*, state, redirect_uri, access=None)`** — the ABC gained `access`; connectors
without modes ignore it.

**Why this exists.** An OAuth grant is account-wide on the providers that matter here — Onshape has
no per-document or per-project scope — so "may Solus edit my CAD?" is a real decision that belongs
to the customer, not a default we pick. `POST /{provider}/oauth/start` takes an optional `access`,
and the granted mode is recorded on `Source.config["access"]` so "can Solus edit this?" is
answerable without re-deriving it from the token.

**Why this shape.** Identical reasoning to Edit 7: the next CAD connector (Fusion, SolidWorks,
AutoCAD) becomes choosable by declaring `access_modes`, with no route change, no picker change and
no catalog change — and nothing in the frontend may branch on a provider id.
