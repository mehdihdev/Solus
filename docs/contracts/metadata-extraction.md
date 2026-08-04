# Metadata-Extraction Strategy — v1 Ingestion Contract (SOLUS-W0-08)

**Status:** Strategy/documentation contract. Pins the v1 ingestion strategy — what each connector
PARSES and EMITS — plus researched parser candidates (all **verify-before-pinning**) and per-format
file→`EntityOut`/`RelationOut` field mappings. **No parsers, connectors, or the shared CAD parser are
built here** — those are downstream connector tickets that reference the ROWS below.
**Authority:** ADR-030 (parse committed Git exports v1, not live tool plugins — `DECISIONS.md`), as
extended by ADR-031 (MCP hosting model: fork–harden–own; forked Solus-owned MCP servers on the
customer machine via the bridge; Accepted 2026-07-30) — ADR-030's own revisit clause ("a live-plugin
or API-pull path is evaluated behind the same `Connector` interface (the interface does not change;
only the extraction mechanism does).") is exactly the clause this amendment exercises,
W0-05 connector interface (`EntityOut`/`RelationOut`; intra-source only; `source_id ==`
`graph_entity.external_ref`), W0-06 fingerprint (`modality_hints` feed the matcher), ADR-001
(graph-centric), ADR-027 + `packages/api/src/solus_api/models.py` (the `EntityKind`/`RelationType`/
`Domain` enums + the `domain_pair` format). No code owned; references `connectors/`.

Consumers: every design-artifact connector ticket points to its ROW here for what it parses and the
exact fields it emits, so a family of connectors mirrors itself. **The CAD rows (§5.4–§5.6, §6) are
the ones for Pratham to review** — they converge on one shared parser and carry the most risk.

> ⚠ **Library pins are candidates, researched 2026-07-05, flagged VERIFY-before-committing.** Parser
> choices below were researched against current (2025-2026) options with the central question _"does it
> extract ASSEMBLY STRUCTURE + inter-part relationships, not just raw geometry?"_ — but versions,
> maintenance, and (critically) **licensing** must be re-checked and validated on REAL customer files
> before any is pinned. DWG is DEFERRED to a later tier (highest-risk — §5.7/§6.4).

---

## 1. Core strategy

v1 ingestion **PARSES DESIGN-EXPORT FILES** rather than integrating deeply/live with every proprietary
tool (ADR-030). Teams already commit their exports — STEP/STL, netlists, SPICE decks (and DWG, whose parsing is deferred, §5.7) — to Git;
those are versioned, diffable, and available without a running desktop tool. This makes the connector
roster tractable and defines the payloads connectors emit. The connector reads the committed export (or,
for code hosts, the live repo API), parses it, and emits normalized `EntityOut`/`RelationOut`
(W0-05). Change detection is the W0-05 re-parse-and-diff path fired by the repo's commit events (ADR-030).
Where a team runs the bridge companion with a vendored MCP server for their desktop tool
(`integrations/mcp/<tool>/`, MCP-03), the SAME export file may instead be acquired by a **live MCP
export call** (§2.1) — a third acquisition mechanism. Parsing is untouched either way: the export
lands in the same parser regardless of how it was obtained.

- **v1-real (actually parsed in v1):** electrical netlists (KiCad XML primary + SPICE deck + Altium
  export), mechanical CAD (**STEP + STL** → geometry + assembly structure + inter-part connections,
  via ONE shared parser), and code (repo tree via the GitHub/GitLab API).
- **Deferred (NOT v1):** **DWG** (deprioritized — no pure-Python reader, a licensing minefield, and it is
  a 2D drawing not an assembly tree; robotics teams lean Onshape/STEP/KiCad — §5.7/§6.4), **Gerber**
  (manufacturing/copper data — low value for the cross-domain graph), and any proprietary-tool-specific
  DEEP integration beyond export parsing.

---

## 2. How each connector obtains its data

Two acquisition mechanisms, plus the Onshape thin-API refinement. Acquisition differs; the parsing (§3)
does not.

| Connector  | Family         | Acquisition                                                                          | v1 format(s) parsed                                    | Parser (§6)                   |
| ---------- | -------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------ | ----------------------------- |
| GitHub     | Code           | **Live API** — repo tree                                                             | files/modules + imports                                | GitHub REST/GraphQL trees API |
| GitLab     | Code           | **Live API** — repo tree                                                             | files/modules + imports                                | GitLab REST trees API         |
| KiCad      | EDA            | **Committed export in the linked Git repo**                                          | KiCad XML netlist (or S-expr `.net`)                   | stdlib XML / `kinparse`       |
| LTspice    | EDA            | **Committed export**                                                                 | SPICE deck (`.net`; `.asc` only if no netlist)         | `spicelib`                    |
| NgSpice    | EDA            | **Committed export**                                                                 | SPICE deck (`.cir`/`.net`)                             | `spicelib`                    |
| Altium     | EDA            | **Committed export**                                                                 | Protel netlist (or SPICE / orcadpcb2)                  | stdlib state machine          |
| Onshape    | Mechanical CAD | **Thin API** — auth + detect change + fetch/generate STEP/STL export → shared parser | STEP/STL                                               | shared CAD parser (§6.1)      |
| Fusion 360 | Mechanical CAD | **Committed export**                                                                 | STEP/STL (DWG deferred)                                | shared CAD parser             |
| SolidWorks | Mechanical CAD | **Committed export**                                                                 | STEP/STL                                               | shared CAD parser             |
| AutoCAD    | Mechanical CAD | **Committed export**                                                                 | **DWG — DEFERRED** (§5.7); STEP if the team commits it | shared CAD parser             |

- **Live API (code hosts):** GitHub, GitLab — query the API for the repo tree; entities = files/modules,
  relations = imports/references.
- **Committed exports in the linked Git repo (most CAD/EDA):** the team commits the export file and the
  connector reads & parses the committed file.
- **Thin API + shared parser (Onshape — the key refinement):** Onshape uses its API ONLY for the thin
  layer — authenticate, DETECT CHANGES, and FETCH/GENERATE a STEP/STL export — then routes that export
  into the SHARED CAD parser (same parser the other CAD tools use). Onshape is **NOT** a deep live-API
  integration; the API is just a means to get the file and know it changed. **Fallback:** if a needed
  format isn't API-exportable from Onshape, fall back to pulling structural data from the API for that
  piece.
- **Live MCP export call (bridge-connected teams — the MCP-04 refinement):** for any committed-export
  row whose desktop tool has a **vendored MCP server** (`integrations/mcp/<tool>/`, MCP-03), the
  connector may obtain the SAME export file by dispatching that server's export tool through the
  W0-04 registry and the bridge (`MCPTool`, MCP-01) instead of reading the committed copy. This is
  **Onshape-thin-API-shaped**: the MCP call is a means to get the file and know it changed —
  authenticate/launch, drive the local tool to emit STEP/STL/netlist/deck, return the bytes — NEVER
  a deep live integration. Mechanism details and invariants: §2.1. **The committed-export path is
  retained as the fallback and remains the default** whenever no companion is connected.

**Table note (MCP-04):** every "**Committed export**" acquisition cell above reads as "Committed
export — or a live MCP export call (§2.1) when the team's bridge companion is connected and a
vendored server exists for the tool." The format parsed and the parser column are unchanged; only
how the file arrives differs.

> **Roster note.** The repo names "~9 design-artifact connectors" (GitHub, GitLab; Onshape + proprietary
> STEP/DWG CAD; KiCad, LTspice, NgSpice, Altium). **Fusion 360 / SolidWorks / AutoCAD are instances of the
> generic "proprietary STEP/DWG" mechanical-CAD bucket**, not separately scaffolded. **ROS is runtime**
> (Live Bench telemetry, ADR-014/029) — NOT a design-artifact parse connector, so it is out of scope here.

### 2.1 Live MCP acquisition — the bridge path (MCP-04)

**Flow.** Change detection or a sync triggers the connector → the cloud dispatches the vendored
server's export tool as a normal W0-04 `ToolCall` through the untouched `ToolRegistry` and the
bridge channel → the forked server (running on the customer machine, `integrations/mcp/<tool>/`)
drives the local desktop tool to produce the export (STEP/STL, netlist, SPICE deck) → the export
returns as the tool result — **bulk bytes ride an `ArtifactRef`** (`ArtifactStorage.CLIENT`, per
the bridge contract's size caps), never inlined — → the runtime materializes the bytes to a
temporary working file → **the SAME parser the committed-file path uses** (§3) parses it → the
SAME `EntityOut`/`RelationOut` emission (§5 rows, unchanged).

**Invariants (each load-bearing):**

1. **Mapping preservation.** The parser and the §5 field mappings cannot tell acquisition paths
   apart — they receive a file, full stop. No parser, mapping, or `modality_hints` change is
   permitted under this mechanism; a divergence is a defect.
2. **Identity is content-derived, never transport-derived.** `source_key` (≡
   `graph_entity.external_ref` ≡ fingerprint `SourceRef.external_ref`, Edit 3) derives from the
   design content exactly as §5 defines it (refdes, part/instance id, repo-relative path) —
   **NEVER** from temp-file paths, `ArtifactRef` ids, call ids, or anything else the transport
   invents. A byte-identical export acquired via either path yields identical
   `EntityOut`/`RelationOut` — and therefore **the fingerprint (W0-06) receives identical
   canonical-part inputs regardless of source**.
3. **Fallback retention (ADR-030 baseline).** The committed-file path is not removed, not
   deprecated, and needs no companion: bridge absent, offline, tool closed, or the MCP call
   failing (`ToolResult(ok=false)` — the never-raises envelope) → the connector falls back to
   the committed export for that sync, logging the degradation. When both are available, the
   live export is preferred as the fresher working copy; the committed file remains the
   versioned historical record.
4. **Untrusted either way.** An export produced by a local tool via MCP is EXACTLY as untrusted
   as a committed file (CLAUDE.md §7): same defensive parsing, same size bounds, same
   zip/traversal guards. Arriving over the bridge grants no trust — the channel's ingress caps
   and the fork's security review (MCP-03) bound the transport, and the parser assumes hostility
   regardless.
5. **Export tools are non-destructive reads** and are allowlisted per fork
   (`integrations/mcp/<tool>/allowlist.yaml`); an export tool needs no confirmation gate. Any
   vendored tool that MUTATES the design is outside this mechanism and carries
   `requires_confirmation: true` per MCP-03.

> **§2.1 addendum — ratified export transport (2026-08-03, SOLUSDEV-100; F1 decision,
> human-approved in-session; tier-1 amendment per ADR-032).** The Flow paragraph above
> predates the built transport; this paragraph supersedes its "bulk bytes ride an
> `ArtifactRef` (`ArtifactStorage.CLIENT`…), never inlined" clause. As ratified and built:
> a live export **≤ 512 KiB** (`artifact_inline_max_bytes`, `docs/api/artifacts.md` §4.4)
> rides **inline** in the tool result (`content`); a larger export is written by the fork to
> a **workspace-confined file** and returned as a workspace-relative `artifact_path`, which
> the **COMPANION** — never the fork, never the cloud — uploads via
> `POST /api/v1/projects/{project_id}/artifacts` (`docs/api/artifacts.md` §2) and rewrites
> in the `tool_result` into the returned W0-04 `ArtifactRef` before the frame crosses the
> bridge (`storage` reports the backend actually holding the bytes: `s3` prod / `local`
> dev). Cloud-side consumption is **one-shot**: the sync acquirer fetches the bytes exactly
> once, and only after the full **six-condition anti-forgery match** against the originating
> tool call (`docs/api/artifacts.md` §4.3 — project scope, team scope, creator = the
> dispatched acting user, `source_tool`, `tool_call_id`, and liveness/first-consumer-wins);
> any mismatch or failure anywhere in the chain declines the live path and **invariant 3's
> committed-file fallback proceeds unchanged**. The five invariants above are NOT modified
> by this addendum; invariant 5 in particular is untouched — the fork's one mutating tool
> (`set_symbol_property`) is allowlisted `requires_confirmation: true` and sits entirely
> outside this export mechanism.

---

## 3. THE UNIFYING PRINCIPLE — one shared CAD parser

**Every CAD connector = {a way to obtain the export file} + {the SHARED geometry/assembly parser}.** The
"way to obtain" differs — Onshape fetches STEP/STL via its API and change-detects; Fusion/SolidWorks/
AutoCAD read committed exports from Git; bridge-connected teams may obtain the same file by a live
MCP export call (§2.1) — but once you have the STEP/STL (and, later, DWG), it **ALL flows through ONE
shared CAD parser**. The hard work — parsing geometry + assembly structure + inter-part relationships — is
done **ONCE**, not per-tool. This is why the CAD family mirrors: the connectors converge on one parser and
differ only in file acquisition. (Formats differ in what they can yield — STEP carries the assembly tree,
STL is geometry-only, DWG is a 2D drawing — see §5–§6; the shared parser dispatches by format.)

---

## 4. v1-real vs. deferred (explicit)

| Domain            | v1-real (parsed in v1)                                                                                                      | Deferred                                                              |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| **Electrical**    | KiCad XML netlist (**primary** — components + connectivity) + SPICE deck (sim params + topology) + Altium export equivalent | —                                                                     |
| **Mechanical**    | STEP + STL → geometry + **assembly structure + inter-part connections** (NOT a flat part list), one SHARED CAD parser       | **DWG** (deprioritized — §5.7/§6.4)                                   |
| **Code**          | repo tree via GitHub/GitLab APIs                                                                                            | —                                                                     |
| **Manufacturing** | —                                                                                                                           | **Gerber** (copper/manufacturing data — low cross-domain-graph value) |
| **Any**           | export parsing only                                                                                                         | any proprietary-tool DEEP/live integration beyond export parsing      |

> **URDF / robot-description note.** URDF (and SDF/xacro) are committed, parseable exports too, but they
> describe robot KINEMATICS for **Live Bench Sim (ADR-014)**, not the design-artifact cross-domain graph.
> They are out of scope for this ingestion doc; if graph ingestion of URDF is later wanted, it gets its own
> row/ticket.

---

## 5. Per-format ROWS — extraction depth + field mapping

Field mappings use the real enums (`models.py`): `EntityKind` = `code_file`/`component`/`part`/`cad_body`;
`RelationType` = `references`/`soldered_to`/`mounted_on`/`same_as`; `domain_pair` = lowercase `Domain`
values joined by `<->` (e.g. `electrical<->electrical`). `source_id` is the stable per-tool id and **==**
`graph_entity.external_ref` **==** fingerprint `SourceRef.external_ref`. Relations are **intra-source only**,
and `src`/`dst` below abbreviate `RelationOut.src_source_id`/`dst_source_id`. See §7 for the two graph-model
gaps (missing `RelationType` values; `RelationOut` has no `attrs`) that these mappings expose.

### 5.1 Code repo tree (GitHub / GitLab) — live API

- **Obtain:** GitHub/GitLab trees API (live).
- **Entities:** files/modules → `EntityOut(kind="code_file", source_id=<file path>, attrs={language, path,
size, ...})`.
- **Relations:** imports/references between files → `RelationOut(relation_type="references",
domain_pair="code<->code")`, `src`/`dst` = the two file paths.
- **modality_hints:** usually none for code files (identity is the path); optional module name.

### 5.2 KiCad netlist (electrical, PRIMARY) — committed export

> **Research correction (verify):** KiCad has **no JSON netlist export** through v10. The v1 target is the
> **KiCad XML netlist** (`kicad-cli sch export netlist --format kicadxml`) — the documented intermediate
> that all other formats derive from, schema-stable across v5–v10, parseable with the stdlib. The default
> S-expr `.net` is the fallback (parser: `kinparse`). A true-JSON netlist exists only for specific tools
> (tscircuit "Circuit JSON", atopile) — parse those with stdlib `json` + a per-producer adapter. The
> ticket's "JSON netlist (primary)" is realized here as **the structured netlist export (KiCad XML
> primary; JSON where a tool emits it)**.

- **Obtain:** committed KiCad XML netlist (or `.net`) — or acquired via a live MCP export call (§2.1); parsing and field mapping identical.
- **Entities:** each component → `EntityOut(kind="component", source_id=<ref designator, e.g. "U1">,
attrs={value, footprint, datasheet, libsource, ...})`.
- **modality_hints (→ fingerprint, W0-06):** `{part_number (from MPN custom field), schematic_symbol_name
(libsource part), datasheet_ref (if present)}`.
- **Relations:** net connectivity — pairwise between components sharing a net → intra-source
  `RelationOut`, `domain_pair="electrical<->electrical"`. **`relation_type`:** closest existing value is
  `soldered_to` (net-connected pins); see §7 — a generic `connected_to`/`net` value is not in the enum
  yet. **Gap (§7):** `RelationOut` has NO `attrs` field (and `extra="forbid"`), so the net name and the
  specific pins (`ref`, pin `num`/`pinfunction`) have nowhere to live on a pairwise edge — expressing full
  net connectivity needs either a `RelationOut.attrs` field or modeling the NET itself as an entity.
- **Fields out (richest of the three):** per component `ref, value, footprint, datasheet, custom fields
(MPN/manufacturer), libsource, sheetpath, tstamp`; per net `code, name, class, nodes(ref, pin num,
pinfunction, pintype)`.

### 5.3 SPICE deck (electrical) — committed export

- **Obtain:** committed SPICE deck (`.cir`/`.net`; LTspice: prefer the exported `.net` over the `.asc`
  schematic) — or acquired via a live MCP export call (§2.1); parsing and field mapping identical.
- **Entities:** circuit elements → `EntityOut(kind="component", source_id=<SPICE element name, e.g. "R1">,
attrs={element_type, value, model, model_params, ...})`.
- **Relations:** circuit topology (element→node connectivity) → intra-source `RelationOut`,
  `domain_pair="electrical<->electrical"`.
- **Reconciliation with the netlist (documented):** the **netlist is authoritative for component
  IDENTITY** (refdes / manufacturer part / footprint); **SPICE ADDS simulation params** (values, `.model`,
  `.param`, `.tran`/`.ac` directives) and **corroborates topology**. Join key = **refdes** (`R1`, `U3`),
  shared by both. SPICE node names are often anonymous (`N001`) vs the netlist's named nets, so treat SPICE
  topology as corroboration, not the primary edges. **On disagreement between netlist and SPICE for the
  same refdes, DO NOT silently merge — emit a mismatch** for the checker/agent layer (that cross-source
  disagreement is exactly what Solus exists to surface).

### 5.4 Altium export (electrical) — committed export

- **Obtain:** committed **Protel netlist** (recommended — native, simplest; or SPICE, or `orcadpcb2`) — or acquired via a live MCP export call (§2.1); parsing and field mapping identical.
- **Maps to the SAME component + connectivity model as KiCad:** component blocks `[ ... ]` (designator,
  footprint/pattern, comment/value) → `EntityOut(kind="component", source_id=<designator>)`; net blocks
  `( ... )` (net name, `Designator-Pin` nodes) → intra-source connectivity relations,
  `domain_pair="electrical<->electrical"`.
- **Flag:** stock Protel carries value/comment but **not a native MPN field** — for supply-chain identity
  (`modality_hints.part_number`) either map a Protel comment field or pull a separate ActiveBOM/CSV. Verify
  with the team's actual export. (`orcadpcb2` is the "one parser for both KiCad and Altium" shortcut if only
  ref/value/footprint + connectivity is needed.)

### 5.5 STEP (mechanical, shared parser) — the assembly source

- **Obtain:** committed STEP (Fusion/SolidWorks) or Onshape API fetch — or acquired via a live MCP export call (§2.1); parsing and field mapping identical.
- **Entities:** parts/bodies in the assembly → `EntityOut(kind="part" | "cad_body", source_id=<the
part/instance id in the assembly>, attrs={name, geometry summary, dimensions/bbox, material if present,
absolute placement})`.
- **modality_hints:** `{cad_model_id, part_number if embedded in the product metadata}`.
- **Relations:** assembly hierarchy + inter-part positioning → intra-source `RelationOut`,
  `domain_pair="mechanical<->mechanical"`. **`relation_type`:** `mounted_on` exists; a part-of-assembly
  hierarchy edge (`part_of`) and a semantic `mates_with` do NOT (§7).
- **Depth (make-or-break):** extract the **assembly TREE + part identities + names + relative placements**,
  not just geometry. This lives in STEP's product structure and is reachable only via OpenCASCADE XDE (§6.1)
  — a naive STEP read flattens it. **STEP yields geometric PLACEMENTS, not semantic mate/joint constraints**
  (those are proprietary to each CAD tool); `mates_with` must be INFERRED from coincident geometry/placement
  — scope that expectation now.

### 5.6 STL (mechanical, shared parser) — geometry only

- **Obtain:** committed STL or Onshape API fetch — or acquired via a live MCP export call (§2.1); parsing and field mapping identical.
- **KEY LIMITATION (confirmed):** STL is a **flat triangle mesh — NO assembly structure, NO part identity,
  NO relationships** (binary STL has no naming at all; ASCII solid-names are unreliable and often unparsed).
  **Assembly structure MUST come from STEP, not STL.**
- **Use:** geometry only → `EntityOut(kind="cad_body", source_id=<file/body id>, attrs={bbox, volume, mass
properties, watertight, triangle/vertex counts})`; a geometric connected-body count is at best a WEAK
  modality hint (touching parts merge; split parts fragment). No relations from STL alone.

### 5.7 DWG (mechanical) — **DEFERRED to a later tier** (founder decision, W0-08)

- **Obtain:** committed DWG → **convert to DXF first** (no pure-Python DWG reader; §6.4), then parse.
- **FRAMING CORRECTION (research):** DWG is fundamentally a **2D-drawing** format — its "structure" is
  layers, block definitions (`BLOCK`), block references (`INSERT`), layouts, and external references
  (`XREF`) — **NOT** a mechanical assembly/mate tree like STEP. It can embed 3D ACIS solids but stores no
  parametric B-Rep or part/assembly hierarchy.
- **Entities/Relations (where meaningful):** blocks/inserts → `EntityOut(kind="cad_body" | "part")`; XREF /
  layout containment → intra-source relations, `domain_pair="mechanical<->mechanical"`. For true assembly
  relationships, DWG is the wrong source — prefer STEP.
- **FLAG:** DWG is the **RISKIEST parser** (§6.4) — proprietary format, external converter or paid SDK or
  cloud API on the critical path, and a **licensing minefield**. Validate the end-to-end path early; if
  target customers lean Onshape/STEP/KiCad, **deprioritize DWG to a later tier**.

- Domain values use the canonical `Domain` enum (`code`/`electrical`/`mechanical`/`simulation`/
  `runtime`). Where §5 shows the code domain as `software`, it is now `code` (the connector was
  reconciled: `Domain.SOFTWARE` → `Domain.CODE`). `domain_pair` examples: `code<->code`.
- `graph_entity.kind` and `graph_edge.relation_type` are now **free strings**, not the closed
  `EntityKind`/`RelationType` enums. So the code/design families the connector already emits —
  `code_repo`, `code_module`, `code_file`, `design_export` — are valid kinds directly (they no
  longer need to "fit" a 4-value enum). Remove the "field mappings use the real enums
  `EntityKind` = …, `RelationType` = …" preamble, or reword it to "well-known values, not enforced".

---

## 6. Parser-library research — tradeoffs (VERIFY before pinning)

Researched 2026-07-05 against current options. **Central question per format: can it extract ASSEMBLY
STRUCTURE + inter-part relationships (not just raw geometry/mesh)?** Every pin is a candidate to validate
on real customer files. A cross-cutting **licensing** dimension runs through all of them (§6.6).

### 6.1 STEP — assembly structure (make-or-break)

Assembly structure comes from OpenCASCADE's **XDE/XCAF** layer (`STEPCAFControl_Reader` → OCAF document →
walk `XCAFDoc_ShapeTool` labels for the tree, names, colors, `TopLoc_Location` transforms). A naive
`STEPControl_Reader` **flattens the model and discards the assembly hierarchy/part names**.

| Candidate                                     | Assembly structure?                                                                    | Maturity             | License   | Heavy deps                                                            |
| --------------------------------------------- | -------------------------------------------------------------------------------------- | -------------------- | --------- | --------------------------------------------------------------------- |
| **pythonocc-core** (default)                  | **YES** — full OCCT XDE; ships a `read_step_file_with_names_colors()` helper to extend | Active (7.9.x, 2026) | LGPL-3.0  | OCCT C++; **conda-first** (Docker friction)                           |
| **cadquery-ocp / OCP** (pip path)             | **YES** — same XDE API; you write the OCAF walk                                        | Active (7.9.3.x)     | LGPL-3.0  | OCCT C++; **pip wheels** — use `cadquery-ocp-novtk` for slim headless |
| FreeCAD-as-a-library                          | YES (highest-level tree API)                                                           | Active               | LGPL-2.1+ | Whole CAD app — validation oracle / last resort only                  |
| ~~steputils / gmsh / ifcopenshell / trimesh~~ | **NO** (DOM-only / mesh-flatten / wrong schema)                                        | —                    | —         | rejected for assembly                                                 |

**Recommendation:** OCCT XDE via `cadquery-ocp-novtk` (pip/Docker-friendly) or `pythonocc-core` (has the
ready helper, conda). **VERIFY:** AP203 often has no part names (AP214/AP242 do — confirm what
Onshape/SolidWorks/Fusion emit); instance-name vs product-name identity (`GetReferredShape()`); compose
transforms down ≥3-level assemblies; and package the OCCT native stack in a real Docker build test.

### 6.2 STL — geometry only

| Candidate                 | Extracts                                                                                       | Assembly?                           | Maturity           | License / weight             |
| ------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------- | ------------------ | ---------------------------- |
| **trimesh** (recommended) | triangles, AABB/oriented bbox, volume, mass props, watertight, `mesh.split()` connected bodies | **NO** (geometric split ≠ identity) | Active (4.x, 2026) | **MIT**, numpy-only hard dep |
| numpy-stl                 | triangles + basic stats                                                                        | NO                                  | Active             | BSD-3, numpy-only            |
| open3d                    | mesh + clustering                                                                              | NO                                  | Active             | heavy C++/CUDA — overkill    |

**Recommendation:** `trimesh` for the geometry summary. **VERIFY:** trimesh multi-body ASCII STL parsing is
buggy — don't rely on it beyond geometry.

### 6.3 Electrical netlist

| Candidate                                         | Handles netlist?     | License | Deps                          |
| ------------------------------------------------- | -------------------- | ------- | ----------------------------- |
| **stdlib `xml.etree`** on KiCad XML (recommended) | YES                  | PSF     | none                          |
| **kinparse** (KiCad S-expr `.net`)                | YES                  | **MIT** | pyparsing                     |
| stdlib `json` + adapter (tscircuit/atopile JSON)  | YES                  | PSF     | none                          |
| ~~kiutils~~                                       | **NO netlist model** | GPLv3   | avoid (wrong tool + copyleft) |
| Altium Protel: stdlib state machine (~40 lines)   | YES                  | —       | none                          |

**Recommendation:** request the **KiCad XML** export and parse with the stdlib (zero-dep, schema-stable
v5–v10); `kinparse` only if stuck on the default `.net`. **VERIFY:** `kinparse` advertises v5–v9 — confirm
KiCad 10 `.net` support (or lean on XML); confirm which format the pipeline actually receives; Altium MPN gap.

### 6.4 DWG — DEFERRED (research retained for when it is revived)

No mature pure-Python DWG reader; every path is **convert-first, then-parse**.

| Path                                                               | What / license                                                                                                                           | Server viability                                                                                     |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **ODA File Converter (DWG→DXF) → ezdxf** (recommended parse layer) | ezdxf **MIT**; extracts layers/blocks/INSERT/XREF/entities from DXF                                                                      | ezdxf trivial; converter is a **Qt GUI app → needs `xvfb`**; subprocess arg-list only (CLAUDE.md §7) |
| **ODA File Converter** licensing                                   | **Free for NON-COMMERCIAL use ONLY** — a paid SaaS needs **ODA membership** (~$7.5k first yr / $4.5k renewal, Pro tier "SaaS permitted") | the single most likely license trap                                                                  |
| **LibreDWG `dwg2dxf`**                                             | **GPLv3** copyleft (legal review); Python bindings are beta/leaky — use only as an arm's-length CLI                                      | risky for a proprietary SaaS                                                                         |
| **APS (Autodesk) Model Derivative** cloud convert                  | per-file cost; **ships customer DWGs to Autodesk's cloud**                                                                               | clean ops but a CLAUDE.md §7 data-governance decision                                                |

**Status: DEFERRED to a later tier (founder decision, W0-08).** The research below stands for when DWG is
revived. **Recommendation when revived:** DWG→DXF (ODA File Converter under `xvfb`) → ezdxf, **contingent on
a human/legal answer to the ODA-membership question first** (the free converter is non-commercial-only). DWG
is the highest-risk item in the stack — this deprioritization avoids paying ~$4.5k/yr + ops burden for a
format robotics teams rarely use (they lean Onshape/STEP/KiCad).

### 6.5 SPICE

| Candidate                                    | Extracts topology?                                                                          | License                  | Deps                                                     |
| -------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------- |
| **spicelib** (recommended)                   | YES — `get_components()`, `get_component_nodes()` (element→node), values, params, `.subckt` | **GPLv3** (legal review) | numpy/scipy/matplotlib; **no simulator needed to parse** |
| **dan-fritchman/Netlist** (BSD escape hatch) | YES — structural AST, multi-dialect                                                         | **BSD-3**                | pure-Python; no releases — pin a commit                  |
| ~~PySpice~~                                  | partial parser (sim-wrapper)                                                                | GPLv3                    | requires ngspice installed; inactive                     |
| hand-parse (fallback for odd dialects)       | YES (line-based grammar)                                                                    | n/a                      | none                                                     |

**Recommendation:** `spicelib` primary, hand-parse odd dialects. **VERIFY:** `spicelib` is **GPLv3** —
clear the SaaS-ingest copyleft question with a human (ingest generally doesn't trigger distribution, but
it's a legal call; `dan-fritchman/Netlist` BSD is the drop-in if GPL is rejected); confirm
`get_component_nodes()` resolves hierarchical/subckt nodes on a real deck.

### 6.6 Licensing — a cross-cutting decision (flag for founders/legal)

The strong parsers span three license classes; several are copyleft. **This must be reviewed by a human,
not decided by an agent.**

- **Permissive (safe for a proprietary SaaS):** `trimesh` (MIT), `numpy-stl` (BSD), `ezdxf` (MIT),
  `kinparse` (MIT), `dan-fritchman/Netlist` (BSD), stdlib.
- **LGPL (dynamic-linking OK; matters only if you bundle/modify the C++):** OCCT / `pythonocc-core` /
  `cadquery-ocp` (STEP).
- **GPLv3 (copyleft — legal sign-off required):** `spicelib`, `PySpice`, `kiutils`, LibreDWG. SaaS ingestion
  generally does not trigger distribution, **but neither an agent nor an engineer should make that call.**
  BSD/MIT alternatives exist for most (noted above).
- **Commercial/EULA-gated:** **ODA File Converter is non-commercial-only** (paid ODA membership for SaaS);
  ODA Drawings SDK is subscription; APS is per-use cloud.

---

## 7. Findings — two human-owned graph-model gaps this strategy surfaces

Defining what CAD/EDA connectors EMIT surfaces two gaps in the graph model. Both are human-owned,
migration-bearing `models.py`/contract changes (ADR-027/W0-05 territory) — this doc is where they were
discovered; it does not make the change.

**7a — `RelationType` enum is missing mechanical/connectivity values.** The current enum
(`references`, `soldered_to`, `mounted_on`, `same_as`) cannot express the assembly/connectivity relations
these formats yield:

- **Mechanical (STEP):** the assembly tree needs a **part-of-assembly** edge (e.g. `part_of`) and, once
  inferred, a **`mates_with`** edge — neither exists. Only `mounted_on` is available today.
- **Electrical (netlist/SPICE):** net connectivity has no generic **`connected_to`/`net`** value; the
  closest is `soldered_to`, which over-specifies.
- CLAUDE.md §1's conceptual relation vocabulary already lists `connected_to`, `mates_with`, `depends_on`,
  `deployed_on` — the enum simply hasn't been extended to match.

- **§7a (RelationType too small for mechanical/connectivity):** resolved. `relation_type` is a free
  string, so `part_of`, `mates_with`, `connected_to`/`net`, etc. are expressible without extending
  an enum. You may keep §7a as historical context or mark it "resolved — SOLUSDEV-72 Decision A".
- **§7b (RelationOut carries no metadata channel):** NOT resolved here. `RelationOut` still has no
  `attrs` field; adding it is part of the connector-contract reconciliation (Decision B), not the
  graph-store unification. Leave §7b open.

**7b — `RelationOut` (W0-05) carries NO metadata channel.** `RelationOut` has exactly four fields
(`src_source_id`, `dst_source_id`, `relation_type`, `domain_pair`) with `extra="forbid"` — **no `attrs`**
(unlike `EntityOut`). So a relation cannot carry the net name, the specific pins, a confidence, or the
precise sub-kind. This blocks the natural §7a workaround (there is nowhere on a relation to "carry the
precise kind") AND full electrical net connectivity (net name + pin numbers have no home on a pairwise
edge).

The §7b finding ("`RelationOut` carries NO metadata channel") is **resolved by Decision B**.
`RelationOut` now has a `properties: dict` channel (the shipped connector contract:
`from_key, to_key, type, properties`), so a relation CAN carry the net name, pins, sub-kind, etc.
The runtime persists it to `graph_edge.attrs`. Update §7b to:

> **7b — resolved (SOLUSDEV-72 Decision B).** `RelationOut` carries a `properties` metadata
> channel (persisted to `graph_edge.attrs`); electrical net name + pins have a home on the edge.
> `domain_pair` is derived by the runtime from the endpoints' domains at write time.

**Recommendation (flag for founders — decide before CAD/EDA ingestion lands):**

1. Extend `RelationType` (7a) with `part_of` / `mates_with` / `connected_to` (a `models.py` enum +
   migration, human-owned).
2. Resolve the relation-metadata gap (7b) by EITHER adding a `RelationOut.attrs` dict (mirroring
   `EntityOut.attrs`, likely with a matching `graph_edge.attrs` — which already exists on the ORM) OR
   modeling the electrical **net** as its own entity so pin/net data lives in entity `attrs`.

Until both are decided, connectors map to the nearest existing `relation_type`, keep any richer sub-kind on
the **entity** side (`EntityOut.attrs`, which DOES exist), and net connectivity is approximated as pairwise
component→component edges without per-net/pin detail.

### Edit 2 — add a `design_export` surfacing row (§5)

Add to the §5 kind list / mapping: the code-host connector already emits `design_export` as a
first-class `graph_entity.kind` (committed CAD/EDA exports — Gerber/STEP/netlist/SPICE — detected
in a repo tree), alongside `code_repo`, `code_module`, `code_file`. Since `kind` is a free string
(Decision A), these are valid directly; document `design_export` explicitly so the strategy isn't
silent about it.

### Edit 3 — align the identity-linchpin wording

Any text saying `source_id == external_ref` should read: the connector's **`EntityOut.source_key`**
is persisted to **`graph_entity.external_ref`** and equals the fingerprint's
**`SourceRef.external_ref`** (`source_key` ≡ `external_ref`, post-Decisions A/B). The public API
preserves the legacy wire keys via serializers (`type←kind`, `source_key←external_ref`,
`properties←attrs`).

---

## 8. Open risks / verify-before-pinning summary

- **DWG is DEFERRED to a later tier (founder decision, W0-08)** — highest risk (no native reader; external
  converter/SDK/cloud on the critical path; headless `xvfb` friction; a licensing minefield — ODA
  non-commercial trap, LibreDWG GPL). When revived, validate the end-to-end path AND get the ODA-membership
  license answered by a human before any DWG work.
- **STL has no assembly structure** — assembly/part-identity/relationships come from STEP; STL is geometry
  only. Don't design assembly extraction against STL.
- **STEP gives placements, not mates** — `mates_with` must be inferred from coincident geometry; AP203 may
  lack part names. Validate on real robotics exports.
- **Netlist ≠ JSON** — KiCad's parseable target is XML (or S-expr `.net`), not a JSON netlist; pin the
  concrete producer before writing any JSON-netlist schema.
- **Live MCP acquisition (§2.1) degrades, never blocks** — companion offline / tool closed /
  call failed → committed-export fallback with a logged degradation. Export determinism is NOT
  assumed: the same design may not export byte-identical files across tool versions, so identity
  rests on content-derived `source_key`s (§2.1 invariant 2), never on file hashes.
- **netlist ↔ SPICE reconciliation** — netlist primary for identity/footprint; SPICE adds sim params +
  corroborates topology; join on refdes; **emit a mismatch on disagreement** rather than silently merging.
- **Licensing (§6.6)** and the **`RelationType` enum gap (§7)** both need human decisions before the
  connectors that depend on this doc are built.

---

**Cross-references:** ADR-030 (`DECISIONS.md` — parse committed Git exports v1), W0-05 connector interface
(`docs/contracts/connector-interface.md`, `packages/api/src/solus_api/connectors/` — `EntityOut`/
`RelationOut`, intra-source, `source_id == external_ref`), W0-06 fingerprint
(`docs/contracts/fingerprint-output.md` — `modality_hints` feed the matcher), ADR-027 + `models.py`
(`EntityKind`/`RelationType`/`Domain`, `domain_pair`). Downstream: each design-artifact connector ticket
implements a ROW above and the ONE shared CAD parser (§3). Sibling contracts: `connector-interface.md`,
`fingerprint-output.md`, `agent-tool.md`, `sol-interface.md`, `model-orchestration.md`. MCP-04
additions: ADR-031 (fork–harden–own hosting model) + `integrations/mcp/` (MCP-03 vendor layout,
allowlist, security gate); W0-04 `MCPTool` (`agent/tools/mcp_tool.py`, MCP-01); bridge channel
contract (`docs/contracts/bridge-protocol.md`).
