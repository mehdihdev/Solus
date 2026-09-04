# extensions.md — Extensions & Store Route Plan

**Ticket:** SOLUSDEV-235 (branch `SOLUSDEV-235-solus-extensions`), task EXT-00.
**Status:** PLANNED (tier-1 route-plan amendment, ADR-032 — agent-editable, the MR review is
the approval gate). Documented BEFORE implementation per the authority hierarchy (#3: no
undocumented routes). The implementing tasks are the EXT-xx backend tasks on the same ticket.
**Provenance:** Written from the fixed decisions of the SOLUSDEV-235 Phase 1 design review
(ratified in-session 2026-09-03), which produced ADR-035 and the ADR-034 amendment of the same
date. The data model this plan reads and writes is documented in `docs/schemas/extensions.md`
(same ticket, separate task); this file references its table names and never redefines them.
**Authority:** ADR-035 (sandboxed views, permission-checked host bridge, open registry with
manual verification) · ADR-034 amendment 2026-09-03 (`~/.solus/extensions/<id>/<version>/`
cache, hash-verified against THIS registry) · ADR-018/019/024 (extension-originated SOL turns
are metered to the invoking user, attributed to the extension) · ADR-025 (roles; project
scoping anchor `project.team_id`) · `docs/contracts/extension-manifest.md` (the `extension.toml`
contract: slug rule, closed scope set, settings fields, `[store]` asset references, byte caps) ·
[artifacts.md](artifacts.md) §4.4/§4.6 (upload hygiene and the `ArtifactStore` protocol the
bundle path reuses) · API.md §1 conventions (envelope, errors, cursor pagination, 202 + Job,
`Idempotency-Key`, rate-limit headers, metering classes) · `docs/wireflows/store.md` (the Store
surface these routes serve) · CLAUDE.md §7 (uploads, tenant isolation, untrusted developer
input, model-orchestration attribution).
**Consumers:** the desktop Store UI (catalog, detail, install/uninstall, settings, permissions);
the desktop MAIN-process installer (bundle download + hash verification into the ADR-034 cache);
the renderer bridge host (`storage.own` backing store, `sol.ask` attribution header); the Live
Bench widget canvas (per-user widget layout); team owners (policies); extension developers
(publish, review status, unpublish); Solus staff (verified badge).

---

## 1. Why this exists

ADR-035 makes extensions **versioned bundles published by anyone and installed per project**.
That needs a registry the Store can read without unzipping anything, a publish path that treats
the bundle as untrusted developer input, per-project install state (pinned version, enabled flag,
validated settings, granted permissions), a small server-side key-value store behind the
`storage.own` scope, per-user widget layouts, team-level policy, and a way for the existing SOL
routes to attribute extension-originated turns to the extension while still metering the user.

Every route here is **Unmetered** (API.md §1.5): nothing on this surface calls a model. The only
metered consequence of an extension is a SOL turn it asks the host to make, and that is charged
on the EXISTING SOL routes (§9) — this plan adds attribution to them, never a second meter.

### Tables referenced (defined in `docs/schemas/extensions.md`)

| table                      | one row per                                                                                             | read/written by                 |
| -------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------- |
| `extension_publishers`     | publishing user                                                                                         | §5 publish                      |
| `extensions`               | slug (= manifest `extension.id`)                                                                        | §4 catalog, §5, §6, §10         |
| `extension_versions`       | (extension, semver)                                                                                     | §4, §5, review job              |
| `extension_version_assets` | store-facing file of a version                                                                          | §4.5 assets, review job         |
| `extension_installs`       | (project, extension)                                                                                    | §6 installs, §7, §9 attribution |
| `extension_storage`        | (project, extension, key)                                                                               | §7 storage                      |
| `team_extension_policies`  | (team, extension)                                                                                       | §10 policy, read by §6          |
| `widget_layouts`           | (project, user)                                                                                         | §8                              |
| `ArtifactStore` (protocol) | stored bundle / extracted asset bytes, keyed by the owning row id — NO `artifacts` row (project-scoped) | §5, §4.4/4.5                    |
| `credit_ledger` (existing) | gains nullable `extension_id`                                                                           | §9 attribution                  |
| `data_events` (existing)   | every write and every bridge refusal (§11)                                                              | all                             |

`extensions.verified` is a **manual Solus-staff flag** (ADR-035 §5) and lives on the extension
row, never on the publisher. `extensions.install_count` is a cached counter maintained by §6
install/uninstall. `extensions.latest_approved_version_id` is maintained by the review job and
by §5.4 unpublish.

---

## 2. Route table

All paths are under `/api/v1`; every response uses the standard envelope; every list is
cursor-paginated (`?cursor=&limit=`, `meta.has_next`, `meta.next_cursor`). Auth is the
centralized middleware (`CurrentUser`, `ProjectCtx`, `TeamCtx`, `require_role`,
`RequireVerified` from `deps.py`) — never per-route logic.

### 2.1 Catalog — signed-in, tenant-free reads of approved content

| Method | Path                                                  | Purpose                                                           | Success |
| ------ | ----------------------------------------------------- | ----------------------------------------------------------------- | ------- |
| GET    | `/extensions?q=&cursor=&limit=`                       | Catalog list — only extensions with an approved version           | `200`   |
| GET    | `/extensions/{slug}`                                  | Detail: latest approved version's manifest, asset URLs, publisher | `200`   |
| GET    | `/extensions/{slug}/versions`                         | Approved versions (publisher also sees pending/checking/rejected) | `200`   |
| GET    | `/extensions/{slug}/versions/{version}/bundle`        | The zip bytes (approved; publisher may fetch own pending)         | `200`   |
| GET    | `/extensions/{slug}/versions/{version}/assets/{path}` | A store-facing asset recorded in `extension_version_assets`       | `200`   |

### 2.2 Publishing — signed-in developer, verified email

| Method | Path                                           | Purpose                                                      | Success |
| ------ | ---------------------------------------------- | ------------------------------------------------------------ | ------- |
| POST   | `/extensions/publish`                          | Multipart bundle upload → version row `pending` + review job | `202`   |
| GET    | `/extensions/{slug}/versions/{version}/review` | Review status + problems (publisher only)                    | `200`   |
| DELETE | `/extensions/{slug}/versions/{version}`        | Unpublish a version (soft delete; installs keep their pin)   | `204`   |
| PATCH  | `/extensions/{slug}`                           | `{ verified: bool }` — Solus staff only                      | `200`   |

### 2.3 Project installs — `ProjectCtx`, `member` floor on writes

| Method | Path                                                     | Purpose                                                       | Success       |
| ------ | -------------------------------------------------------- | ------------------------------------------------------------- | ------------- |
| GET    | `/projects/{project_id}/extensions`                      | Installed extensions with pin, state, grants, update, policy  | `200`         |
| PUT    | `/projects/{project_id}/extensions/{slug}`               | Install (`201`) or update the pinned version / grants (`200`) | `201` / `200` |
| PATCH  | `/projects/{project_id}/extensions/{slug}`               | `{ enabled?, settings? }`                                     | `200`         |
| DELETE | `/projects/{project_id}/extensions/{slug}`               | Uninstall (install row + this extension's storage rows)       | `204`         |
| GET    | `/projects/{project_id}/extensions/{slug}/storage/{key}` | Read one `storage.own` value                                  | `200`         |
| PUT    | `/projects/{project_id}/extensions/{slug}/storage/{key}` | Write one value (create `201`, replace `200`)                 | `201` / `200` |
| DELETE | `/projects/{project_id}/extensions/{slug}/storage/{key}` | Delete one value                                              | `204`         |
| GET    | `/projects/{project_id}/widget-layout`                   | The caller's widget layout for this project                   | `200`         |
| PUT    | `/projects/{project_id}/widget-layout`                   | Replace the caller's layout                                   | `200`         |

### 2.4 Team policy — `TeamCtx`, `owner` only

| Method | Path                                          | Purpose                                                      | Success       |
| ------ | --------------------------------------------- | ------------------------------------------------------------ | ------------- |
| GET    | `/teams/{team_id}/extensions/policies`        | List policies                                                | `200`         |
| PUT    | `/teams/{team_id}/extensions/policies/{slug}` | Upsert `{ blocked?, default_installed?, default_settings? }` | `201` / `200` |
| DELETE | `/teams/{team_id}/extensions/policies/{slug}` | Reset (delete the policy row)                                | `204`         |

### 2.5 Attribution on EXISTING routes (no new path)

| Header                      | Applies to                                                                                                                     | Effect                                                                                 |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| `X-Solus-Extension: <slug>` | `POST /projects/{project_id}/sol/conversations/{id}/messages` (live, API-implementation.md §11) and the §2.9 agent turn routes | Accepted only with an enabled install granting `sol.ask`; else `403 scope_denied` (§9) |

---

## 3. Conventions specific to this surface

- **`{slug}`** in every path is the manifest `extension.id` (`^[a-z][a-z0-9-]{1,63}$`), matched
  case-insensitively against `extensions.slug`. A path segment failing the regex → `422
validation_error` before any lookup (no DB round-trip on garbage).
- **`{version}`** is a semver string exactly as stored on `extension_versions.version`. Any
  version the caller may not see (unapproved and caller is not the publisher; soft-deleted) is
  `404 not_found` — the same no-existence-oracle posture as [artifacts.md](artifacts.md) §3.
- **Tenant-free catalog.** Approved extensions are global content (the ADR-033 precedent for a
  tenant-free table): §4 routes need only `CurrentUser`, no team or project. Nothing in §4 ever
  discloses which teams or projects installed an extension — `install_count` is an aggregate.
- **Asset and bundle URLs** returned anywhere are the relative **API routes** of §4.4/§4.5, never
  a storage-internal locator (`ArtifactStore` S3 keys / local paths never leave the server —
  artifacts.md §4.6 "single authz path").
- **Roles** are the `Role` enum in `models.py` (`owner > admin > member > viewer`). "`member`
  floor" means `require_role(ctx, Role.MEMBER)` — a `viewer` or an ADR-025 share-only user
  (`ProjectContext.membership is None`) gets `403 forbidden`; a non-member gets `404 not_found`
  from `ProjectCtx` itself. **Reads are exempt from the floor** (orchestrator decision
  2026-09-03): `GET …/extensions` (§6.1), `GET …/storage/{key}` (§7) and `GET …/widget-layout`
  (§8) succeed for anyone `ProjectCtx` admits, because a viewer must still be able to render the
  project's installed extension views and their own canvas. Every write keeps the `member` floor.
- **Staff** = user ids listed in the `SOLUS_STAFF_USER_IDS` setting (Secrets Manager / env,
  comma-separated UUIDs), evaluated server-side by a `RequireStaff` dependency in `deps.py` (so
  CLAUDE.md §7's "no per-endpoint ad-hoc auth" holds literally). Everyone else → `403 forbidden`.
  Staff status is never returned by any route and never derived from a publisher name.
- **Verified email** (`RequireVerified`) is required on `POST /extensions/publish`, `DELETE
…/versions/{version}` and `PATCH /extensions/{slug}` — the same gate as other sensitive writes
  (SOLUSDEV-82).
- **Data events** (ADR-011): every write and every bridge refusal emits one of the events in §11,
  server-side, consent-gated like every other event.

---

## 4. Catalog routes

### 4.1 GET /api/v1/extensions — list

Query: `q` (≤ 80 chars; case-insensitive match on `slug`, `name`, `summary`), `cursor`, `limit`
(default 24, max 100). Sorted by `name` ascending, cursor over `(name, id)`. Only extensions with
`latest_approved_version_id IS NOT NULL` appear. Nothing here is per-project: the Store's
"available for THIS project" suggestions are computed client-side from `requires` against the
project's connected sources (wireflow: gated on connected sources, never on popularity).

`200`:

```json
{
  "data": [
    {
      "slug": "bom",
      "name": "BOM",
      "summary": "Bill of materials from your EDA project.",
      "publisher": { "display_name": "Solus" },
      "verified": true,
      "install_count": 412,
      "latest_version": {
        "version": "1.2.0",
        "published_at": "2026-09-01T09:12:03.000Z"
      },
      "requires": [["eda"]],
      "views": ["widget", "page"],
      "updated_at": "2026-09-01T09:12:03.000Z"
    }
  ],
  "meta": {
    "has_next": true,
    "next_cursor": "eyJuYW1lIjoiQk9NIiwiaWQiOiIwMTk5In0"
  }
}
```

`requires` and `views` are read from the approved version's stored manifest; `views` is the list
of keys present in the manifest's `[views]` (`widget | page | window`).

### 4.2 GET /api/v1/extensions/{slug} — detail

`200`:

```json
{
  "data": {
    "slug": "bom",
    "name": "BOM",
    "summary": "Bill of materials from your EDA project.",
    "publisher": { "display_name": "Solus" },
    "verified": true,
    "install_count": 412,
    "version": {
      "version": "1.2.0",
      "published_at": "2026-09-01T09:12:03.000Z",
      "content_hash": "9f2c0b1e4d…64 hex…",
      "bundle_size_bytes": 1834112,
      "bundle_url": "/api/v1/extensions/bom/versions/1.2.0/bundle"
    },
    "manifest": {
      "schema_version": 1,
      "extension": {
        "id": "bom",
        "name": "BOM",
        "version": "1.2.0",
        "publisher": "Solus",
        "summary": "…",
        "requires": [["eda"]]
      },
      "views": {
        "widget": {
          "entry": "widget.html",
          "preferred": "wide",
          "minimum": "standard"
        },
        "page": { "entry": "page.html", "icon": "icon.svg", "label": "BOM" }
      },
      "permissions": {
        "scopes": ["graph.read", "sources.read"],
        "network": ["https://api.octopart.com"]
      },
      "settings": {
        "fields": [
          {
            "key": "refresh",
            "type": "select",
            "label": "Run frequency",
            "options": ["every_sync", "hourly", "daily", "manual"],
            "default": "every_sync"
          }
        ]
      },
      "store": {
        "overview": "OVERVIEW.md",
        "privacy_policy": "PRIVACY.md",
        "links": { "documentation": "https://…" },
        "screenshots": ["shots/table.png"],
        "sections": [{ "title": "How it works", "body": "docs/HOW.md" }]
      }
    },
    "assets": {
      "overview": "/api/v1/extensions/bom/versions/1.2.0/assets/OVERVIEW.md",
      "privacy_policy": "/api/v1/extensions/bom/versions/1.2.0/assets/PRIVACY.md",
      "icon": "/api/v1/extensions/bom/versions/1.2.0/assets/icon.svg",
      "screenshots": [
        "/api/v1/extensions/bom/versions/1.2.0/assets/shots/table.png"
      ],
      "sections": [
        {
          "title": "How it works",
          "url": "/api/v1/extensions/bom/versions/1.2.0/assets/docs/HOW.md"
        }
      ]
    },
    "created_at": "2026-08-20T14:02:11.000Z",
    "updated_at": "2026-09-01T09:12:03.000Z"
  }
}
```

`manifest` is the stored `extension_versions.manifest` jsonb of the latest approved version,
already contract-validated at publish time — the Store renders it without re-parsing TOML.
`assets` carries only URLs whose `path` exists in `extension_version_assets` for that version
(`privacy_policy` / `icon` are `null` when the manifest declares none). A slug with no approved
version → `404 not_found` for everyone except its publisher, who receives the detail with
`version: null`, `manifest: null`, `assets: null` (so a developer can see their own unreleased
listing without a leak to anyone else).

### 4.3 GET /api/v1/extensions/{slug}/versions — versions

Cursor-paginated, newest first (semver descending). Everyone sees approved, non-deleted versions.
The **publisher** additionally sees `pending | checking | rejected` versions with their
`review_problems`; nobody else can learn such a version exists (it is simply absent).

`200` (as the publisher):

```json
{
  "data": [
    {
      "version": "1.3.0",
      "review_status": "rejected",
      "review_problems": [
        "store.screenshots[0]: shots/big.png is 1.4 MiB, cap is 1 MiB"
      ],
      "published_at": null,
      "content_hash": "3ab0…",
      "bundle_size_bytes": 2670001,
      "created_at": "2026-09-02T18:40:00.000Z"
    },
    {
      "version": "1.2.0",
      "review_status": "approved",
      "published_at": "2026-09-01T09:12:03.000Z",
      "content_hash": "9f2c…",
      "bundle_size_bytes": 1834112,
      "created_at": "2026-09-01T09:10:41.000Z"
    }
  ],
  "meta": { "has_next": false, "next_cursor": null }
}
```

`review_problems` is present only in the publisher's view and only when `review_status` is
`rejected`; the strings are the contract's dotted-path problem messages (`manifest_problems`) plus
the review job's bundle-level findings.

### 4.4 GET /api/v1/extensions/{slug}/versions/{version}/bundle — the zip

`200` — the stored zip bytes streamed from `ArtifactStore`, `Content-Type: application/zip`,
`Content-Length: <bundle_size_bytes>`, `X-Solus-Content-Hash: <sha256 hex of the bytes>`. The
desktop MAIN process verifies the hash before writing the bundle into
`~/.solus/extensions/<id>/<version>/` (ADR-034 amendment) and refuses a mismatch.

Visible to everyone when the version is `approved` and not soft-deleted; the **publisher may also
fetch their own `pending | checking | rejected` versions** (to reproduce a review finding
locally). Any other case → `404 not_found` — never a `403`, so a non-publisher cannot confirm an
unapproved version exists. The route serves the stored bytes only: never unzips, transforms, or
executes them.

### 4.5 GET /api/v1/extensions/{slug}/versions/{version}/assets/{path} — store-facing assets

Serves ONLY a file whose `path` is recorded in `extension_version_assets` for that version — the
review job extracted exactly the files the manifest's `[store]` and `views.page.icon` name
(`OVERVIEW.md`, `PRIVACY.md`, `[[store.sections]].body`, `store.screenshots[]`, the page icon).
Anything else — an entry HTML, a JS file, a path with `..`, a file that is in the zip but not in
the table — is `404 not_found`. The route path is compared as a whole string to the stored
`path`; no filesystem or zip lookup ever happens in the request.

`200` — `Content-Type` is the stored `media_type`: `text/markdown; charset=utf-8` for `.md`,
`image/png` / `image/webp` for screenshots, `image/svg+xml` for the icon **after publish-time
sanitization** (the review job reduces the icon to the path-only monochrome subset ADR-035 §3
requires — no scripts, no external references, no `<foreignObject>`; the sanitized bytes are what
is stored and served, never the original). `Content-Length` and `Cache-Control: private,
max-age=86400, immutable` are set (a version's assets never change once approved). Same
visibility rule as §4.4 (approved for everyone, own pending for the publisher).

---

## 5. Publishing routes

### 5.1 POST /api/v1/extensions/publish — publish a version (`202`)

Dependencies: `CurrentUser` + `RequireVerified`. `Idempotency-Key` header **required**
(`400 idempotency_key_required` without it) — replaying the same key with the same body returns the
original `202` response; the same key with different bytes → `409 idempotency_conflict`.

`multipart/form-data`:

| part     | type | required | notes                                                                                          |
| -------- | ---- | -------- | ---------------------------------------------------------------------------------------------- |
| `bundle` | file | yes      | the zip; `Content-Type` of the part `application/zip`; ≤ **25 MiB** (`MANIFEST_LIMITS.bundle`) |

Any other form field → `422 validation_error` (unknown fields rejected — the same posture as
artifacts.md §2).

Request-path processing, in order — nothing here fully unzips or executes the bundle:

1. `Content-Length` required (`411 length_required` when absent or non-integer — artifacts.md
   §4.4 M1); over the cap → `413 payload_too_large` BEFORE the body is read, and again while
   streaming (`read_bounded`) so a lying header cannot overshoot.
2. The zip's central directory is read with a **bounded reader**
   (`extensions.bundle.inspect_bundle_structure`): entry count ≤ 2,000, every declared
   uncompressed size summed ≤ 25 MiB plus a per-entry compression-ratio guard (zip-bomb guards),
   no absolute or `..` names, no symlinks, allowed suffixes only; violations → `422 bundle_invalid`
   with the offending entry named. Only ONE entry is inflated in the request path —
   `extension.toml` at the root, ≤ 64 KiB — decoded with stdlib `tomllib` and validated with
   `parse_extension_manifest` (the contract). Every other member is inflated only by the review
   job, under a cumulative 25 MiB decompressed budget.
   Contract problems → `422 validation_error` with `details` = the dotted-path problem strings
   (identical text to the desktop developer mode).
3. Slug claim: if `extensions.slug` (case-insensitive) does not exist, the slug is claimed for
   this publisher; an `extension_publishers` row is created on the user's first publish
   (`display_name` seeded from the manifest's `extension.publisher`). If the slug is owned by
   another publisher → `409 slug_taken`. If `(extension, version)` already exists (including a
   soft-deleted one — a version string is never reused) → `409 version_exists`.
4. The bundle bytes are stored through the `ArtifactStore` PROTOCOL under key =
   `extension_versions.id` (no `artifacts` row: that table is project-scoped and cascades on
   project delete, while the registry is global — `docs/schemas/extensions.md` §8.1);
   `bundle_storage` records the backend, `content_hash = sha256(bytes)`, `bundle_size_bytes`.
5. `extension_versions` row created with `review_status = pending`, `manifest` = the validated
   manifest, `published_at = null`; `extension.publish` event emitted; the `extension_review`
   ARQ job is enqueued.

`202 Accepted` — no `jobs` row and no `Location` header: the `jobs` table is project-scoped and
the registry has no project, so review progress is polled through §5.2 instead (integration
decision, 2026-09-03):

```json
{
  "data": {
    "version": {
      "slug": "bom",
      "version": "1.3.0",
      "review_status": "pending",
      "content_hash": "3ab0c7…",
      "bundle_size_bytes": 2670001,
      "bundle_url": "/api/v1/extensions/bom/versions/1.3.0/bundle",
      "review_url": "/api/v1/extensions/bom/versions/1.3.0/review",
      "created_at": "2026-09-02T18:40:00.000Z"
    },
    "review": { "status": "pending", "problems": [] }
  }
}
```

**The review job** (`JobKind.EXTENSION_REVIEW`, ARQ, queue-level concurrency-limited so one
publisher cannot monopolize the worker pool): sets `checking`; re-validates the manifest; walks
the zip under the same bomb/traversal guards; enforces the per-file byte caps
(`MANIFEST_LIMITS`: icon 16 KiB, overview 32 KiB, section 16 KiB, screenshot 1 MiB); enforces an
**asset-type allowlist** for the whole bundle (`.html .js .css .svg .png .webp .md .json .toml
.woff2` — anything else, e.g. `.wasm`, `.exe`, `.sh`, `.node`, is a rejection); verifies every
file the manifest references exists; sanitizes the icon SVG; extracts the `[store]` files and the
icon into `extension_version_assets` (bytes via `ArtifactStore` under key = the asset row id,
`storage`, `media_type`, `size`); then sets
`approved` (with `published_at = now`, and `extensions.latest_approved_version_id` to this version
if it is the highest approved semver) or `rejected` with `review_problems`. It emits
`extension.review_completed` and the Job resolves per API.md §2.16. Nothing in the job executes
bundle content.

Rate limit: `extension_publishes_per_hour_per_user` (default **10**) → `429 rate_limited` +
`Retry-After`.

### 5.2 GET /api/v1/extensions/{slug}/versions/{version}/review — review status

Publisher only; anyone else → `404 not_found` (the review of a version you did not publish does
not exist for you). `200`:

```json
{
  "data": {
    "slug": "bom",
    "version": "1.3.0",
    "review_status": "rejected",
    "review_problems": [
      "store.screenshots[0]: shots/big.png is 1.4 MiB, cap is 1 MiB",
      "bundle: vendor/helper.wasm has a disallowed asset type"
    ],
    "published_at": null
  }
}
```

`review_problems` is `[]` for `pending | checking | approved` (the field is always present; `checked_at` is not returned — there is no backing column).

### 5.3 DELETE /api/v1/extensions/{slug}/versions/{version} — unpublish

Publisher only (`RequireVerified`); others → `404`. Soft-deletes the version row: the Store hides
it (§4.1–§4.5 return `404` for it), `extensions.latest_approved_version_id` is recomputed to the
highest remaining approved version (or `null`, which removes the extension from the catalog
entirely). **Existing installs keep their pinned copy** — `extension_installs.version_id` still
resolves, the desktop's ADR-034 cache remains valid, and `GET /projects/{id}/extensions` keeps
reporting the pinned version (with `update_available` computed against the remaining approved
versions). A version string, once used, is never reusable (§5.1 step 3). `204 No Content`.

### 5.4 PATCH /api/v1/extensions/{slug} — verified badge (staff only)

Dependencies: `CurrentUser` + `RequireVerified` + `RequireStaff` (§3). Body `{ "verified": bool
}` — exactly this one field; any other key, including `summary`, `name` or `publisher`, is `422
validation_error` (those come from the manifest and change only through a new published
version; a publisher has NO `PATCH` on this route — `403 forbidden` for every non-staff caller
regardless of ownership). `200` returns the §4.2 detail shape. Staff membership is never disclosed
in any response.

---

## 6. Project install routes (`ProjectCtx`; `member` floor on writes)

Every route in this section resolves the project through `ProjectCtx` (non-member → `404`).
Writes (§6.2–§6.4) then apply `require_role(ctx, Role.MEMBER)` (viewer / share-only →
`403 forbidden`); the read (§6.1) has no role floor (§3). Team policy is read from
`team_extension_policies` for `ctx.project.team_id` on every write.

### 6.1 GET /api/v1/projects/{project_id}/extensions — installed extensions

Cursor-paginated (default `limit` 50, max 200 — a project rarely exceeds a page). Each item is the
join of the install row, its pinned version, the latest approved version, and the team policy:

```json
{
  "data": [
    {
      "extension": {
        "slug": "bom",
        "name": "BOM",
        "verified": true,
        "publisher": { "display_name": "Solus" }
      },
      "version": {
        "version": "1.2.0",
        "content_hash": "9f2c…",
        "bundle_size_bytes": 1834112,
        "bundle_url": "/api/v1/extensions/bom/versions/1.2.0/bundle",
        "manifest": { "…": "the pinned version's manifest, §4.2 shape" }
      },
      "enabled": true,
      "settings": { "refresh": "hourly" },
      "granted_scopes": ["graph.read", "sources.read"],
      "granted_network": ["https://api.octopart.com"],
      "update_available": { "version": "1.3.0", "widens_permissions": false },
      "policy": { "blocked": false, "default_installed": true },
      "installed_by": "019ebe5b-7aca-7770-acbb-c1897f15f46e",
      "installed_at": "2026-08-28T10:00:00.000Z",
      "updated_at": "2026-09-01T12:30:00.000Z"
    }
  ],
  "meta": { "has_next": false, "next_cursor": null }
}
```

- `manifest` is the **pinned** version's manifest — the desktop renders and validates settings
  against what is actually installed, not the newest listing.
- `update_available` is `null` when the pinned version is the latest approved; otherwise it names
  the latest approved version and whether its declared `permissions` exceed the current grants
  (so the Store can show "update requires new permissions" before the user clicks).
- `policy` reflects the team row (`{ blocked: false, default_installed: false }` when none).
  **A blocked extension is reported with `enabled: false`** regardless of the stored flag (§10).
- What this route does NOT carry: the availability of every catalog extension for this project.
  The client computes suggestions from `requires` × the project's connected sources.

### 6.2 PUT /api/v1/projects/{project_id}/extensions/{slug} — install or update

Body (`extra="forbid"`):

```json
{
  "version": "1.3.0",
  "grants": {
    "scopes": ["graph.read", "sources.read"],
    "network": ["https://api.octopart.com"]
  }
}
```

- `version` optional — defaults to the latest approved version. Must name an approved,
  non-deleted version (`404 not_found` otherwise; the publisher's own pending versions are NOT
  installable — installs come only from the catalog).
- `grants` required. `scopes` ⊆ the target version's `permissions.scopes` and `network` ⊆ its
  `permissions.network` (exact-string origin match); any grant not declared by the manifest →
  `422 validation_error` with `details` listing the undeclared entries. Granting fewer than
  declared is allowed (the bridge refuses the ungranted ones at call time).
- Team policy `blocked = true` → `403 extension_blocked` (nothing written).
- **Update semantics** (install exists, `version` differs): if the target version declares any
  scope or network origin not in the CURRENT grants and the body's `grants` does not include
  them → `409 grants_required`, `details: [{ "scopes": [...new...], "network": [...new...] }]`.
  The client re-prompts the user with the concrete additions and retries with widened grants.
  A version change that narrows permissions is applied silently and the install's grants are
  intersected with the new declaration.
- Settings on install: the install's `settings` are seeded from the team policy's
  `default_settings` (keys the manifest declares, values type-checked; unknown keys dropped),
  then manifest field defaults for the rest.
- `enabled` is `true` on first install; an update keeps the stored flag.

`201 Created` on first install, `200 OK` on update — both return the §6.1 item shape. Increments
`extensions.install_count` on `201`. Events: `extension.install` (201) or
`extension.grants_changed` (200 with changed grants) — see §11.

### 6.3 PATCH /api/v1/projects/{project_id}/extensions/{slug} — enable / settings

Body (`extra="forbid"`; at least one key): `{ "enabled"?: bool, "settings"?: object }`.

- `settings` is validated against the **pinned** manifest's `[settings]`: unknown key → `422`;
  wrong type for `boolean | number | string | select` → `422`; a `select` value outside
  `options` → `422`; a `number` outside `min`/`max` → `422`; the encoded object ≤ **16 KiB** →
  `422` beyond. The object REPLACES the stored settings (missing declared keys fall back to
  manifest defaults). Emits `extension.settings_changed` with the changed keys (never values —
  settings may carry a user's private choices).
- `enabled: true` on a team-blocked extension → `403 extension_blocked`; `enabled: false` is
  always allowed. Emits `extension.enable` / `extension.disable`.

`200` → the §6.1 item. Unknown slug for this project → `404 not_found`.

### 6.4 DELETE /api/v1/projects/{project_id}/extensions/{slug} — uninstall

Deletes the `extension_installs` row and every `extension_storage` row for
`(project_id, extension_id)` in one transaction; decrements `extensions.install_count`. Graph data
the extension produced (e.g. findings raised via `findings.write`) **stays** — it is the team's
data. The caller's `widget_layouts` entries referencing `ext:<slug>` are left as-is (the canvas
skips refs with no install; the user's arrangement survives a reinstall). `204 No Content`; emits
`extension.uninstall`. Unknown slug for this project → `404`.

---

## 7. Storage routes — the `storage.own` backing store

`/api/v1/projects/{project_id}/extensions/{slug}/storage/{key}` — `ProjectCtx`; `member` floor on PUT/DELETE, no floor on GET (§3),
THEN: the install must exist, be `enabled`, not be team-blocked, and have `storage.own` in
`granted_scopes`; otherwise `403 scope_denied` (and `extension.bridge_refused` is emitted — the
bridge host should never have let the call through, so a refusal here is a signal). No install at
all → `404 not_found`.

`{key}`: `^[A-Za-z0-9_.-]{1,64}$` → `422` otherwise.

- **GET** → `200 { "data": { "key": "cache", "value": <any JSON>, "size_bytes": 812, "updated_at": "…" } }`;
  unknown key → `404 not_found`.
- **PUT** — body is the raw JSON value (any JSON type), encoded size ≤ **64 KiB** →
  `413 payload_too_large` beyond. The projected total for `(project, extension)` after the write
  must be ≤ **256 KiB** (`storage.own` contract cap) → `413 storage_quota_exceeded` with
  `details: [{ "used_bytes": 261000, "limit_bytes": 262144 }]`. `201` on create, `200` on
  replace, same body as GET.
- **DELETE** → `204`; unknown key → `404`.

Values are opaque to Solus: never parsed, never entered into any prompt, never returned to any
other project or extension. A cross-project or cross-extension read is structurally impossible —
the row key is `(project_id, extension_id, key)` and both ids come from the resolved context,
never from the body. Rate limit: `extension_storage_writes_per_minute_per_install` (default
**120**) → `429`.

---

## 8. Widget layout — `GET|PUT /api/v1/projects/{project_id}/widget-layout`

Per `(project_id, user_id)` — the caller's own arrangement of the Live Bench widget canvas.
`ProjectCtx`; `member` floor on PUT, no floor on GET (§3).

`GET` → `200`; a user with no stored row receives the empty default:

```json
{
  "data": {
    "project_id": "019ebe61-ef4e-72e1-8726-5905455db85a",
    "layout": [
      { "ref": "builtin:signals", "size": "wide" },
      { "ref": "ext:bom", "size": "standard" }
    ],
    "updated_at": "2026-09-01T12:30:00.000Z"
  }
}
```

(`layout: []`, `updated_at: null` for the default.)

`PUT` body `{ "layout": [ { "ref", "size" } ] }` (`extra="forbid"`), replacing the whole layout:

- ≤ **24** slots → `422` beyond;
- `ref` matches `^builtin:[a-z][a-z0-9-]{0,63}$` or `^ext:[a-z][a-z0-9-]{1,63}$` (the second
  half is the manifest slug rule) → `422` otherwise; refs must be distinct → `422`;
- `size` ∈ `compact | standard | wide | full` (CTR-01 slot sizes) → `422` otherwise.

`ext:` refs are NOT checked against installs at write time (a layout may be saved before an
install completes, and survives an uninstall — §6.4); the canvas resolves them at render. `200`
returns the GET shape. No data event (pure per-user display state — not a meaningful
interaction per ADR-011).

---

## 9. Bridge attribution on EXISTING SOL routes — `X-Solus-Extension`

When the desktop bridge host performs a `sol.ask` call on behalf of an extension, it makes the
ordinary SOL turn request (`POST /api/v1/projects/{project_id}/sol/conversations/{id}/messages`,
API-implementation.md §11; and the §2.9 `agent/conversations` turn routes when they land) with
the header **`X-Solus-Extension: <slug>`**. Server-side, in the SOL router BEFORE admission:

1. The header value must match the slug regex → `403 scope_denied` otherwise (a malformed
   attribution header is a refused attribution, never a validation hint to the caller).
2. The project (from `ProjectCtx`) must have an `extension_installs` row for that slug that is
   `enabled`, not team-blocked, and whose `granted_scopes` contains `sol.ask`. **Otherwise →
   `403 scope_denied`** and an `extension.bridge_refused` event (`{ slug, method: "sol.ask",
reason }`). A client-asserted header without a matching install is REFUSED, never silently
   ignored and never downgraded to an unattributed turn — an extension must not be able to
   launder a turn as the user's own.
3. On acceptance the turn proceeds exactly as today: the **invoking user** is admitted against
   their own credits and frequency caps (`402 insufficient_credits`, `429`), the debit is written
   to `credit_ledger` with **`extension_id`** set (ADR-035 §2 attribution; ADR-018/019/024 —
   metering stays per-user, no pooling, no extension budget), and the existing
   `X-Solus-Credits-Charged` / `X-Solus-Credits-Remaining` headers are returned unchanged.
   `credit_ledger.attrs` additionally records `{ "extension_slug": "bom", "extension_version":
"1.2.0" }` so the ledger stays legible after an unpublish.

Without the header nothing changes for SOL. The header is only ever set by the desktop host — an
extension frame cannot set it (it never holds a session, ADR-035 §1) — but the server verifies
anyway, because the check is what makes the attribution trustworthy.

---

## 10. Team policy routes (`TeamCtx`, `owner` only)

`/api/v1/teams/{team_id}/extensions/policies[/{slug}]` — `TeamCtx` (non-member → `404`) then
`require_role(ctx, Role.OWNER)`: `admin`, `member`, `viewer` → `403 forbidden`. ADR-035 §5 —
"team owners may set project defaults and block an extension team-wide".

- **GET** — cursor-paginated list:

  ```json
  {
    "data": [
      {
        "extension": { "slug": "bom", "name": "BOM", "verified": true },
        "blocked": false,
        "default_installed": true,
        "default_settings": { "refresh": "hourly" },
        "updated_by": "019ebe5b-7aca-7770-acbb-c1897f15f46e",
        "updated_at": "2026-09-01T12:00:00.000Z"
      }
    ],
    "meta": { "has_next": false, "next_cursor": null }
  }
  ```

- **PUT `/{slug}`** — body (`extra="forbid"`, ≥ 1 key): `{ "blocked"?: bool, "default_installed"?:
bool, "default_settings"?: object }`. The slug must name an extension with an approved version
  (`404` otherwise — a policy on an unknown extension is meaningless). `default_settings` is
  validated against the **latest approved** manifest's `[settings]` exactly as §6.3 (≤ 16 KiB,
  `422` on unknown key / wrong type). `blocked: true` with `default_installed: true` → `422`.
  Upsert: `201` when the row is created, `200` when updated; returns the item shape above.
- **DELETE `/{slug}`** — deletes the policy row (reset to "no policy") → `204`; no row → `404`.

**Effect of `blocked: true`** (applied at write time, in the same transaction): every
`extension_installs` row for this extension in any project of the team is set `enabled = false`
(one `extension.disable` event per project, `reason: "team_policy"`); `PUT`/`PATCH enabled: true`
in §6 refuse with `403 extension_blocked` while the block stands; `storage` and `sol.ask`
attribution refuse with `403 scope_denied`. The desktop learns via the §6.1 installs list
(`policy.blocked`, `enabled: false`). Unblocking does NOT re-enable — a member re-enables
explicitly. `default_installed` / `default_settings` are consulted by §6.2 (settings seed) and by
the desktop when a member opens a project (the Store proposes the team defaults; installation
remains an explicit, confirmed user action — never an automatic write).

Events: `extension.policy_changed` is NOT a separate event; policy writes emit
`extension.grants_changed` with `scope: "team"` and the changed keys (§11).

---

## 11. Data events (ADR-011)

All emitted server-side into `data_events` (consent-gated), `team_id`/`project_id` from the
resolved context. Payloads carry ids and slugs, never settings VALUES, never storage values.

| `event_type`                 | emitted by                             | payload keys                                                                                                   |
| ---------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `extension.install`          | §6.2 `201`                             | `slug, version, granted_scopes, granted_network`                                                               |
| `extension.uninstall`        | §6.4                                   | `slug, version, storage_rows_deleted`                                                                          |
| `extension.enable`           | §6.3 `enabled: true`                   | `slug, version`                                                                                                |
| `extension.disable`          | §6.3 `enabled: false`; §10 block       | `slug, version, reason: "user" \| "team_policy"`                                                               |
| `extension.settings_changed` | §6.3 `settings`                        | `slug, version, changed_keys`                                                                                  |
| `extension.grants_changed`   | §6.2 `200` (grants differ); §10 writes | `slug, scope: "project" \| "team", added_scopes, removed_scopes, added_network, removed_network, changed_keys` |
| `extension.publish`          | §5.1                                   | `slug, version, bundle_size_bytes, content_hash`                                                               |
| `extension.review_completed` | review job                             | `slug, version, review_status, problem_count, duration_ms`                                                     |
| `extension.bridge_refused`   | §7 `403`, §9 `403`                     | `slug, method, reason: "not_installed" \| "disabled" \| "blocked" \| "scope_not_granted"`                      |
| `extension.unpublish`        | §5.3                                   | `slug, version`                                                                                                |
| `extension.verified_changed` | §5.4                                   | `slug, verified`                                                                                               |
| `extension.rate_limited`     | every §12 `429`                        | `route, budget?, limit?`                                                                                       |

The desktop's own refusals (unknown method, undeclared network host) reach `data_events` through
the existing `POST /api/v1/events` client path (API.md §2.13) with the same `event_type`.

---

## 12. Rate limiting

On top of the global per-token limiter (API-implementation.md §7), enforced with the same
`FixedWindowLimiter` machinery and caveats as artifacts.md §4.5 (per-process in v1; Redis when
multi-instance). Settings names are the contract; defaults are provisional pending the Phase 4
security pass.

| setting                                           | applies     | default | routes                   |
| ------------------------------------------------- | ----------- | ------- | ------------------------ |
| `extension_publishes_per_hour_per_user`           | per user    | 10      | §5.1                     |
| `extension_bundle_downloads_per_minute_per_user`  | per user    | 30      | §4.4                     |
| `extension_install_writes_per_minute_per_user`    | per user    | 60      | §6.2, §6.3, §6.4, §8 PUT |
| `extension_storage_writes_per_minute_per_install` | per install | 120     | §7 PUT/DELETE            |
| `extension_policy_writes_per_minute_per_team`     | per team    | 30      | §10 PUT/DELETE           |

Catalog reads (§4.1–§4.3, §4.5) ride the global limiter only. Exceeded → `429 rate_limited` +
`Retry-After`; every 429 is a data event for abuse detection (CLAUDE.md §7).

---

## 13. Error code catalogue (this surface)

| HTTP | `error.code`               | Where                                                                                                                                                        |
| ---- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 401  | `unauthorized`             | missing/invalid/expired JWT                                                                                                                                  |
| 402  | `insufficient_credits`     | §9 — the EXISTING SOL admission, unchanged; the invoking user is out of credits                                                                              |
| 403  | `forbidden`                | viewer / share-only on a §6–§8 write; `admin`+below on §10; non-staff on §5.4                                                                                |
| 403  | `email_not_verified`       | §5.1, §5.3, §5.4 without a verified email                                                                                                                    |
| 403  | `extension_blocked`        | §6.2 install / §6.3 `enabled: true` of a team-blocked extension                                                                                              |
| 403  | `scope_denied`             | §7 without an enabled install granting `storage.own`; §9 header without an enabled install granting `sol.ask`                                                |
| 404  | `not_found`                | non-member project/team; unknown slug; unapproved/deleted version to a non-publisher; unrecorded asset path; unknown storage key; no install / no policy row |
| 400  | `idempotency_key_required` | §5.1 without an `Idempotency-Key` header                                                                                                                     |
| 409  | `slug_taken`               | §5.1 — slug owned by another publisher                                                                                                                       |
| 409  | `version_exists`           | §5.1 — `(extension, version)` already used (incl. soft-deleted)                                                                                              |
| 409  | `idempotency_conflict`     | §5.1 — same `Idempotency-Key`, different bytes                                                                                                               |
| 409  | `grants_required`          | §6.2 — version change widens permissions beyond current grants; `details` lists the additions                                                                |
| 411  | `length_required`          | §5.1 without (or with a malformed) `Content-Length`                                                                                                          |
| 413  | `payload_too_large`        | §5.1 bundle > 25 MiB; §7 value > 64 KiB                                                                                                                      |
| 413  | `storage_quota_exceeded`   | §7 — `(project, extension)` total would exceed 256 KiB                                                                                                       |
| 422  | `validation_error`         | bad slug/version/key/path syntax; unknown form or body fields; undeclared grants; settings/layout/policy shape violations                                    |
| 422  | `bundle_invalid`           | §5.1 — manifest contract problems or zip guard violations; `details` = the dotted-path problem strings                                                       |
| 429  | `rate_limited`             | §12 budgets or the global limiter                                                                                                                            |

---

## 14. Security checklist (this surface — every implementing MR satisfies it)

- [ ] Centralized dependencies only: `CurrentUser`, `RequireVerified`, `RequireStaff` (new, in
      `deps.py`), `ProjectCtx` + `require_role(MEMBER)`, `TeamCtx` + `require_role(OWNER)`. No
      route contains its own auth logic.
- [ ] **Cross-team isolation test per project and team route** (§6, §7, §8, §10): team A's member
      cannot read or mutate team B's installs, storage, layout, or policies — `404`, never `403`,
      for a foreign project/team; and a `viewer` / share-only user gets `403` on the `member`-floor
      routes. Storage rows are keyed by the resolved `(project_id, extension_id)` — a test proves
      the same key in two projects (and two extensions) never collides.
- [ ] Catalog routes disclose no tenant: no project/team ids, no per-team install data; unapproved
      versions and their reviews/bundles/assets are `404` to non-publishers; `PATCH verified`
      never reveals staff membership.
- [ ] Bundle upload hygiene (CLAUDE.md §7 file uploads): `Content-Length` required (411), 25 MiB
      cap enforced pre-read AND while streaming (413), unknown form fields rejected (422), bounded
      central-directory read with entry-count / total-size / traversal / symlink guards, ONLY
      `extension.toml` extracted in the request path, bytes stored verbatim via `ArtifactStore`,
      **never executed, never served un-sanitized** (icon SVG reduced at review; assets served
      only from `extension_version_assets`).
- [ ] The manifest is untrusted developer input: validated with the contract (unknown fields
      reject, caps, traversal-free references); `manifest` jsonb is stored only after validation;
      `settings` and `default_settings` are validated against it on every write (≤ 16 KiB).
- [ ] Grants are a subset of declared permissions (422), widening requires re-consent (409
      `grants_required`), team blocks win over every enable path (403 `extension_blocked`).
- [ ] `X-Solus-Extension` is verified against an enabled install granting `sol.ask` — refused
      (403 `scope_denied`) rather than ignored; attribution is recorded on `credit_ledger`, the
      invoking user is still the metered party (ADR-018/019/024); no extension budget, no pooling.
- [ ] Storage values are opaque: never parsed, never in a prompt, never cross-project; 64 KiB /
      256 KiB caps enforced (413).
- [ ] No storage-internal locator in any response (`bundle_url`, `assets.*` are API routes);
      `ArtifactStore` keys never leave the server.
- [ ] Rate limits on every write group (§12) with `Retry-After`; 429s emitted as data events.
- [ ] Every write emits its §11 event; payloads carry no settings or storage VALUES.
- [ ] Review job runs under queue-level concurrency limits; rejects disallowed asset types;
      never executes bundle content.

---

## 15. Open questions

None — every decision above was fixed at the SOLUSDEV-235 Phase 1 design review (2026-09-03).
Two conventions are extended rather than changed and are called out in API.md §1.4/§1.5:
`Idempotency-Key` becomes **required** on `POST /extensions/publish` (§1.4 lists it as required
only on billing and deployment), and the catalog is a **tenant-free** read surface under
`/extensions` rather than nested under a team or project (§1.3), on the ADR-033 precedent.

---

**Cross-references:** DECISIONS.md ADR-035, ADR-034 (amendment 2026-09-03), ADR-018/019/024/025,
ADR-033 · `docs/contracts/extension-manifest.md` · `docs/schemas/extensions.md` (tables) ·
`docs/wireflows/store.md` · [artifacts.md](artifacts.md) §4.4/§4.5/§4.6 (upload hygiene, limiter,
`ArtifactStore`) · [API.md](API.md) §1.4/§1.5/§2.17/§5 · [API-implementation.md](API-implementation.md)
§7 (limiter), §11 (the live SOL turn route §9 attributes), §16 (index entry) · CLAUDE.md §7.
