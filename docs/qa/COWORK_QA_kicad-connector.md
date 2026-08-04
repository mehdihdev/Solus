# COWORK_QA — KiCad Connector (SOLUSDEV-100, SOLUS-EDA-01)

> **Phase 2 (MCP) — tested separately.** SOLUSDEV-100 phase 2 added the vendored KiCad
> MCP server fork (`integrations/mcp/kicad/`), live netlist-export acquisition over the
> bridge companion (committed export remains the fallback), the project artifact
> upload/fetch surface, and the confirmation-gated schematic write tool. Those flows —
> plus their isolation and security spot-checks — live in
> [`COWORK_QA_kicad-mcp.md`](COWORK_QA_kicad-mcp.md). Run THIS file first (the committed
> path is phase 2's fallback and must pass on its own), then the MCP plan. The flows
> below are unchanged by phase 2.

End-to-end test plan for the KiCad connector — the electrical PRIMARY (W0-08
§5.2). v1 **parses a committed KiCad XML netlist** (`kicad-cli sch export
netlist --format kicadxml`) into the shared electrical graph shape — components

- first-class nets + `connected_to` relations — via the EDA family base. Unlike
  Altium, KiCad carries the fingerprint identity channels: `part_number` (MPN
  custom field), `schematic_symbol_name` (libsource), `datasheet_ref`.

This ticket ALSO shipped the first real **frontend connect flow for a
file-based connector** (design review Q1=B): the onboarding tile list is driven
by the live `GET /integrations` catalog, and the KiCad (and Altium) tiles drive
a real pick-netlist → create-source → sync flow instead of the simulated
animation. Live REPO acquisition (pulling the committed file at a ref) remains
the family's clearly-marked post-launch scaffold; v1 receives the export
CONTENT via config (from the picked file in the UI).

Legend: ✅ pass · ❌ fail · ➖ blocked/NA

---

## Required setup state

**Backend-level flows (1–7):**

- Python backend deps installed (`uv sync` in `packages/api`).
- No DB, network, or credentials required — the connector is a pure file-parse
  unit (auth_kind = `none`). A sample netlist is embedded at
  `packages/api/tests/fixtures/kicad_sample.py`.

**UI flows (8–10):**

- Backend API running with migrations applied; desktop app running and signed
  in (Supabase auth configured), with a team + project provisioned (the
  onboarding flow creates one).
- A KiCad XML netlist file on disk. Generate from any KiCad project:
  `kicad-cli sch export netlist --format kicadxml -o power-board.xml <schematic>.kicad_sch`
  — or save the fixture content above as `power-board.xml`.
- Optionally a KiCad S-expression `.net` file (the default netlist export) to
  exercise the format-rejection path.

---

## Flow 1 — Parse a committed KiCad XML netlist (the core path)

Run: `cd packages/api && uv run pytest tests/test_kicad_netlist.py tests/test_kicad_connector.py -v`

1. **Components become `component` entities.**
   - [ ] Each `<comp ref="…">` → one `EntityOut(type="component")` keyed by its
         reference designator (`U1`, `R1`, `C1`), `domain=electrical`, with
         `footprint`/`value` in `properties`.
2. **Fingerprint channels flow (the ticket's acceptance).**
   - [ ] `modality_hints.part_number` from the MPN custom field — both the v5
         `<fields><field name="MPN">` and v6+ `<property name="…" value="…"/>`
         encodings, including alias spellings (`Manufacturer_Part_Number`, …).
   - [ ] `modality_hints.schematic_symbol_name` from `<libsource part>`.
   - [ ] `modality_hints.datasheet_ref` from `<datasheet>` — but the `~`
         placeholder means absent, not a hint.
3. **Nets become first-class `net` entities** keyed `net:<NAME>`, carrying
   `net_class` when the export has one. [ ]
4. **Connectivity becomes intra-source `connected_to` edges** — one edge per
   component-on-net with ALL its pins in `properties.pins`. [ ]

## Flow 2 — Conformance suite

- [ ] `KicadConnector` passes `assert_connector_contract`
      (`tests/test_kicad_connector.py::test_passes_connector_conformance_suite`).

## Flow 3 — Change detection (re-parse-and-diff)

- [ ] `detect_changes` False on unchanged content hash; True when the netlist
      content changes; True (fail-safe) when the export is unavailable.

## Flow 4 — Identity & scaffold boundary

- [ ] `validate_credentials` → synthetic `AccountInfo(login="kicad-export")`.
- [ ] `sync` with no `config["export"]` → `ConnectorError("export_unavailable")`
      with a clear "live acquisition not yet implemented" message.

## Flow 5 — XML-only v1 (design review Q2)

- [ ] An S-expression netlist (`(export (version "E") …)`) fails with
      `ConnectorError("export_format_unsupported")` whose message names the fix:
      re-export with `kicad-cli sch export netlist --format kicadxml`.

## Flow 6 — Registry / catalog

Run: `uv run pytest tests/test_registry.py tests/test_sources.py -v`

- [ ] `build_registry` lists `kicad` alongside `altium`/`github`/`gitlab`; the
      catalog entry shows `auth_kind="none"`, `config_fields=["export"]`.
- [ ] `POST /projects/{id}/sources` with `{type: "kicad", name, config: {export: …}}`
      → 201, source lands `connected` with `account_login="kicad-export"` (an
      auth-NONE source has nothing to authenticate — Phase 4 review fix; the
      same now holds for `altium`).
- [ ] The response's `config` does NOT echo the `export` content (bulk config
      keys are stored, never serialized — Phase 4 security fix), and
      `POST …/sync` on that source returns 202 (no secret_ref required for
      auth-NONE connectors).

## Flow 7 — Edge cases & untrusted input (§7)

Run: `uv run pytest tests/test_kicad_netlist.py tests/test_eda.py -v`

- [ ] XML with a `<!DOCTYPE`/`<!ENTITY` declaration (entity-expansion attack) is
      refused (`export_invalid`) BEFORE parsing.
- [ ] Malformed/truncated XML and non-netlist XML roots are refused with
      `export_invalid`, never a stack trace.
- [ ] Components without a `ref`, nets without a `name`, nodes missing
      `ref`/`pin` are skipped with counted warnings that surface as `SyncError`s
      on the sync record (partial parse is visible, not silent).
- [ ] Duplicate designators/nets deduped with `SyncError`s; orphan net nodes
      dropped; oversized export (>8 MB) refused; no eval/exec/subprocess.

## Flow 8 — UI: real KiCad connect from onboarding (NEW)

In the desktop app, onboarding step "Connect your tools":

1. - [ ] The tile grid shows GitHub, KiCad, Onshape, ROS 2 **and Altium** (the
         catalog is live from `GET /integrations`; Altium was invisible before).
2. - [ ] Click **KiCad** → an OS file picker opens (accepts `.xml`/`.net`).
3. - [ ] Pick the KiCad XML netlist → the tile shows live progress
         ("Reading power-board.xml…", "Parsing netlist & building the graph…")
         and lands on "Connected — N entities indexed" with the real count
         (fixture: 6 = 3 components + 3 nets).
4. - [ ] The source appears via `GET /projects/{id}/sources` as type `kicad`
         with a sync record; entities exist via `GET /projects/{id}/entities`.
5. - [ ] Settings → Integrations mirrors the same catalog and shows KiCad
         `● CONNECTED`.

## Flow 9 — UI failure paths

1. - [ ] Pick an **S-expression `.net`** file → the tile shows the error state
         with the re-export guidance message (not a spinner hang, not a crash).
2. - [ ] Pick an **empty file** → immediate "The selected file is empty."
         without any API call.
3. - [ ] Pick a **file > 8 MB** → immediate "too large" error without upload.
4. - [ ] Cancel the file picker → tile stays unconnected, no error.
5. - [ ] With the backend stopped: click KiCad → the tile falls back to the
         SIMULATED animation (dev-bypass path) rather than erroring, because the
         workspace never linked.

## Flow 10 — Cross-feature interactions

- [ ] GitHub tile still drives the real OAuth flow (regression check after the
      shared sync-poll refactor).
- [ ] Onshape / ROS 2 tiles still simulate (not yet backend-registered).
- [ ] GitLab does NOT appear as a tile (live but has no drivable in-app flow —
      hiding it avoids a dishonest fake-connect).
- [ ] Component entities carry `source_key` == graph `external_ref` and the
      three modality hints the fingerprint (W0-06/FP-01) reads — exercised once
      fingerprint lands.

## v1 limitations to confirm are documented (not bugs)

- [ ] XML netlist only; the S-expr `.net` is a documented rejection with
      guidance (kinparse support is a later extension).
- [ ] Live repo acquisition (committed file at a ref) is the family's
      scaffolded post-launch stub — the UI supplies the file content directly.
- [ ] MPN recognition is an alias list (`MPN`, `Manufacturer_Part_Number`,
      `MFR_PN`, `Mfr. Part #`, …, case/punctuation-insensitive); unlisted
      exotic field names fall back to no `part_number` hint.
