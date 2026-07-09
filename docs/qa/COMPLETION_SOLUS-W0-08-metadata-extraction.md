# Completion Report — SOLUS-W0-08: Metadata-Extraction Strategy

**Branch:** `SOLUSDEV-72-shared-dev-models`. **Status:** complete, validation-green (doc-only), left
uncommitted for human review → MR.

---

## What was built

`docs/contracts/metadata-extraction.md` (377 lines) — the v1 ingestion strategy doc that pins WHAT each
connector parses and emits, so every connector ticket points to its ROW. Doc-only; **no parsers,
connectors, or the shared CAD parser were built** (those are downstream tickets). Operationalizes ADR-030
(parse committed Git exports v1) and consumes the W0-05 connector shapes + W0-06 `modality_hints`.

Contents: core strategy · acquisition mechanisms (roster table: live API / committed exports / Onshape
thin-API→shared parser) · **the unifying principle** (all CAD connectors converge on ONE shared
geometry/assembly parser) · explicit v1-real vs deferred (Gerber deferred) · per-format ROWS with
file→`EntityOut`/`RelationOut` field mappings (code tree, KiCad XML netlist, SPICE, Altium, STEP, STL,
DWG) using the real enums + `<->` `domain_pair` · **researched parser candidates with tradeoffs +
licensing** (all verify-before-pinning; DWG riskiest) · two surfaced graph-model gaps · open-risks summary.

## Parser research (verified 2026-07-05, 5 parallel web-research threads — all VERIFY-before-pinning)

- **STEP** → assembly structure needs OpenCASCADE XDE (`pythonocc-core` LGPL / `cadquery-ocp-novtk` LGPL);
  a naive read flattens the tree. STEP yields geometric _placements_, not semantic _mates_.
- **STL** → mesh-only, **no assembly structure or part identity** (`trimesh` MIT for geometry) → assembly
  must come from STEP.
- **DWG** → no pure-Python reader; convert-first (ODA File Converter → `ezdxf` MIT). It's a 2D drawing, not
  an assembly tree. **Riskiest** — validate early or deprioritize.
- **Netlist** → **KiCad has no JSON netlist through v10**; target KiCad XML (stdlib) or S-expr `.net`
  (`kinparse` MIT); "JSON netlist" is tool-specific (tscircuit/atopile).
- **SPICE** → `spicelib` (GPLv3) or `dan-fritchman/Netlist` (BSD); netlist authoritative for identity,
  SPICE adds sim params, **disagreement → emit a mismatch signal**.

## Phase-4 review (fresh-context) — NEEDS-FIXES → all fixed

- **HIGH (fixed):** `RelationOut` has NO `attrs` field (`extra="forbid"`) — my §5.2/§7 had routed net/pin
  metadata and the enum-gap workaround through a nonexistent relation `attrs`. Corrected: net connectivity
  is documented as pairwise edges without per-net/pin detail, and this is surfaced as a **second graph-model
  gap (§7b)**.
- **MEDIUM (fixed):** two `(§7)` refs in the DWG section meant CLAUDE.md §7 (Security), not this doc's §7 —
  now cite `CLAUDE.md §7`.
- **LOW (fixed):** `src`/`dst` shorthand annotated; URDF/robot-description scoped out (→ Live Bench sim).
- **Verified correct:** all 7 acceptance criteria met; enum usage clean (no invented values used as real);
  the `RelationType` gap + JSON-netlist correction + ADR-030 citation + parser-as-candidates framing all sound.

## Flags for the founders (graph-model changes this strategy surfaces — human-owned, migration-bearing)

1. **`RelationType` enum is missing mechanical/connectivity values** (`part_of`, `mates_with`,
   `connected_to`) — needed before CAD/EDA ingestion can emit full assembly structure + net connectivity.
   Currently connectors map to the nearest existing value (`mounted_on`/`soldered_to`).
2. **`RelationOut` has no metadata channel** — unlike `EntityOut`, it carries no `attrs`, so a relation
   can't hold the net name, pins, confidence, or precise sub-kind. Resolve by adding `RelationOut.attrs`
   (the ORM `graph_edge.attrs` already exists) OR modeling the electrical NET as its own entity.
3. **Licensing is a cross-cutting legal decision** — several strong parsers are copyleft (GPLv3: `spicelib`,
   LibreDWG) or EULA-gated (ODA File Converter is **non-commercial-only** — a paid SaaS needs ODA membership
   ~$4.5k/yr). Permissive alternatives exist for most (MIT/BSD noted per format). Get legal sign-off before
   pinning.
4. **DWG DEPRIORITIZED (founder decision — applied to the doc).** DWG is now DEFERRED to a later tier across
   the doc (§1/§2/§4 tables, §5.7, §6.4, §8): mechanical v1-real is **STEP + STL** only; the researched DWG
   analysis is retained, clearly marked deferred, for when it is revived (avoids the ODA-membership cost + ops
   burden for a format robotics teams rarely use). When revived, the ODA-membership license + end-to-end path
   must be validated first.
5. **Doc-currency (out of scope to edit here):** the ⚠ flag in `connector-interface.md` (said ADR-030
   didn't exist yet) is now stale — ADR-030 is in `DECISIONS.md` and this doc closes it. Recommend a human
   tidy of that flag. (`temp-DECISIONS.md` also still holds the ADR-030 draft copy — can be cleaned.)

## Verification

Doc-only (no mypy/ruff/pytest). Self-checks: all 7 acceptance-criteria keywords present; correct enum
values + lowercase `<->` `domain_pair` (no Unicode-arrow/uppercase in mappings); ADR-030 cited from
`DECISIONS.md`; the two graph-model gaps documented; invented enum values never used as if real. Fresh-context
review APPROVE-after-fixes.

## Handoff

Review the doc + this report; decide the two graph-model gaps (§7a/§7b) and the licensing/legal question;
each downstream connector ticket implements a ROW + the one shared CAD parser (§3).
