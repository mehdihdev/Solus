# Cowork QA — KiCad MCP Fork & Live Export Acquisition (SOLUSDEV-100 phase 2)

Self-sufficient end-to-end test plan for SOLUSDEV-100 phase 2: the vendored KiCad MCP
server fork (`integrations/mcp/kicad/`), the live netlist-export acquisition path
(committed export → live MCP export via the bridge companion), the project artifact
upload/fetch surface (`docs/api/artifacts.md`), and the schematic write tool's security
posture. Phase 1 (the committed-netlist connector and its UI connect flow) is covered by
`COWORK_QA_kicad-connector.md` — run that first; this file assumes those flows pass.

Legend: ✅ pass · ❌ fail · ➖ blocked/NA

---

## Required setup state

- **Postgres + API running** (`make db-up`, then
  `cd packages/api && uv run uvicorn --factory solus_api.main:create_app --port 8000`)
  with `SOLUS_SUPABASE_JWT_SECRET` set and
  `SOLUS_BRIDGE_ALLOWLIST_ROOT=<repo>/integrations/mcp` (exposes the real kicad fork's
  allowlist to the bridge ingress gate).
- **A user with a team + project** and a valid access token (`<TOKEN>`, `<PROJECT_ID>`),
  plus a second user in a DIFFERENT team with their own project (`<TOKEN_B>`,
  `<PROJECT_B>`) for the isolation flows.
- **Fork venv materialized** (the companion install step, done manually until BRG ships
  it):
  ```
  cd integrations/mcp/kicad
  python3.12 -m venv .venv
  .venv/bin/pip install --require-hashes -r requirements.lock.txt
  ```
  Without this, `bin/launch` cannot exec and every fork test skips with a materialization
  hint — that skip message is itself an expected behavior, not a failure.
- **Companion running** (separate terminal):
  ```
  SOLUS_COMPANION_URL="ws://127.0.0.1:8000/api/v1/projects/<PROJECT_ID>/bridge" \
  SOLUS_COMPANION_TOKEN="<TOKEN>" \
  SOLUS_COMPANION_INTEGRATIONS_ROOT="<repo>/integrations/mcp" \
  uv run python -m solus_companion
  ```
- **Sample project**: the committed fixture
  `integrations/mcp/kicad/tests/fixtures/solus_sample/` (`solus_sample.kicad_pro` +
  `.kicad_sch` + `solus_sample.net.xml` ~13 KiB + `solus_sample_large.net.xml` ~737 KiB).
- **KiCad itself is OPTIONAL.** Without `kicad-cli` on the pinned lookup
  (`KICAD_CLI_PATH` or `/usr/bin:/bin`), the fork's `export_netlist` degrades to a
  KiCad-free schematic file parse and returns `degraded: true` with the stable reason
  "kicad-cli unavailable (headless posture)…". Headless is a first-class supported state —
  test it, don't work around it.

> **DEFECT FIXED before handoff (commit `23503ef`):** the cloud acquirer originally
> rejected the REAL fork tool's plan-locked result envelope and silently fell back to
> the committed export. `_ExportToolValue` now accepts the full envelope (advisory
> metadata keys never authority; a NON-NULL `artifact_path` is a hard decline), with
> regression tests feeding the acquirer the fork's literal envelope. Flows 2.3–2.5
> below test the real inline/artifact expected results; a fallback with reason
> "tool result value has an unexpected shape" is now a ❌ regression, not ➖ blocked.

---

## Flow 1 — Fork discovery, launch, and the allowlist gate

1. [ ] Start API, then companion. Companion log shows the kicad server discovered
       (from `integrations/mcp/kicad/allowlist.yaml`), launched via `bin/launch`, and the
       bridge `hello` accepted.
2. [ ] `GET /api/v1/projects/<PROJECT_ID>/sol/tools` (Bearer `<TOKEN>`) lists EXACTLY the
       roster: `kicad.list_projects`, `kicad.get_project_structure`,
       `kicad.extract_project_netlist`, `kicad.analyze_schematic_connections`,
       `kicad.analyze_bom`, `kicad.export_netlist`, `kicad.set_symbol_property`.
3. [ ] NO other upstream tool appears — spot-check for `kicad.run_drc_check`,
       `kicad.open_project`, `kicad.generate_pcb_thumbnail`: absent (the overlay never
       registers the 11 non-allowlisted upstream tools; the cloud gate would drop them
       anyway).
4. [ ] `GET /api/v1/projects/<PROJECT_ID>/bridge` → `connected: true`, kicad server
       `ready`.
5. [ ] Edge: stop the companion, edit a COPY of the fork with an extra tool advertised
       (or use the `mock.badschema` fixture posture from `COWORK_QA_local-bridge.md`):
       a companion-advertised descriptor not in `allowlist.yaml` never appears in
       `sol/tools` and the companion log/API log shows it gated.

## Flow 2 — Live export acquisition (sync via the bridge)

Setup: create a kicad source on the project whose config carries BOTH keys —
`{"export": "<contents of solus_sample.net.xml>", "project_path":
"<abs repo path>/integrations/mcp/kicad/tests/fixtures/solus_sample/solus_sample.kicad_pro"}`
— then `POST /api/v1/projects/<PROJECT_ID>/sources/<id>/sync`.

1. [ ] With the companion CONNECTED, the sync completes and entities land: 9 components
       (U1=STM32F030F4P6, U2=MPU-6050, R1–R3, C1–C4), `net:` entities, and
       `connected_to` edges (same graph shape as the committed-path flow in
       `COWORK_QA_kicad-connector.md` Flow 1 — invariant 2: identity is content-derived,
       so the two paths must land IDENTICAL `source_key`s/external_refs).
2. [ ] API log for the sync names the acquisition path taken; NO stack trace either way.
3. [ ] **Inline path (small export, post-fix target):** the fork exports the sample
       netlist (< 512 KiB) → the tool result carries it inline (`content`); no artifact
       row is created (`GET .../artifacts/...` has nothing new); sync entities as in 2.1.
       
4. [ ] **Headless degradation is invisible to the graph:** on a machine without
       kicad-cli the live export is synthesized from the schematic parse — the sync still
       succeeds; the companion-side fork result carries `degraded: true` + stable reason
       (visible in companion logs), never an error.
5. [ ] **Artifact path (large export, post-fix target):** with a project whose netlist
       export exceeds 512 KiB (no committed schematic this large exists — build one from
       `gen_large_fixture.py`'s cluster pattern, or verify this leg via
       `uv run pytest packages/companion packages/api/tests/test_mcp_acquire_artifact.py -q`,
       which covers it with real upload/consume rounds): companion log shows the
       workspace file uploaded (`201`), the tool result carries an `artifact_ref` (never
       a local path), and the sync consumes it exactly once.

## Flow 3 — Artifact upload/fetch surface (drives `docs/api/artifacts.md` directly)

Use curl with Bearer `<TOKEN>`; `<BASE>` = `http://127.0.0.1:8000/api/v1/projects/<PROJECT_ID>`.

1. [ ] `POST <BASE>/artifacts` multipart with
       `file=@integrations/mcp/kicad/tests/fixtures/solus_sample/solus_sample_large.net.xml`,
       `media_type=application/xml` → `201` and an `ArtifactRef` whose `uri` is the API
       content route (relative), `storage` = `local` (dev).
2. [ ] `GET <BASE>/artifacts/<id>` → `200` metadata; `scope: "project"`.
3. [ ] `GET <BASE>/artifacts/<id>/content` → `200`, byte-identical to the uploaded file.
4. [ ] **One-shot:** repeat the content GET → `404` (consumed; the row is soft-deleted).
       Metadata GET now also → `404`.
5. [ ] Upload with a >8 MiB file → `413 payload_too_large` (and a lying small
       `Content-Length` on a big body must not slip through).
6. [ ] Upload with a malformed `media_type` (e.g. `not-a-mime`) or an unknown form field
       → `422 validation_error`.
7. [ ] Hammer uploads past the per-user request budget → `429 rate_limited` with
       `Retry-After`.

## Flow 4 — Bridge-offline degradation (invariant 3)

1. [ ] Kill the companion (Ctrl-C). `GET .../bridge` flips `connected: false` (within
       ~60 s).
2. [ ] Re-run the Flow 2 sync: it STILL SUCCEEDS from the committed `export` config, and
       the API log records the live-path degradation ("bridge offline") — a warning, not
       an error.
3. [ ] Entity set after the fallback sync is identical to the live-path sync (re-sync is
       idempotent: no duplicates, stable counts).
4. [ ] Remove `project_path` from a source's config: sync never attempts the live path
       (declines "no project_path configured") and uses the committed export directly.
5. [ ] Source with NEITHER `export` nor a reachable live path → sync fails with the
       structured `export_unavailable` connector error, not a crash.

## Flow 5 — The write tool is REFUSED by SOL (expected, not a bug)

`kicad.set_symbol_property` mutates a customer design file; it is allowlisted
`requires_confirmation: true`, and the user-confirmation flow is NOT built yet, so the
central gate (`agent/runtime.py::confirmation_refusal`) refuses it outright.

1. [ ] Ask SOL (chat) to change a symbol property (e.g. "set R1's Value to 10k in my
       KiCad schematic"): if SOL attempts the tool, the result is a structured
       `unauthorized` tool error — "destructive action requiring explicit user
       confirmation; the confirmation flow is not yet available". **Expected refusal.**
2. [ ] No dispatch reaches the companion for that call (companion log shows no
       `tool_call` for `kicad.set_symbol_property`).
3. [ ] `solus_sample.kicad_sch` is byte-unchanged afterwards (checksum before/after).
4. [ ] The refusal never crashes the SOL stream — the conversation continues.

## Flow 6 — Cross-team isolation spot-checks

1. [ ] **Artifact fetch:** upload an artifact as user A (Flow 3.1). As user B (other
       team), `GET /api/v1/projects/<PROJECT_ID>/artifacts/<id>` and `/content` → `404`
       (never 403 — no existence oracle). Same for B addressing the artifact through
       B's OWN project id.
2. [ ] **Upload role:** a share-only/viewer user on project A attempting the upload →
       `403 forbidden`.
3. [ ] **Bridge dispatch:** with A's companion connected, user B's
       `GET /api/v1/projects/<PROJECT_B>/bridge` → `connected: false`; B's SOL cannot see
       or invoke A's kicad tools (`sol/tools` on B's project does not list them).
4. [ ] A companion dialing project A's bridge URL with B's (non-member) token is
       rejected at connect (4404 posture, per `COWORK_QA_local-bridge.md` Flow 4).

## Flow 7 — Security spot-checks

1. [ ] **No tokens in logs:** grep API and companion logs for the bearer token string →
       zero hits (uploads log call ids/byte counts only).
2. [ ] **No secret values anywhere:** grep the fork tree and logs for any credential
       value; the fork's env allowlist (`bin/launch` env -i block) passes only the
       declared 11 names; companion decline reasons are stable strings, never local
       paths or free-text companion errors echoed cloud-side.
3. [ ] **`upstream/` never written at runtime:** after running Flows 1–5,
       `git status integrations/mcp/kicad/upstream integrations/mcp/kicad/vendor` is
       clean; no `kicad-mcp.log` and no `__pycache__` anywhere under `upstream/` or
       `vendor/` (the entry sets `dont_write_bytecode`; upstream's in-tree logging is
       shimmed out). Export artifacts land ONLY under `<workspace>/solus-artifacts/`.
4. [ ] **Path confinement:** a tool result pointing `artifact_path` outside the
       workspace (covered mechanically by
       `packages/companion/tests/test_companion_artifacts.py`) is refused with
       `artifact_path_escapes_workspace` and makes ZERO HTTP calls — verify the test
       passes: `uv run pytest packages/companion -q`.
5. [ ] Full suite green as the closing check:
       `uv run pytest integrations/mcp packages/api packages/companion -q`.

## Cross-feature interactions

- [ ] Phase-1 committed-path UI connect flow (`COWORK_QA_kicad-connector.md` Flows 8–9)
      still passes with the companion RUNNING — live acquisition must never break the
      file-pick path.
- [ ] `COWORK_QA_local-bridge.md` Flows 1–4 still pass with
      `SOLUS_BRIDGE_ALLOWLIST_ROOT` pointed at the real `integrations/mcp` tree.
- [ ] Altium committed-path sync (`COWORK_QA_altium-connector.md`) unaffected (it shares
      the EDA acquisition seam but has no vendored fork yet — its live path declines
      cleanly).

## Known limitations to confirm are documented (not bugs)

- [x] The acquirer↔fork envelope mismatch — FIXED in `23503ef`; live path serves real results
      until the follow-up lands.
- [ ] `set_symbol_property` is not end-to-end dispatchable until the user-confirmation
      flow ticket ships (Flow 5 is the intended posture).
- [ ] Live acquisition works only where the API process hosts the bridge registry
      (F2: API-process-only; ARQ-worker-triggered syncs use the committed path).
- [ ] Property CREATION is unsupported by the write tool (it edits an existing property
      value only).
- [ ] Fork tests skip when `.venv` is not materialized; S3 artifact backend undeployable
      until infra F11 (dev uses `local`).
