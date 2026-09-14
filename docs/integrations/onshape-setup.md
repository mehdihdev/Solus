# Onshape integration setup (SOLUSDEV-96 / CAD-01)

> Current behavior (SOLUSDEV-261): this guide retains the original connector setup
> history. Native authoring and the hosted FeatureScript add-on now complement
> STEP graph ingestion. The default import bound is 256 exportable elements;
> verified public webhook subscriptions replace routine polling. See
> [the quota audit](../qa/ONSHAPE_QUOTA_AUDIT_SOLUSDEV-261.md) and
> [current code map](../CODEMAPS/onshape.md) for transport, freshness and acceptance
> limits. `SOLUS_PUBLIC_API_BASE_URL` also configures webhook callback registration;
> localhost does not provide live webhook delivery.


Onshape is Solus's mechanical-CAD source. It is a **thin API** integration per
`docs/contracts/metadata-extraction.md` §2: Solus uses the Onshape REST API only to
authenticate, detect change, and fetch a STEP export — then routes that export into the **shared
CAD parser** every other CAD tool uses. It is deliberately _not_ a deep live-API integration, and
it needs **no local bridge** (Onshape is cloud REST).

## 1. Why OAuth, and why an API key pair will not do

From Onshape's own documentation:

> API keys are used to authenticate an application, **NOT its users**. OAuth2 authenticates an
> application **AND** users.

An Onshape API key pair acts as **the developer**. It can only ever reach the developer's own
documents, so it cannot serve a customer. Solus therefore registers an **Integrated Cloud App**
and uses the authorization-code flow. `OnshapeConnector.supports_token_connect` is `False` so the
generic token-connect path cannot be used to smuggle a key pair past the OAuth flow.

The `onshape_access_key` / `onshape_secret_key` names that appear in
`agent/tools/mcp_servers.py` belong to the **separate MCP tool path**, not to this connector. Do
not conflate them.

## 2. Register the OAuth application

1. Onshape → **Developer Settings → OAuth applications → Create new application**.
2. Redirect URLs — add both, **exactly** as written:

   - `http://localhost:8000/api/v1/integrations/onshape/oauth/callback` (web/dev callback)
   - `http://localhost:53682/auth/callback` (the desktop loopback flow)

   > **`localhost`, not `127.0.0.1`.** Onshape's OAuth app refuses a bare IP in a redirect URL.
   > The desktop loopback server therefore binds **both** `127.0.0.1` and `::1` — `localhost`
   > resolves to `::1` first on many systems, and a callback arriving over IPv6 at an
   > IPv4-only socket is refused, hanging the sign-in until it times out. Both sockets are
   > loopback-only (`apps/desktop/src/main/oauthLoopback.ts`).
   >
   > **Onshape matches the redirect URI exactly** — host, port, path, and query. The earlier
   > `http://127.0.0.1:<port>` placeholder here is what produced
   > `error="invalid_grant", error_description="Application requested an invalid redirect URL"`:
   > the desktop was sending `…/auth/callback?solus_cb=<fresh uuid>`, a URL that changes every
   > flow and so can never match a registration. The connector flow now uses the constant URL
   > above and carries its CSRF nonce in the OAuth `state` param instead
   > (`apps/desktop/src/main/oauthCallback.ts` — `connectorRedirectUrl`). GitHub and GitLab use
   > the same constant URL; they tolerated the old query, Onshape does not. **Update their OAuth
   > apps to this URL too** if they still carry the old `127.0.0.1` entry.
   >
   > `SOLUS_PUBLIC_API_BASE_URL` does **not** build this redirect. It is only the fallback the
   > backend uses when the caller sends no `redirect_uri` (`_resolve_redirect_uri`,
   > `routers/integrations.py`) — i.e. the web callback, not the desktop app.

3. Scopes: request **`OAuth2Read`** and **`OAuth2Write`** on the application. Do **not** request
   `OAuth2Delete`, `OAuth2Share`, `OAuth2Purchase` or the PII scope.

   **Why write is requested, and why the customer chooses (SOLUS-ONS-A2).** Editing CAD is the
   product, not a dangerous add-on — withholding the capability would not make anyone safer, it
   would make Solus unable to do the thing it exists to do. The mitigation is token protection plus
   a per-edit confirmation gate that shows the user the concrete change before it is applied, not
   refusing the capability.

   But an Onshape grant is **account-wide**. Verified against Onshape's docs: the scopes are
   `OAuth2Read`, `OAuth2Write`, `OAuth2Delete`, `OAuth2Share`, `OAuth2Purchase` and `OAuth2ReadPII`,
   and **there is no per-document, per-workspace or per-company grant, and no "share this document
   with an app" mechanism** — the account UI offers only whole-grant revocation. So how much power
   Solus holds is the customer's decision, made **at connect time**: the connector declares two
   access modes (`read`, `write`) and the app asks. An omitted choice resolves to the declared
   default, which is `read` — an absent answer can only ever under-grant.

   **`OAuth2Delete` is never requested.** It covers destroying documents, workspaces and elements.
   Feature deletion and assembly-instance deletion are both `OAuth2Write` (verified by enumerating
   every operation in Onshape's OpenAPI spec that requires `Delete` — ten, none of them features).
   So it buys nothing and would let a confused agent wipe a customer's document.

   > **Changed in SOLUS-ONS-A2.** This section previously forbade `OAuth2Write` outright, on a
   > security-review finding that a leaked token could modify or destroy live CAD. That risk is
   > real and unchanged; what changed is the judgement about how to handle it. Withholding write
   > made the read-only product safe and the actual product impossible. The replacement controls
   > are: the customer chooses at connect time, `OAuth2Delete` is never requested, and every write
   > passes the confirmation gate. Recorded rather than silently reversed.

4. Copy the client id and secret.

## 3. Configure Solus

```bash
SOLUS_ONSHAPE_CLIENT_ID=...
SOLUS_ONSHAPE_CLIENT_SECRET=...
# Where the callback returns the user (shared by every OAuth provider).
SOLUS_OAUTH_REDIRECT_APP=http://localhost:5173/#/onboarding
```

> **Renamed in CAD-01:** `SOLUS_GITHUB_OAUTH_REDIRECT_APP` → `SOLUS_OAUTH_REDIRECT_APP`. The
> setting was always provider-agnostic (GitLab already used it); Onshape made the GitHub name
> actively misleading. Update any `.env` that still sets the old name.

Secrets are read from the environment / AWS Secrets Manager and stored through `SecretStore` —
never in code, never returned by an API response.

## 4. Per-source configuration — a SELECTION, not typed ids

The OAuth grant is **account-level**, so connecting requires nothing to be typed in:
`config_fields` is empty and `validate_credentials` reads no config at all. After connecting, the
app lists the account's documents (`list_selectable` → `GET /api/v1/projects/{p}/sources/{s}/selectable`)
and the user picks which to track — the same connect-then-choose shape GitHub uses for repos.

The choice is stored as a **list of document ids** under `config["documents"]`:

```json
{ "documents": ["a1b2c3…", "d4e5f6…"] }
```

A list, not a map: `PATCH /sources/{id}` merges config and cannot delete keys, so only a
wholesale-replaced list actually shrinks when a document is deselected. Selecting **nothing** is
valid — the source is connected and idle.

Each id is validated against `^[A-Za-z0-9]{1,40}$` before it is interpolated into any request
path, and the selection is length-bounded — ingested config is untrusted input (CLAUDE.md §7).
Sync resolves each document's **default workspace** and every **assembly element** in it, bounded
by `max_elements`.

> **Legacy (CAD-01) sources.** A source whose config still carries
> `document_id`/`workspace_id`/`element_id` keeps working, pinned to exactly that element, via a
> read-time shim — no migration. Note its entity keys change (see §5), so it re-syncs into fresh
> rows with the old ones tombstoned.

## 5. What a sync does

Per **selected document**: resolve `defaultWorkspace` (`GET /api/v6/documents/{did}`), list its
its exportable elements (`GET /api/v6/documents/d/{did}/w/{wid}/elements`, filtered
client-side to `ASSEMBLY` and `PARTSTUDIO` — `elementType` is single-valued, so asking the
server for both families would cost a second call per document), then per element:

1. `GET /api/v6/documents/d/{did}/w/{wid}/currentmicroversion` — the change token.
2. `POST /api/v6/{assemblies|partstudios}/d/{did}/w/{wid}/e/{eid}/translations` with
   `formatName: STEP`. The collection follows the element's family — this is the ONLY
   element-type-specific URL in the ingest path; poll, download and part metadata are all
   type-agnostic.
3. Poll `GET /api/v8/translations/{requestId}` until `DONE` (bounded — 30 attempts by default,
   then `export_timeout`; never an unbounded loop against a third party).
4. `GET /api/v6/documents/d/{did}/externaldata/{id}` — the STEP bytes, size-bounded before parsing.
5. `GET /api/v6/parts/d/{did}/w/{wid}/e/{eid}` — part numbers and materials.
6. `parse_step` → `build_mechanical_graph` → `part` entities + `part_of` edges.

**Entity keys are namespaced `{document_id}:{element_id}:{occurrence_path}`.** A STEP occurrence
path is unique only _within_ one export, but a source now spans many documents and the runtime
upserts on `(source_id, external_ref)` — so two documents each holding a `Bracket` would otherwise
collapse into ONE graph row. That is a false merge created at the ingestion key, upstream of every
fingerprint guard, which is why the scope is not optional. Each entity also carries
`properties.document_id` / `element_id`.

**Partial failure is deliberately asymmetric.** `apply_sync_result` treats a result as a COMPLETE
snapshot and soft-deletes anything absent from it. So a document that Onshape reports **404 GONE**
is dropped (its entities are correctly reconciled away, with a `SyncError` recorded), while **any
other failure aborts the whole sync** — quietly omitting a document that merely timed out would
tombstone its entire subtree.

`detect_changes` compares each selected document's current microversion with the stored per-document
cursor (`{"microversions": {did: mv}}`), and **fails safe**: an unreachable API counts as changed,
so an outage schedules a sync rather than skipping one. A change to the SELECTION also counts as
changed, so newly picked documents get ingested and deselected ones reconciled. Onshape exposes no
account-level change feed, so this is one cheap probe per tracked document. The CAD-01 scalar
cursor is read as a one-document map so legacy sources do not re-sync for nothing.

## 6. Token expiry — expect refreshes

**Onshape access tokens are valid for 60 minutes** and the refresh token **rotates on every use**.
Solus stores the refresh token at `source/{source_id}/onshape/refresh` and refreshes
automatically: a sync that fails with `invalid_credentials` triggers one refresh, persists **both**
new tokens (refresh token first, so a mid-write failure leaves a recoverable state rather than a
stranded source), and retries once. See `docs/contracts/connector-interface.md` Edit 6.

Disconnecting a source, or deleting the account, removes **both** secrets — the refresh token does
not outlive the access token.

## 7. Part numbers and the fingerprint

STEP's product structure has **no part-number field**. Part numbers come from Onshape's parts
metadata and are joined to STEP products **by name**, then written to
`modality_hints["part_number"]` — the only channel the fingerprint matcher uses to seed a merge.

**So a CAD part collapses onto its schematic symbol only where the team has filled in the Onshape
part-number field with a real MPN.** An Onshape part id (e.g. `JHD-0007-a1b2`) is not an MPN and is
never invented into that channel. If the metadata call fails the sync still lands the full assembly
tree, with the loss recorded on the Sync row.

## 8. What the read-only scope does NOT give you

`OAuth2Read` alone carries **no PII**. Confirmed against a live tenant
(`sessioninfo.oauth2Scopes == 1`): `email` and `name` come back empty and only the opaque user
`id` is populated. SOLUSDEV-260 keeps that id for account matching but never uses it as
an account label. When the provider supplies identity fields, the label prefers its display
name, then email. If neither is available, it shows **Onshape account**; it does not substitute
the Solus user's email or claim that the grant exposed an address.

Do **not** widen to the PII scope for a friendlier label; §2 forbids it, and a leaked token would
then carry the customer's identity for no capability Solus uses.

**"No documents" is usually true.** `GET /api/v6/documents` lists documents the account **owns**;
filters 0/1/2/5/6 all return empty for an account with none. Only `filter=4` (public documents)
returns rows, and Solus deliberately does not use it — see the API-terms note below.

## 9. Account and licensing constraints

- Onshape's **free personal plan makes every document public and forbids commercial use**, and its
  API terms prohibit automated extraction from public documents. Team tenants need **paid seats**.
- A **private (unpublished) OAuth app's calls still count against the API rate cap** exactly like
  API keys — the exemption is a property of the _published_ app. Plan for App Store publication
  before high-volume use.
- **429 handling (SOLUSDEV-64):** the connector treats a 429 as an expected operating condition —
  every API call (and the externaldata download) retries up to 3 times, honoring `Retry-After`
  when it is a plain integer (capped at 30s; the header is untrusted) and falling back to
  exponential backoff otherwise. Rate limiting that outlasts the retries surfaces as a
  `rate_limited` connector error rather than a generic `api_error`, and the sync aborts without
  tombstoning existing entities.

## 10. Not yet built

- **Live verification owed.** The HTTP paths and payload shapes above were written from Onshape's
  public API documentation, not captured from a live tenant. One confirmation run against a real
  document is owed before this is called production-ready; the fixtures in
  `packages/api/tests/fixtures/onshape_sample.py` name the endpoint each payload stands for so the
  pass is mechanical. **The document/workspace/element enumeration endpoints added for the
  account-level selection inherit this risk** — expect payload-shape corrections on the first run
  against a real tenant.
- **Onshape's `limit` cap.** `/documents` answers **400** for `limit > 20`, found on the first
  live run — the connector now asks for 20 per page and pages for the rest. Treat any other
  documented "max" in the fixtures as similarly unverified.
- **Element granularity.** A selected document ingests every exportable element in its default
  workspace — assemblies AND Part Studios (SOLUSDEV-168). Picking individual elements, or a
  non-default branch, is not offered. Cost scales with a document's exportable tabs.
- **Part Studios are flat.** A Part Studio STEP export has no assembly tree, so it yields
  entities and **zero `part_of` relations**, and every node's `is_assembly` is false. This is
  what `docs/contracts/metadata-extraction.md` was amended for; anything reading
  `properties["is_assembly"]` or expecting a tree must tolerate it.
- **The same part can be ingested twice.** Part metadata is joined to STEP products by NAME
  (there is no shared id), and an assembly and a Part Studio in one document routinely hold the
  same named parts. They land under two `external_ref`s carrying the same `part_number`, which
  the fingerprint matcher seeds merges on. That is intended — recognising one physical part
  across representations is what the multimodal fingerprint is for — but it means Part Studio
  ingestion deliberately feeds the matcher duplicates.
- **Per-element microversions are real, cross-tab staleness is not proven.** `GET …/elements`
  returns a distinct `microversionId` per element (verified against a live tenant 2026-09-03:
  two elements in one document reported different values, so it is not the document's
  microversion echoed). What is NOT established is whether an element's microversion advances
  when its geometry changes because ANOTHER tab changed — a variable, a derived part, an
  in-context feature. Any future export cache keyed on element microversion must either prove
  that case or invalidate on the document microversion instead.
