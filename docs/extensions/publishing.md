# Publishing

How a bundle becomes an installable version: packaging, the publish route, the automated review,
versions and updates, unpublishing, the verified badge, and your obligations. Routes are
documented in `docs/api/extensions.md`; the validator is
`packages/api/src/solus_api/extensions/{bundle,checks,svg,manifest}.py`. Companion pages:
[manifest](manifest.md), [bridge API](bridge-api.md), [getting started](getting-started.md).

Publishing is a registry action from your account, not a desktop feature: you need a signed-in
session with a **verified email**, and an API token. The desktop's developer mode never publishes.

## 1. Package the zip

Zip the **contents** of the extension folder so `extension.toml` sits at the archive root:

```bash
cd hello-widget
zip -r ../hello-widget-0.1.0.zip . -x '.*' -x '__MACOSX/*' -x '*/.*'
```

The `-x` patterns matter: `.DS_Store`, `.git/`, editor swap files and macOS resource forks are not
allowed file types and fail review.

What the archive must satisfy (every violation is listed by path):

| Rule                                                                                                            | Problem text                                                                                                                                                                                                                                          |
| --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Starts with the zip signature and is readable                                                                   | `not a zip archive` · `not a readable zip archive: …`                                                                                                                                                                                                 |
| Archive ≤ 25 MiB; total uncompressed ≤ 25 MiB; every entry ≤ 25 MiB                                             | `bundle size N exceeds …` · `total uncompressed size N exceeds …`                                                                                                                                                                                     |
| ≤ 2000 entries                                                                                                  | `bundle has N entries; the maximum is 2000`                                                                                                                                                                                                           |
| Compression ratio ≤ 100:1 for entries over 16 KiB (zip-bomb guard)                                              | `<path>: compression ratio exceeds 100:1`                                                                                                                                                                                                             |
| Allowed suffixes only: `.html .js .css .json .svg .png .webp .woff2 .md .toml`                                  | `<path>: not an allowed file type (…)`                                                                                                                                                                                                                |
| Relative paths, no leading `/`, no backslash, no `.`/`..` segments, segment chars `[A-Za-z0-9_.-]`, ≤ 200 chars | `<path>: absolute paths are not allowed` · `…: backslashes are not allowed in paths` · `…: path traversal or empty segment` · `…: path is not a safe bundle path (characters or length)`                                                              |
| No symlinks, no encrypted entries                                                                               | `<path>: symlink entries are not allowed` · `…: encrypted entries are not allowed`                                                                                                                                                                    |
| No duplicate names (case-insensitive)                                                                           | `<path>: duplicate entry (case-insensitive)`                                                                                                                                                                                                          |
| `extension.toml` at the root, UTF-8, ≤ 64 KiB, valid TOML                                                       | `extension.toml: missing from the bundle root` · `extension.toml: must be at the bundle root, found inside 'hello-widget/' — zip the folder's contents, not the folder` · `extension.toml: not valid UTF-8 text` · `extension.toml: invalid TOML — …` |

Directory entries (`docs/`) are fine. Files the manifest does not reference are allowed as long as
they pass the rules above and the content checks.

## 2. `POST /api/v1/extensions/publish`

`multipart/form-data` with exactly one part, `bundle` (the zip, `application/zip`). Requirements:

- `Authorization: Bearer <token>` for an account with a verified email (`401 unauthorized`,
  `403 email_not_verified`).
- `Idempotency-Key` header, **required** (≤ 255 chars) — `400 idempotency_key_required` without it.
  Replaying the same key with the same bytes returns the original `202`; the same key with different
  bytes is `409 idempotency_conflict`.
- `Content-Length` (`411 length_required` when absent or malformed); over 25 MiB → `413 payload_too_large`
  before the body is read and again while streaming.
- No other form fields (`422 validation_error`).

```bash
curl -sS -X POST "https://api.solus.example/api/v1/extensions/publish" \
  -H "Authorization: Bearer $SOLUS_TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -F "bundle=@hello-widget-0.1.0.zip;type=application/zip"
```

The request path checks the zip **structure** and your `extension.toml` only (entry count and
declared sizes, names, suffixes, symlinks, the manifest contract, and that every referenced file
is present by name). Any problem is `422 bundle_invalid` with every problem in `error.details[]`
— nothing is stored:

```json
{
  "error": {
    "code": "bundle_invalid",
    "message": "Bundle failed validation",
    "details": [
      "store.privacy_policy: required when permissions.scopes or permissions.network is non-empty",
      "page.html:14: href/src must be bundle-relative (no http:, https:, //, javascript:, data:text/html)",
      "vendor/chart.wasm: not an allowed file type (.html, .js, .css, .json, .svg, .png, .webp, .woff2, .md, .toml)"
    ]
  }
}
```

Then the slug is claimed: a new `extension.id` becomes yours; an id owned by another publisher is
`409 slug_taken`; a `(id, version)` pair that was ever published — including unpublished ones — is
`409 version_exists`. On your first publish a publisher record is created with `display_name`
seeded from the manifest's `extension.publisher` (later publishes do not rewrite it).

### The `202` response

```json
{
  "data": {
    "version": {
      "slug": "hello-widget",
      "version": "0.1.0",
      "review_status": "pending",
      "content_hash": "3ab0c7…64 hex…",
      "bundle_size_bytes": 18211,
      "bundle_url": "/api/v1/extensions/hello-widget/versions/0.1.0/bundle",
      "review_url": "/api/v1/extensions/hello-widget/versions/0.1.0/review",
      "created_at": "2026-09-03T10:00:00.000Z"
    },
    "review": { "status": "pending", "problems": [] }
  }
}
```

`content_hash` is the sha256 of the bytes you sent; the desktop verifies every download against it.

## 3. Poll the review

`GET /api/v1/extensions/{slug}/versions/{version}/review` — publisher only; anyone else gets
`404` (a review of a version you did not publish does not exist for you).

```json
{
  "data": {
    "slug": "hello-widget",
    "version": "0.1.0",
    "review_status": "approved",
    "review_problems": [],
    "checked_at": null,
    "published_at": "2026-09-03T10:00:04.000Z"
  }
}
```

`review_status` walks `pending → checking → approved | rejected`. `review_problems` is empty
except on `rejected`. Poll every few seconds; the job is quick. A version stuck in `pending` means
the review worker is not running — nothing on your side.

`GET /api/v1/extensions/{slug}/versions` shows you every version including `pending`, `checking`
and `rejected` ones (with their problems); other users see approved versions only. You may also
fetch your own unapproved bundle bytes from `bundle_url` to reproduce a finding locally.

## 4. What the review checks

The review job is where members are actually inflated (under a cumulative 25 MiB budget, 512 KiB per
text file, and a compression-ratio guard on every entry) and where content rules apply. A bundle
that passed the upload can still end `rejected` here.

The background job re-runs the same validator the request ran (so a rejection here is rare and
usually means the bundle changed shape between checks, or an internal error — `review: internal
error`), then:

1. Reduces the page icon to the monochrome subset and stores the **reduced** SVG.
2. Extracts the store-facing files — `store.overview`, `store.privacy_policy`, each
   `store.sections[].body`, each screenshot, the icon — as assets served at
   `/api/v1/extensions/{slug}/versions/{version}/assets/{path}`. Nothing else in the bundle is ever
   served by the API; the desktop serves your entry files from its verified local cache.
3. Sets `approved` with `published_at`, and makes the version the extension's latest if it is the
   highest approved semver.

The static content checks, and their problem text `"<path>:<line>: <message>"`:

| Files              | Rejected                                                                                                                                                                                                                                                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.html`            | `<script src=` remote · `<link href=` remote · `<iframe>` · `<base>` · `<meta http-equiv=content-security-policy>` · `<form action=` remote · `<object>` · `<embed>` · any `href`/`src` starting with `http:`, `https:`, `//`, `javascript:`, `data:text/html` · inline `<script>` bodies are checked with the JS rules |
| `.js` (and inline) | `importScripts(` · `new Worker(` · `navigator.serviceWorker` · `import(` of a remote module · `fetch(` · `XMLHttpRequest` · `WebSocket(` · `EventSource(` · `sendBeacon(`                                                                                                                                               |
| `.md`              | `<script` · `<iframe` · `javascript:` · `on*=` attributes                                                                                                                                                                                                                                                               |
| all text files     | must be valid UTF-8                                                                                                                                                                                                                                                                                                     |

These are conservative textual matches on the raw file (comments included, case-insensitive).
`fetch(` in a comment is a rejection; write "the network proxy" instead. `.css` and `.json` are not
scanned, but the CSP still blocks remote `@import`/`url()` at runtime.

Also checked: every declared `entry` exists (`<entry>:1: declared entry is not in the bundle`),
every referenced file exists (`views.page.icon: references icon.svg, which is not in the bundle`)
and is within its cap (`shots/big.png: exceeds 1048576 bytes`), PNG/WebP signatures match their
suffix (`shots/table.png: not a PNG image (signature mismatch)`), and the icon passes the
[icon rules](getting-started.md#icon-rules) (`icon.svg: element <style> is not allowed`,
`icon.svg: attribute id on <path> is not allowed`, `icon.svg: fill on <path> must be none,
currentColor, a hex colour or a colour name`, `icon.svg: DOCTYPE declarations are not allowed`).

Review is automated and static. Nothing in the bundle is executed, and approval is not an
endorsement — see the verified badge below.

## 5. Versions

- `extension.version` is semver `MAJOR.MINOR.PATCH[-prerelease]`; `+build` metadata is rejected.
- Every version string is single-use per extension — including rejected and unpublished ones. A
  rejected `0.1.0` means your fix ships as `0.1.1`.
- The catalog shows the highest approved semver; a pre-release (`1.0.0-rc.1`) sorts below the
  release of the same core, so publishing `1.0.0-rc.2` after `1.0.0` does not change what users see
  as latest.
- **Installs pin a version.** Each project keeps the exact version its member installed, with its
  own grants and settings, until someone updates it.
- Bump the version for every publish; the manifest inside the zip and the registry must agree, and
  the desktop refuses a bundle whose manifest id/version differ from the registry's
  (`manifest_mismatch`).

## 6. Updating

When a newer approved version exists, the Store shows **Update available** on the card and
`v<pinned> → <latest>` on the detail header. Updates are never automatic.

- **Same or narrower permissions**: one click swaps the pinned version; the desktop downloads and
  verifies the new bundle beside the old one, remounts frames on the new version, then removes the
  old directory. Grants are intersected with the new declaration.
- **Widened permissions** (a new scope or a new network origin): the Store shows the permissions
  step again, listing only what the new version _additionally_ asks for, with your privacy policy.
  The user must **Grant and update**; cancelling keeps the pinned version. On the API this is
  `409 grants_required` until the client re-sends widened grants.
- Settings carry over: values for keys the new manifest still declares are kept (type-checked),
  unknown keys are dropped, new keys take their defaults.
- `storage.own` data is untouched by an update.

Design for this: a new version must cope with settings and storage written by the previous one.

## 7. Unpublishing

`DELETE /api/v1/extensions/{slug}/versions/{version}` — publisher only (`404` for everyone else),
verified email required, `204 No Content`.

- The version disappears from the catalog, the versions list, the bundle and asset routes.
- The extension's latest is recomputed from the remaining approved versions; when none remain the
  extension leaves the catalog entirely (your listing remains visible to you).
- **Existing installs keep running** from their pinned, cached copy; the desktop shows "no longer
  in the catalog" and offers no update. Unpublishing is not a recall.
- The version string is burned and cannot be published again.

There is no route to delete an extension or release a slug.

## 7b. First-party tables (`schema_version = 2`)

If your manifest declares `[backend]`, `[graph]` or `[tools]` the request path additionally
requires that you publish from a **Solus staff** account and that an in-repo capability package
with your `extension.id` provides everything you declared. Otherwise nothing is stored and the
`422 bundle_invalid` details name the reason:

| problem                                                            | meaning                                                |
| ------------------------------------------------------------------ | ------------------------------------------------------ |
| `backend: first-party only (publisher is not Solus staff)`         | community accounts cannot use these tables — drop them |
| `backend.capability: no in-repo capability named <id>`             | staff, but Solus ships no package for that id          |
| `backend.routes: capability <id> has no router`                    | `routes = true` but the package exports no router      |
| `graph.kinds.N` / `tools.names.N: not provided by capability <id>` | the package does not define that kind / tool           |

Community bundles do not need these tables; the bridge is the whole API. A `schema_version = 2`
manifest WITHOUT them publishes exactly like a v1 one.

## 8. The verified badge

`verified` is a boolean on the extension row set by **Solus staff** through a staff-only route
(`PATCH /api/v1/extensions/{slug} { "verified": true }`). It is a manual decision, independent of
review, and is never derived from the publisher display name — naming yourself "Solus" in
`extension.publisher` produces no badge and is likely to get the listing removed (and, on a first
publish, is refused outright — `409 publisher_name_reserved` — unless the account is Solus staff,
which is how first-party bundles are published under the Solus name). There is no
application form in this build; staff reach out. Everything else on the listing (`name`, `summary`,
`publisher`) comes from the manifest and changes only through a new version.

## 9. Your obligations

- **Privacy policy** — mandatory once you declare any scope or network origin. It is shown before
  the user grants anything. Describe what you read from the project, what you keep in
  `storage.own`, what you send to which origins and why, and whether you call SOL (metered to the
  user's own credits). Keep it current: a new version that widens permissions is shown to users
  alongside it.
- **Data leaves through `net.fetch` only**, to origins you declared. Do not proxy project data
  through an undeclared origin via redirects — they are refused, and doing so deliberately is
  grounds for a team-wide block.
- **Render text as text.** Anything you receive from the graph, from `sol.ask` or from a network
  response is untrusted; never `innerHTML` it.
- **Respect the user's meter.** `sol.ask` spends the invoking user's credits with your extension
  named on the ledger; do not call it in loops or on every focus change.
- Team owners can block your extension across their team at any time; project members can
  disable it. Handle `blocked` quietly.

## 10. Rate limits

On top of the global per-token limiter. Exceeding one returns `429 rate_limited` with
`Retry-After`, and every 429 is logged as a data event for abuse detection.

| Budget                                 | Default | Applies to                                                                  |
| -------------------------------------- | ------- | --------------------------------------------------------------------------- |
| Publishes per hour, per user           | 10      | `POST /extensions/publish` (`Retry-After: 3600`)                            |
| Bundle downloads per minute, per user  | 30      | `GET …/versions/{version}/bundle`                                           |
| Install writes per minute, per user    | 60      | install / update / settings / uninstall / widget layout                     |
| Storage writes per minute, per install | 120     | `storage.set` / `storage.delete` (surfaces as `rate_limited` on the bridge) |
| Policy writes per minute, per team     | 30      | team owner policy routes                                                    |

## Error codes on the publishing routes

| HTTP | `error.code`               | When                                                                                                               |
| ---- | -------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 400  | `idempotency_key_required` | Publish without an `Idempotency-Key` header                                                                        |
| 401  | `unauthorized`             | Missing/invalid/expired token                                                                                      |
| 403  | `email_not_verified`       | Publish or unpublish from an account without a verified email                                                      |
| 403  | `forbidden`                | Non-staff calling the verified-badge route                                                                         |
| 404  | `not_found`                | Unknown slug/version; someone else's unapproved version or review; a deleted version                               |
| 409  | `slug_taken`               | `extension.id` belongs to another publisher                                                                        |
| 409  | `publisher_name_reserved`  | Your first publish used a display name reserved for Solus (`Solus`, `Solus Forge`, lookalikes); pick your own name |
| 409  | `version_exists`           | This `(id, version)` was already published (even if rejected or unpublished)                                       |
| 409  | `idempotency_conflict`     | Same `Idempotency-Key`, different bytes                                                                            |
| 411  | `length_required`          | No (or malformed) `Content-Length`                                                                                 |
| 413  | `payload_too_large`        | Bundle over 25 MiB                                                                                                 |
| 422  | `validation_error`         | Unknown form field, missing `bundle` part, malformed slug/version in the path, over-long idempotency key           |
| 422  | `bundle_invalid`           | Any validator problem; `details[]` lists them all                                                                  |
| 429  | `rate_limited`             | Publish budget exhausted                                                                                           |
