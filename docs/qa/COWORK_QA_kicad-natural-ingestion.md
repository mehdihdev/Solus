> **Superseded by [`COWORK_QA_kicad-integration.md`](COWORK_QA_kicad-integration.md)** — the consolidated checklist. Kept for detail.

# Cowork QA — KiCad natural ingestion (SOLUSDEV-252)

Self-sufficient end-to-end test plan for SOLUSDEV-252: the KiCad connector now accepts the
**default KiCad S-expression netlist** (`.net`, what KiCad's Export Netlist dialog and
`kicad-cli sch export netlist` emit unless told otherwise) as a first-class equal of the XML
netlist, accepts a **`.kicad_pcb` board file** (alone or together with a netlist), and
**refuses raw `.kicad_sch` / `.kicad_pro` files with actionable guidance** instead of a
cryptic parse error. The desktop connect wizard lets a user pick the netlist and/or the board
in one go and sniffs file CONTENT (extensions are never trusted).

Run [`COWORK_QA_kicad-connector.md`](COWORK_QA_kicad-connector.md) first (the base connector
flows still apply); this file covers what SOLUSDEV-252 added or changed.

Legend: ✅ pass · ❌ fail · ➖ blocked/NA

---

## Required setup state

- **Postgres + API running** (`make db-up`, then
  `cd packages/api && uv run uvicorn --factory solus_api.main:create_app --port 8000`),
  a user with a team + project (`<TOKEN>`, `<PROJECT_ID>`), and a second user in a
  DIFFERENT team (`<TOKEN_B>`, `<PROJECT_B>`) for the isolation check.
- **Desktop app** running against that API, signed in as the first user, with the project
  open (Workspace → Connected accounts, or onboarding "Connect your tools").
- **Sample files** (all committed):
  - XML netlist: `integrations/mcp/kicad/tests/fixtures/solus_sample/solus_sample.net.xml`
  - S-expression netlist (real `kicad-cli` 10 export of the same design):
    `packages/api/tests/fixtures/solus_sample.net`
  - Schematic (must be REFUSED): `integrations/mcp/kicad/tests/fixtures/solus_sample/solus_sample.kicad_sch`
  - Project file (must be REFUSED): `integrations/mcp/kicad/tests/fixtures/solus_sample/solus_sample.kicad_pro`
  - Board file: the Python fixture `KICAD_PCB` in `packages/api/tests/fixtures/kicad_sample.py`
    (write it to `sample.kicad_pcb` with
    `uv run python -c "import sys; sys.path.insert(0,'packages/api/tests'); from fixtures.kicad_sample import KICAD_PCB; open('sample.kicad_pcb','w').write(KICAD_PCB)"`).
    It describes the SAME design as `KICAD_XML`/`KICAD_SEXPR` in that module (U1, R1, C1 on
    nets VCC/GND/SIGNAL) plus a board-only mounting hole `H1` and fiducial `FID1`. To pair a
    board with a netlist of the same design, also write `KICAD_SEXPR` to `sample.net`.
- **Optional, for a real-world run:** KiCad 9/10 installed. From any project of yours:
  File → Export → Netlist → default "KiCad" format produces the `.net` this feature exists
  for; your project's `.kicad_pcb` is the board.

Expected fixture counts for `solus_sample`: **9 components**, **22 nets** (XML and
S-expression must agree). For `KICAD_XML`/`KICAD_SEXPR`: 3 components, 3 nets.
For `KICAD_PCB` alone: 5 components (U1, R1, C1, H1, FID1), 3 nets, no edges on H1/FID1.

---

## Flow 1 — The natural path: default S-expression netlist (the reported bug)

1. - [ ] Click the **KiCad** tile → the wizard's first step shows the button
         **"Choose netlist / board file"** and a muted hint: "Netlist export (.xml or .net —
         any KiCad format) and/or your .kicad_pcb. Schematics (.kicad_sch) can't be read
         directly yet."
2. - [ ] The OS picker accepts `.xml`, `.net`, `.kicad_pcb` and allows multi-select.
3. - [ ] Pick `solus_sample.net` (S-expression) alone → progress "Reading solus_sample.net…"
         then "Parsing netlist & building the graph…" → "Connected — N entities indexed".
4. - [ ] `GET /api/v1/projects/<PROJECT_ID>/sources` shows a `kicad` source named
         `solus_sample`, status connected/synced, `last_error` null.
5. - [ ] `GET /api/v1/projects/<PROJECT_ID>/entities` contains 9 `component` entities and 22
         `net` entities; `U1`'s modality hints carry `part_number`,
         `schematic_symbol_name`, and `datasheet_ref`.
6. - [ ] Disconnect, repeat with `solus_sample.net.xml` (XML) → identical component set and
         identical net→pins connectivity (net names may differ only by a leading `/` on
         local labels — KiCad 10 vs 9 producer difference, documented).

## Flow 2 — Board file alone

1. - [ ] Pick `sample.kicad_pcb` alone → "Parsing board & building the graph…" → connected.
2. - [ ] Entities: U1, R1, C1, H1, FID1 as `component`; nets VCC, GND, SIGNAL as `net`;
         `connected_to` edges for U1/R1/C1 only — H1 and FID1 have NO edges.
3. - [ ] No component from a board carries `schematic_symbol_name` (absent by design); U1
         still carries `part_number` from its MPN property.
4. - [ ] The source's sync record has no errors except the documented warning for the
         reference-less footprint in the fixture ("skipped … without a reference").

## Flow 3 — Netlist + board together (reconciliation)

1. - [ ] Multi-select `sample.net` (from `KICAD_SEXPR`) AND `sample.kicad_pcb` in ONE pick
         → "Parsing netlist and board & building the graph…" → connected.
2. - [ ] Components are the NETLIST's (U1, R1, C1 — not H1/FID1); U1/R1/C1 now carry a
         `layer` property from the board.
3. - [ ] `GET …/sources/<id>/syncs/<sync_id>` lists per-item errors prefixed
         `board/netlist mismatch:` for `H1` and `FID1` ("placed on board but not in
         netlist"). Nothing else is flagged for matching files.
4. - [ ] Edit `sample.kicad_pcb`: change R1's Value from the netlist's value to `22k` and
         re-connect → a mismatch error "R1: value differs (netlist '…', board '22k')" appears;
         the graph still shows the NETLIST value (the netlist is authoritative).
5. - [ ] Edit `sample.kicad_pcb`: move R1 pad 2 to net GND → mismatch "R1 pin 2: board net
         'GND' but netlist net 'SIGNAL'"; the `connected_to` edges are unchanged from the
         netlist.
6. - [ ] Re-connecting with ONLY the board changed (same netlist) triggers a new sync
         (change detection covers both files).

## Flow 4 — Refused with guidance (client side, instant)

1. - [ ] Pick `solus_sample.kicad_sch` → the tile errors IMMEDIATELY with "Solus can't read a
         .kicad_sch schematic directly yet. Export a netlist from KiCad (File → Export →
         Netlist, any format) or add your .kicad_pcb board file." — no source is created
         (`GET …/sources` unchanged), no sync runs.
2. - [ ] Pick `solus_sample.kicad_pro` → "A .kicad_pro file holds project settings, not the
         design. Export a netlist from KiCad or add your .kicad_pcb board file."
3. - [ ] Pick a schematic TOGETHER with a valid netlist → the schematic guidance wins (no
         partial connect).
4. - [ ] Pick two netlists → "Choose one netlist export (XML or S-expression)."
5. - [ ] Pick two board files → "Choose one .kicad_pcb board file."
6. - [ ] Rename `solus_sample.kicad_sch` to `fake.net` and pick it → still the schematic
         guidance (content is sniffed, not the extension).
7. - [ ] Pick a random text file → "That doesn't look like a KiCad netlist or board file.
         Choose a netlist export (.xml or .net) or a .kicad_pcb."
8. - [ ] Empty file → "The selected file is empty."; file > 8 MB → "The selected file is too
         large (limit 8 MB)." — both before any upload.
9. - [ ] Closing the wizard after any of these errors leaves the tile in a retryable error
         state; re-opening and picking a valid file connects normally.

## Flow 5 — Refused with guidance (server side, the safety net)

Drive the API directly with `<TOKEN>`:

1. - [ ] `POST /api/v1/projects/<PROJECT_ID>/sources`
         `{"type":"kicad","name":"sch","config":{"export":"<contents of solus_sample.kicad_sch>"}}`
         then `POST …/sources/<id>/sync` → the sync FAILS with error code
         `export_format_unsupported` and a message that names both routes (netlist export,
         `.kicad_pcb`). The Sources list shows the message text in red (not JSON).
2. - [ ] Same with the board file's text in `config.export` → message "kicad: this is a
         .kicad_pcb board file; supply it as the board, not as the netlist export."
3. - [ ] Same with a netlist's text in `config.board` → "kicad: expected a .kicad_pcb board
         file but received a netlist; supply it as the netlist export."
4. - [ ] `config: {}` (neither key) → error code `export_unavailable`; the message names both
         `export` and `board`.
5. - [ ] `config: {"export": "<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'b'>]><export/>"}`
         → `export_invalid` (DTD refused) — unchanged behavior.
6. - [ ] A netlist over 8 MiB, or a board over 8 MiB → `export_too_large`; the limit applies
         per file.

## Flow 6 — Hostile and malformed input (CLAUDE.md §7)

1. - [ ] `config.export` = `(export (version "E") (components (comp (ref "U1"` (unterminated)
         → `export_invalid` mentioning "not a well-formed S-expression"; the API stays up.
2. - [ ] A 7 MiB S-expression netlist made of one component repeated (generate with a script)
         → syncs in a few seconds; memory stays bounded (watch the API process).
3. - [ ] A file of 200 000 nested `(` … `)` → `export_invalid` (nesting limit), not a crash
         or a hang.
4. - [ ] `integrations/mcp/kicad/tests/fixtures/solus_sample/solus_sample_hostile.net.xml`
         still ingests with its adversarial strings landing as inert property VALUES.
5. - [ ] Board with a `comp`/`footprint` smuggled inside a pruned `zone` or `segment` → it
         never appears as an entity.

## Flow 6a — Hardening added in Phase 4 review (SOLUSDEV-252)

Each item below is a fix for a finding the security/code reviews raised, so each
is worth exercising by hand at least once.

1. - [ ] **A BOM-prefixed export is accepted.** Re-save `solus_sample.net` as
         "UTF-8 with BOM" (any editor; or `printf '\xef\xbb\xbf' | cat - solus_sample.net > bom.net`)
         and connect it → syncs normally. Before the fix this failed with a
         misleading "not a well-formed S-expression".
2. - [ ] **The board file is never echoed back.** Connect a source with BOTH
         files, then `GET /api/v1/projects/<PROJECT_ID>/sources` and
         `…/sources/<id>` → the JSON `config` contains NEITHER `export` NOR
         `board` (only your own extra keys). Check the response size: a source
         list must not carry megabytes.
3. - [ ] **Over-cap input is refused at the boundary.** POST a source whose
         `config.board` is larger than 8 MiB → **422** `validation_error`, and
         `GET …/sources` shows nothing was stored. Same for a PATCH.
4. - [ ] **Control characters are refused cleanly.** Insert a NUL byte into a
         netlist value (`printf '(export (components (comp (ref "U\x00"))))' > nul.net`)
         and connect → the sync fails with `export_invalid` naming a "control
         character", NOT an opaque internal error.
5. - [ ] **A hostile board cannot flood the sync record.** Take
         `sample.kicad_pcb`, give one footprint a 70 KB `Value` property, pair it
         with a netlist that disagrees, and sync → the mismatch error message is
         truncated (ends with `…`), and the whole sync's errors stay small
         (`GET …/syncs/<id>` is a normal-sized response).
6. - [ ] **Too many files are refused before reading.** In the wizard, select
         three files at once for KiCad → "Choose at most one netlist export and
         one .kicad_pcb board file." appears immediately, with no source created.
7. - [ ] **An unreadable file fails honestly.** Pick a file, then make it
         unreadable (`chmod 000`) before the read completes, or pick a file on a
         disconnected volume → the tile shows "Could not read the selected file.
         Try choosing it again." and stays retryable. It must never hang on the
         pick step.

## Flow 7 — Cross-team isolation

1. - [ ] As `<TOKEN_B>`, `GET /api/v1/projects/<PROJECT_ID>/sources` and
         `GET /api/v1/projects/<PROJECT_ID>/entities` → 404/403; team B never sees team A's
         KiCad entities, sync errors, or config.
2. - [ ] `GET …/sources/<id>` as the owner → `config` echoes no secrets (there are none for
         KiCad) and the export text is not leaked into any log line.

## Flow 8 — Cross-feature interactions

- [ ] Altium tile: single-file picker unchanged (accept `.xml,.net`, no multi-select, button
      "Choose export file"); an Altium Protel netlist still connects.
- [ ] GitHub/Onshape tiles: unchanged (regression on the shared wizard).
- [ ] Settings → Integrations catalog (`GET /api/v1/integrations`) lists kicad with
      `config_fields: ["export", "board"]`.
- [ ] Live acquisition (companion connected, `COWORK_QA_kicad-mcp.md` Flow 2): the acquired
      netlist still wins over the inline `export`; an inline `board` is merged with it.
- [ ] SOL: ask "which parts share the I2C bus?" on a board-only source → answers from the
      board's nets (SDA/SCL) — no schematic needed.

## Documented limitations (not bugs)

- [ ] Raw `.kicad_sch` is refused, never partially ingested (no connectivity without KiCad's
      netlister). The zero-export path is the linked local folder + companion `kicad-cli`
      export, a separate ticket.
- [ ] Board-derived components carry no `schematic_symbol_name` hint.
- [ ] Board files are inline-only (no live acquisition tool for them yet).
- [ ] The 8 MiB cap applies per file; very large boards must be trimmed or exported as a
      netlist.
- [ ] Two branches exist under SOLUSDEV-252 (the ticket was reused for this work).
