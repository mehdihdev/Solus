# Completion report — SOLUSDEV-205 (SOLUS-TU-02): documentation-ingestion path (KiCad)

**Lane:** D (SOLUSDEV-215) · **Branch:** `SOLUSDEV-215-lane-toolkb` · **Date:** 2026-08-08
**Commit:** `babc29c`

## What was built

- `packages/api/src/solus_api/toolkb/ingest/kicad.py` — the KiCad docs-ingestion path:
  - `parse_tool_actions(source)` — a deterministic parser for KiCad's `TOOL_ACTION` builder-chain
    definitions (`.Name`, `.FriendlyName`/`.MenuText`, `.Tooltip`, `.DefaultHotkey` incl.
    modifiers, `AF_ACTIVATE` flag). This is the authoritative, machine-precise, **vendor-pure**,
    version-scoped catalog of every KiCad command — the TU-01 matrix named it "the cleanest seed
    of the six."
  - `control_id_for(name)` — normalizes KiCad's camelCase action names to CTR-05-valid slugs
    (`eeschema.InspectionTool.runERC` → `kicad.eeschema.inspection_tool.run_erc`).
  - `classify(action)` — **precision over recall**: derives `surface` ONLY from signals the
    source actually carries (`AF_ACTIVATE` ⇒ toolbar tool; KiCad's `…` dialog-menu convention or a
    "show … window" tooltip ⇒ dialog; a default hotkey ⇒ keyboard) and `effect` ONLY from a
    recognized FriendlyName verb, and **skips** anything else rather than guess a wrong pointer.
  - `ingest_kicad_actions(...)` — parse → classify → **guard docs-path** for each classifiable
    command; returns an honest `IngestSummary` (parsed / ingested / skipped / rejected).
- `packages/api/src/solus_api/toolkb/catalog.py` — added `gitlab.com/kicad/code/kicad` to the
  KiCad vendor-doc allowlist (the GPL source is an official vendor definition; curation is Phase 0
  §7.5).

## Acceptance (met)

- **KiCad docs ingested into the KB** with meanings + invocation + provenance, keyed to tool +
  version: **105 of 194 KiCad 9.0 eeschema commands (54%)** land as published `vendor_docs`
  entries scoped to `>=9.0 <10.0` (version window pins them to 9.x — a 9.0.4 query returns them, an
  8.0.6 query does not). Every entry carries label (FriendlyName), description (Tooltip or
  FriendlyName), invocation shortcut where the source gives a hotkey, provenance, and the source
  URL as its docs-path proof.
- The 89 skipped commands are surface-unknowable from this source (no toolbar flag, no dialog
  signal, no hotkey) or carry an unrecognized verb — reported, not guessed. They feed the TU-01
  menu-structure and TU-03 visual ladder steps. This honest coverage is the lane mandate
  (precision over recall) working as intended, not a shortfall.
- pcbnew (`pcb_actions.cpp`, 316 more actions) runs through the identical path — a config
  addition, not a code change — and is available the moment its source is added to `sources`.

## Governing docs / decisions

`docs/contracts/tool-knowledge.md` (the guard's docs path is the only writer; the source URL must
be an allowlisted vendor host) · CTR-05 (control_id slug rules, re-validated by the guard). No new
route (server-side ingestion path). Nothing writes the store except via the TU-06 guard.

## Tests

`tests/toolkb/test_kicad.py` — parser field extraction (inline + the real 194-action fixture),
control_id normalization against the CTR-05 slug validator, classifier rules (activate→toolbar,
`…`/window→dialog, hotkey→keyboard, unknown→skip, unrecognized-verb→skip), end-to-end ingestion
(coverage floor, all-published/vendor_docs/version-scoped, queryable at 9.0.4 not 8.0.6),
idempotent re-run, and a **poisoned-tooltip rejection** (a plausible action whose tooltip carries
`~/designs/arm_v3.kicad_sch` is caught by the guard's CTR-05 net, counted as rejected, never
stored). 14 KiCad tests; full toolkb suite 117 passed; mypy clean.

## Flags for human review

1. **GPLv3 fixture licensing** — `sch_actions_9.0.cpp` is committed verbatim (GPL header intact)
   under `packages/api/tests/toolkb/fixtures/kicad/` as the reproducible corpus. Confirm the
   licensing posture, or switch the path to fetch the source at deploy time. (See the fixture
   README.)
2. **Vendor-doc allowlist widening** — `gitlab.com/kicad/code/kicad` added to
   `VENDOR_DOC_DOMAINS[KICAD]`; part of the Phase 0 §7.5 catalog/doc-domain curation sign-off.
3. **Coverage is source-bounded, not effort-bounded** — 46% of KiCad actions cannot be given a
   surface from `TOOL_ACTION` alone. Closing that gap needs KiCad's menu definitions (TU-01, once
   KiCad is installed and probeable) or docs-prose/visual (TU-03).
