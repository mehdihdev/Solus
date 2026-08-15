# Completion Report — SOLUS-CAD-01 / SOLUSDEV-96: Onshape connector

**Status:** built, verified, on `SOLUSDEV-60/cad-01-onshape`. Ends at the per-ticket human gate.

## Deviation from the ticket's acceptance text — stated up front

SOLUSDEV-96 says _"Fork an existing open-source Onshape MCP server … and OWN it in our repo."_
**This ticket does not fork anything**, on your approved decision D-A. Two independent reasons:

1. **No candidate clears the MCP-03 licence bar.** Every Python Onshape MCP server descends from
   `hedless/onshape-mcp`, which has **no LICENSE file** — only a bare README line "MIT License"
   with no grant text and no copyright holder. `jarvis` admits in its own NOTICE that its import
   commit _"squashes the upstream history"_, so the provenance cannot be audited. ADR-031 allows
   MIT/Apache-2.0 only, with **no sign-off path around it**. The one clean-licence candidate
   (`altendky`, MIT+Apache-2.0, OAuth+PKCE) has 10 generic tools and no CAD semantics.
2. **The contract already specifies this shape.** `metadata-extraction.md` §2: _"Thin API — auth +
   detect change + fetch/generate STEP/STL export → shared parser. Onshape is **NOT** a deep
   live-API integration."_ Onshape's REST API natively provides STEP translation, microversions
   and OAuth, so the fork would have added a supply-chain liability and bought nothing.

Everything else in the acceptance list is met: OAuth via `SecretStore`, read of assemblies/parts
into the graph, `detect_changes` on the document microversion, and no bridge dependency.

## What was built

### `connectors/onshape.py` — the thin-API connector

- **OAuth** against `oauth.onshape.com`: `authorize_url` (scopes `OAuth2Read OAuth2Write`),
  `exchange_code`, and `refresh_credentials`. `supports_token_connect = False` so an API key pair
  — which authenticates the **developer**, not the customer — cannot bypass the flow.
- **`detect_changes`** on the document **microversion**, failing safe (unreachable API ⇒ changed).
- **Acquisition**: `POST …/translations` (STEP) → **bounded** poll of `/api/v8/translations/{id}`
  (30 attempts, then `export_timeout`) → download external data → size-bound → `parse_step`.
- **Enrichment**: `GET …/parts/…` for part numbers and materials, joined to STEP products **by
  name** (the only key both sides share) and written to `modality_hints["part_number"]`. A
  metadata failure **degrades** — the team still gets their assembly tree, with the loss recorded
  as a `SyncError`.
- Every `document_id`/`workspace_id`/`element_id` is validated against `^[A-Za-z0-9]{1,40}$`
  **before** URL interpolation; upstream error text is never echoed into a `ConnectorError`.

### The OAuth refresh seam (contract Edit 6)

The pre-existing OAuth path stored **only** the access token — `refresh_token` was dropped at
persist time. GitHub/GitLab tokens are long-lived so nothing surfaced it; **Onshape tokens expire
in 60 minutes**, so an Onshape source would have died within the hour.

- `OAuthConnector.refresh_credentials` — non-abstract, **default refuses**, so a provider that has
  not opted in can never appear to refresh silently.
- `runtime._sync_with_refresh` — on `invalid_credentials` **only**, for an `OAuthConnector`
  **only**, with a stored refresh token **only**: refresh **once**, persist, retry **once**. A
  permanently-broken credential cannot spin against a provider's token endpoint.
- **Rotation honoured**: Onshape issues a new refresh token on every use and invalidates the old.
  Both tokens are persisted; a test pins this, because dropping the rotated token breaks the chain
  at the _next_ refresh, not this one.
- `runtime.refresh_secret_ref()` is the ONE definition of `{secret_ref}/refresh`, shared by the
  write and both reads (the rule MCP-05's `license_secret_ref` follows). Sources connected before
  this ticket have no such secret; its absence is not an error.

### `settings.github_oauth_redirect_app` → `oauth_redirect_app`

Raised in Phase 0 as a flag. It was always provider-agnostic (GitLab already used it) and the
GitHub name became actively misleading with a third provider. Renamed across config, the single
consumer, `env.mega.example`, `scripts/env-sync.test.mjs`, and the GitHub setup doc.
**Env var change: `SOLUS_GITHUB_OAUTH_REDIRECT_APP` → `SOLUS_OAUTH_REDIRECT_APP`.**

## Verification

- `uv run ruff check .` — clean · `uv run mypy packages/api/src` — **clean, strict, 114 files**
- `uv run pytest -q` — **1348 passed, 4 skipped** (was 1306 after CAD-00)
- `pnpm --filter @solus/desktop run typecheck` — clean · **630 vitest tests pass** (98 files)
- `node scripts/env-sync.test.mjs` — 0 failures (the rename is consistent end to end)
- Single alembic head unchanged (`a7c5d2e91f04`); no migration needed
- 47 new/updated tests: 33 `test_onshape_connector` · 9 `test_oauth_refresh` · `test_registry`
  roster + Onshape catalog assertions · desktop catalog test

Notable coverage: the OAuth-only gate; rotated-refresh persistence; refresh attempted **at most
once**; non-OAuth connectors never retried; bounded translation polling; `export_too_large` before
parsing; `invalid_credentials` on 401 so the runtime can refresh; config ids rejected before URL
interpolation (`../etc`, `d1/w1`, `d 1`, `d1?x=1`); metadata failure degrading rather than failing;
and the access token never appearing in an error message.

## Delegated-judgment decisions

1. **`OnshapeConnector` extends `OAuthConnector`, not `CadExportConnector`.** It shares the
   _parser_ (`parse_step` + `build_mechanical_graph`) — which is what §3 actually mandates — while
   the `CadExportConnector` scaffold serves the committed-export tools (CAD-02/03/04). Avoids an
   MRO conflict between `auth_kind = NONE` and OAuth.
2. **Part numbers joined by NAME.** STEP has no MPN slot and Onshape's parts API has no STEP
   product id; name is the only shared key. Marked `ponytail:` with the upgrade path.
3. **Metadata failure is non-fatal.** Structure is the deliverable; part numbers are enrichment.
4. **Upstream error bodies are never surfaced** — status code plus our own label only.
5. **Desktop tile stays hidden.** `integrationCatalog.modeFor` returns `null` for Onshape because
   the renderer has no Onshape OAuth flow yet. Hiding an undrivable tile is the existing
   de-simulation rule (SOLUSDEV-152); faking one would be worse. The test that asserted Onshape's
   absence was renamed — its stated reason ("the backend does not register it") is now false — and
   its fixture now includes Onshape so the assertion tests the real rule.

## Open items for humans

1. **Live verification owed (the honest limit of this ticket).** The HTTP paths and payload shapes
   were written from Onshape's public API docs, **not captured from a live tenant**. One
   confirmation run against a real document is owed before this is production-ready. Fixtures in
   `tests/fixtures/onshape_sample.py` name the endpoint each payload stands for so that pass is
   mechanical. **Accurate statement of status: connector, seam and graph mapping complete and
   proven against documented payload shapes; live E2E unverified.**
2. **Renderer connect flow for Onshape** is not built — backend-only ticket.
3. **Onshape account constraints** worth pricing before launch: the free personal plan makes every
   document public, forbids commercial use, and its API terms bar automated extraction from public
   documents — tenants need paid seats. A _private_ OAuth app's calls also still count against the
   rate cap; the exemption belongs to the _published_ app.
4. **`SOLUS_GITHUB_OAUTH_REDIRECT_APP` must be renamed in any deployed `.env`.**
5. G0 (OCCT licence, from CAD-00) still open — CAD-01's sync path parses STEP, so it inherits that
   gate.

## Doc changes

- `docs/contracts/connector-interface.md` — **Edit 6** added (OAuth token refresh: the new hook,
  the runtime/connector division of responsibility, rotation, storage ref, error codes).
- `docs/integrations/onshape-setup.md` — new: OAuth app registration, scopes, config, what a sync
  does, token expiry, the part-number/fingerprint caveat, licensing constraints, and what is not
  yet built.
- `docs/integrations/github-setup.md` — env var rename only.
