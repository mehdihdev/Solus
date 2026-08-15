# Completion Report — SOLUS-CAD-00: shared mechanical-CAD family + STEP/XDE parser

**Status:** built, verified, on branch `SOLUSDEV-60/cad-00-step-parser`.
**HUMAN GATE OPEN: G0 — the OCCT licence call.** The dependency is wired as an OPTIONAL extra
precisely so this can be answered after the fact; nothing ships to a customer until it is.

## Why this ticket exists (it was not in the epic)

The CAD-01..04 tickets each ask for a per-tool "MCP output → EntityOut/RelationOut adapter". The
governing contract says the opposite — `docs/contracts/metadata-extraction.md` §3:

> every CAD connector = {a way to obtain the export file} + {the SHARED geometry/assembly parser}
> … it **ALL flows through ONE shared CAD parser**. The hard work … is done **ONCE**, not per-tool.

That shared parser did not exist (no OCCT dependency anywhere; `integrations/onshape/` was a lone
`.gitkeep`). It is the real critical path for all four tickets, so it was raised in Phase 0 and
approved as CAD-00.

## What was built

### `connectors/mechanical.py` — the CAD family (the EDA family's mechanical twin)

- **CAD IR**: `CadNode(key, name, is_assembly, parent_key, placement, part_number, material,
  properties)` + `CadModel(nodes, warnings)`. Frozen dataclasses, per the immutability rule.
- **`build_mechanical_graph(model)`** — pure IR → `EntityOut` / `RelationOut` / `SyncError`.
  - Every product-structure node → `EntityOut(type="part", domain=MECHANICAL)`; the
    assembly/leaf distinction rides `properties["is_assembly"]` rather than inventing a
    second kind.
  - Hierarchy → `RelationOut(from_key=child, to_key=parent, type="part_of")`, with the
    occurrence's translation on `properties["placement"]` — because STEP yields geometric
    **placements, not semantic mates** (§5.5), and a placement belongs to the occurrence, not
    the product.
  - Dangling parents, duplicate keys, and field-bound overflows degrade to `SyncError`s; a
    partial or adversarial export never fails the whole sync (§7).
- **`CadExportConnector`** — the Connector scaffold. Subclasses supply `provider` + `parse`;
  acquisition is the only per-tool difference. `detect_changes` fails **safe** (an unreadable
  export counts as changed). v1 takes export content on `config["export"]`; CAD-01's REST fetch
  and CAD-02/03/04's MCP export call override `_read_export` and nothing else.

### `connectors/step_parser.py` — STEP → IR through OpenCASCADE XDE

Reads via `STEPCAFControl_Reader` → OCAF → `XCAFDoc_ShapeTool` label walk, **never** the naive
`STEPControl_Reader` that §6.1 warns "flattens the model and discards the assembly hierarchy/part
names". Proven by test, not by assertion — see the evidence section.

### `connectors/export_common.py` — extracted, not duplicated

H6 blocked a second `build_graph`/`_ErrorRecorder`/`_content_sha`, correctly. Rather than rename
around it, the genuinely shared pieces (`ErrorRecorder`, `content_sha`, `label`,
`MAX_SYNC_ERRORS`) were extracted into one module that **both** families now import, so EDA and
mechanical cannot drift. `eda.py` behaviour is unchanged (its 42 tests still pass).

## The identity linchpin

`source_key` is the **occurrence path** derived from file content —
`Bracket/PegPair/Peg[0]` — with an ordinal suffix only where one product is instanced more than
once under the same parent. Never a temp path, `ArtifactRef` id, call id, or file hash. This is
MCP-04 §2.1 invariant 2, and it is what makes an export acquired over the bridge produce byte-
identical graph rows to the same export read from a committed file.

`ponytail:` name-path + ordinal is the strongest content-derived key STEP affords — OCCT's label
entries are allocation-ordered and shift between exports. Upgrade path noted in the module
docstring: key on stable instance UUIDs if a tool ever exposes them.

## Fingerprint channels (decision D-D)

`modality_hints` uses the matcher's own `_HINT_KEYS` spellings — `part_number` and `cad_model` —
because the EDA family's `schematic_symbol_name` / `datasheet_ref` spellings are **dead channels
the matcher never reads**. A test pins this so the mistake cannot be repeated here.

**Honest scope:** `test_step_carries_no_part_numbers_so_hints_stay_empty` asserts that STEP yields
no MPNs, because STEP's product structure has no part-number slot. Part numbers arrive from the
**tool's metadata API** (Onshape, CAD-01) and are merged onto the IR — never invented from a CAD
id. Until that lands, CAD entities carry `cad_model` only, which the matcher leaves unmatched by
design. No FP-01/FP-02 invariant was touched.

## Verification

- `uv run ruff check .` — **clean**
- `uv run mypy packages/api/src` — **clean, strict, 113 files** (added an `OCP.*`
  `ignore_missing_imports` override beside the existing `pgvector.*`/`asyncpg` ones; the wheel
  ships no `py.typed`)
- `uv run pytest -q` — **1306 passed, 4 skipped** (full suite, real Postgres)
- Single alembic head — unchanged, `a7c5d2e91f04` (no migration in this ticket)
- 34 new tests: 6 `test_export_common` · 18 `test_mechanical` · 10 `test_step_parser` (+1 skipped:
  the reader-absent path, unreachable while OCCT is installed)

### The make-or-break evidence (§6.1)

`tests/fixtures/bracket.step` is a real 34 KB AP214 file with a three-level product structure and
one product instanced twice. Parsed through XDE it yields exactly:

```
Bracket                      (assembly, root)
├── Bracket/BasePlate        (part)
└── Bracket/PegPair          (assembly)
    ├── Bracket/PegPair/Peg[0]   @ (5, 8, 5)
    └── Bracket/PegPair/Peg[1]   @ (20, 8, 5)
```

Tests assert the tree, the surviving product names, the assembly/leaf flags, **two distinct
occurrence keys for one twice-instanced product**, distinct per-occurrence placements, and
determinism across repeated reads.

## Delegated-judgment decisions

1. **OCCT is an OPTIONAL extra (`cad`), not a runtime dependency.** The import is lazy and its
   absence is a clean `ConnectorError("step_reader_unavailable")` naming the extra — never an
   `ImportError` reaching a request. This keeps G0 reversible: if the licence call goes the other
   way, the reader is swapped without touching the IR, the mapping, or any connector. It is in the
   dev group so CI exercises the real path.
2. **`part` for all product-structure nodes**, with `is_assembly` as a property, rather than
   inventing `cad_assembly`. Follows §5.5 and decision D-C.
3. **Placement on the edge, not the entity** — an occurrence's transform is a property of the
   occurrence relationship.
4. **`_safe_path_segment`** neutralises `/` in product names so a crafted name cannot forge an
   ambiguous occurrence path (same class of guard as the fingerprint's separator-collision fix).
5. **`MAX_CAD_EXPORT_BYTES = 64 MiB`** (vs EDA's 8 MiB) — a real robot assembly's STEP runs to
   tens of MB, so the EDA bound would refuse ordinary files.
6. **`MAX_ASSEMBLY_DEPTH = 32`** bounds recursion against a pathological or cyclic file.

## Environment findings worth recording

- **This worktree's `.venv` was empty**; tests were silently resolving `solus_api` from the PARENT
  checkout (`/home/beeboss/Solus/packages/api/src`), so worktree edits were invisible. Fixed with
  a full `uv sync --all-packages`. **Run `uv run` without `--active`** — `VIRTUAL_ENV` points at
  the parent venv and must be ignored.
- **OCCT works on linux/aarch64** despite `cadquery-ocp` publishing only x86_64 wheels:
  `cadquery-ocp-novtk` 7.9.3.1.1 resolves via `cadquery-ocp-proxy` and installs (59 MiB).
  `cadquery-ocp-arm` is a red herring — macOS-only, Python ≤3.11, stale since 2024.

## Open items for humans

1. **G0 — the licence call.** `cadquery-ocp-novtk`: binding Apache-2.0, **bundled OCCT kernel
   LGPL-2.1-with-exception**. W0-08 §6.6: *"This must be reviewed by a human, not decided by an
   agent."* Note the contract's "LGPL-3.0" label for these readers is imprecise. Until signed off,
   the extra must not be promoted into `dependencies`.
2. **Docker build test** — §6.1 requires packaging the OCCT native stack in a real Docker build.
   Not done here (no Dockerfile change in scope); flagged for the deployment ticket.
3. `docs/architecture/` remains empty; no diagram governs CAD ingestion.

## Contract/doc changes

None. This ticket implements the existing contract; no amendment was needed.
