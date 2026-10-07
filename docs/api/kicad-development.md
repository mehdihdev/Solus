# KiCad schematic development — SOLUSDEV-261

Design for Phase 2 of the integration-check packet. This extends the owned
`integrations/mcp/kicad/solus/` overlay through the existing companion and action
gate; it adds no HTTP route and no direct cloud filesystem access. Implementation
is authorized under the user's explicit Phase 2 build requirements and subsequent
full permission to complete the integrations. Root governance, `integrations/mcp/CLAUDE.md`,
`docs/architecture/local-folders.md`, `docs/contracts/bridge-protocol.md`, and
`docs/contracts/action-gate.md` govern this plan. Consult the installed
`kicad-parsing` skill before implementing.

## Installed evidence and launch posture

Read-only probes on 2026-09-12 found system Flatpak `org.kicad.KiCad`, aarch64,
version 10.0.6. There is no `kicad-cli` on the host PATH. This command succeeds:

```text
/usr/bin/flatpak run --command=kicad-cli org.kicad.KiCad version
```

`sch erc --help` advertises `--format json`, `--units mm`, `--severity-all`,
`--exit-code-violations`, and `--output`. Existing detection would miss this
installation; absence on host PATH must not be presented as KiCad unavailable.
Use an owned executable adapter, pinned through the existing `KICAD_CLI_PATH`
launch configuration. The adapter dispatches only the overlay's fixed supported
CLI argument shapes through `/usr/bin/flatpak`; no shell command string, caller
executable, arbitrary application ID, install, or Flatpak override. Probe and pin
this once at startup, retain native CLI support. Bind workspace paths to the same
installed application's visible home filesystem; inaccessible paths are an
explicit unavailable operation, never an invented successful check.

The separately installed `org.kicad.KiCad.Library.Symbols` extension contains
`files/symbols/Device.kicad_sym`, `Connector_Generic.kicad_sym`, and
`MCU_Module.kicad_sym`. Resolve its trusted location with fixed argv
`/usr/bin/flatpak info --show-location org.kicad.KiCad.Library.Symbols`; do not
hardcode this machine's deployment hash or search arbitrary caller directories.
Confirmed symbols: `Device:R`, `Device:R_Variable`,
`Connector_Generic:Conn_01x02`, `Connector_Generic:Conn_01x06`, and
`MCU_Module:Arduino_UNO_R3`. `Device:R` has passive pins 1 and 2, local positions
(0, 3.81) and (0, -3.81) mm. These are library evidence, not a universal placement
rule. Resolve every actual symbol and pin at runtime. Flatpak metadata declares
its library extension mount; the host reader uses the resolved extension files.
Runtime data is read from the installed library, not copied into repository
fixtures. No KiCad GPL implementation code is imported into the owned overlay.

## Common schemas and limits

All tools reject unknown input fields. No input accepts S-expressions, Python,
raw CLI options, library file paths, arbitrary UUIDs, raw document contents, or
footprint names. Paths are workspace-relative `.kicad_sch` paths, at most 512
characters; reject absolute paths, NUL, empty/dot/dot-dot segments, and symlinks.
Check the workspace and every parent component again at commit. Never follow a
path outside the active, source-bound companion workspace.

- `Point`: `{x_mm:number,y_mm:number}`; finite numbers, each 0..1000, maximum four
  decimal places. Actual pin-derived coordinates may retain more exact internal
  precision. Reject ambiguous near-coincidence rather than snapping silently.
- `Pin`: `{reference:string,pin_number:string}`; reference `[A-Za-z][A-Za-z0-9_]{0,31}`,
  pin number nonempty printable text up to 32 characters. Resolve a unique top-level
  instance and a unique physical pin in its active unit; never assume pin 1 by name.
- `Anchor`: exactly one of `{pin:Pin}` or `{wire_uuid:string,endpoint:0|1}`. UUIDs
  here select a read-back existing wire; validate canonical UUID syntax and exact
  uniqueness. No freely authored coordinate can masquerade as an electrical pin.
- `Fingerprint`: full SHA-256 represented as four 16-hex chunks joined by `:`.
  This preserves the complete digest through existing ingress redaction; do not
  weaken redaction or use an abbreviated checksum as a stale-write guard.
- Existing schematic max 8 MiB; parser retains 200,000-token/200-depth bounds.
  Library file max 32 MiB, streaming bounded symbol extraction; selected definition
  plus inheritance closure max 512 KiB/20,000 tokens/32 ancestors. Refuse cycles.
- Per mutation at most one symbol, 32 wire segments, or one label/no-connect.
  Input JSON max 16 KiB. Returned preview max 40 rows, each field at most 400 chars;
  planned operation must fail explicitly if the complete human review cannot fit.
  Never silently truncate a plan or expose the whole embedded symbol definition.
- Every mutation accepts `dry_run:boolean=false` and
  `expected_fingerprint:Fingerprint` (required for existing-file changes; create
  instead requires `expected_absent:true`). A dry run performs reads and builds a
  deterministic plan only. It does not write caches, files, or artifacts.

Use exact stored args on approval. Both fresh preview and execution verify the
expected fingerprint. The cloud's Solus-owned `requires_complete_preview` policy
requires a complete dry-run result both before parking and before execution.
Failed, empty, malformed or oversized plans cannot fall back to argument-only
approval. A previously parked argument-only card also fails the new gate.

## Tool surface

Names below are composed cloud names; fork registration uses the suffix only.
Every read response is structured untrusted data, never executable instructions.

### `kicad.get_symbol_definition` — read

Input: `{library_id:string}` with exactly `Library:Symbol`, each identifier
1..128 printable characters excluding separators `/`, `\\`, `:`, NUL and control
characters. Resolve only a discovered trusted installed library. No implicit
remote download and no fabricated fallback symbol.

Output: `{library_id,library_fingerprint,units:[{unit,pins:[{number,name,
electrical_type,x_mm,y_mm,angle}]}],default_reference,default_value,footprint}`.
Coordinates are symbol-local KiCad coordinates. Multi-unit and inherited symbols
are discovered honestly; the first placement slice supports unit 1 of a single-unit
symbol only. Unknown unit/inheritance shapes refuse placement. Do not discard an
unsupported parent and create a visually plausible but electrically wrong symbol.

### `kicad.get_schematic_geometry` — read

Input: `{schematic_path,reference?:string}`. Optional exact reference filter keeps
large boards within tool-result bounds; missing reference returns `not_found`.
Output: `{schematic_path,fingerprint,sheet_uuid,symbols:[{reference,library_id,
unit,x_mm,y_mm,rotation_deg,pins:[{number,name,electrical_type,x_mm,y_mm}]}],
wires:[{uuid,start:Point,end:Point}],labels:[{name,at:Point}]}`. Filtered reads include
only wires/labels touching the selected instance's pins. A bounded result that
cannot fit asks for a reference filter; it must not claim to be complete.

Pin positions use the actual embedded definition, placement, unit and orientation;
quarter-turn transforms and KiCad's symbol-versus-sheet Y convention are covered
by CLI netlist tests. Existing mirrored placements must be supported accurately or
explicitly refused as unsupported before wiring. Never guess a coordinate from a
symbol's bounding box. Existing netlist reads remain the connectivity authority.

### `kicad.create_schematic` — confirmation required

Input: `{schematic_path,title:string,expected_absent:true,dry_run?:boolean}`.
Title maximum 120 characters. Creates one standalone A4 root schematic, not a
hierarchical child silently detached from its parent. Its parent directory must
already exist and its destination must not exist. No overwrite option.

Construct a minimal valid root with a supported format version, owned generator,
sheet UUID, title, empty `lib_symbols` and root `sheet_instances`. Version 20250114
is present in this installation's shipped schematics; the generated minimum must
be accepted by the actual CLI before being declared supported. Do not clone a
demo or the committed Solus sample. A `.kicad_pro` is not required to open a root
schematic; project settings creation is a separate file action if needed.

### `kicad.add_symbol` — confirmation required

Input: `{schematic_path,expected_fingerprint,library_id,library_fingerprint,
reference,value:string,at:Point,rotation_deg:0|90|180|270,dry_run?:boolean}`.
`value` maximum 120 chars, strictly escaped as a KiCad string. Resolve a real
single-unit definition and its inheritance closure; selected library hash must
still match. Reference must be unique. Copy the real definition into
`lib_symbols` once, then append one properly annotated instance with its actual
pins, UUIDs, unit and sheet/project instance path. Existing embedded definition
with the same library ID but different contents is a refusal, not replacement.

Preserve installed-library footprint property if present; no guessed package.
Generic connector fallback uses its genuine library definition and pin numbers.
Real board pin/function names are expressed by explicit net labels and the review
summary; do not rename a library's pins without an independently designed tool.
Preview names symbol, reference/value, sheet placement, resolved pins and any
library footprint. A passive across two nets is this operation plus independently
previewed wires/labels; there is no unsafe compound `add_passive` shortcut.

### `kicad.add_wire` — confirmation required

Input: `{schematic_path,expected_fingerprint,start:Anchor,end:Anchor,
via?:Point[],dry_run?:boolean}`; max 31 interior points and 32 resulting segments.
Pin endpoints are resolved from live geometry, never caller-supplied pin XY.
Each segment must be nonzero and orthogonal; no autorouter that invents bends.
If no `via`, a non-aligned pair is refused with resolved endpoints for replanning.

First slice connects pins or an existing wire endpoint. An intermediate crossing,
T connection, pin collision, duplicate wire, or accidental overlap is refused;
there is no implicit junction and no silent short to another net. Joining a
mid-wire point needs a later explicit split/junction design. Preview includes both
resolved references/pin numbers/names and every segment's exact coordinates.

### `kicad.add_net_label` — confirmation required

Input: `{schematic_path,expected_fingerprint,name:string,anchor:Anchor,
rotation_deg:0|90|180|270,dry_run?:boolean}`. Name 1..80 printable characters,
excluding control characters; retain case, escape quotes/backslashes correctly.
Creates a local label exactly on the resolved pin or wire endpoint. Does not
invent global/hierarchical electrical connectivity. Refuse conflicting label
names at the same anchor. Repeated same label is an explicit no-op.
Preview shows label name, exact anchor and affected pin/wire identity. Reusing
one name at separate anchors intentionally joins those nets and must say so.

### `kicad.mark_no_connect` — confirmation required, necessary ERC companion

Input: `{schematic_path,expected_fingerprint,pin:Pin,dry_run?:boolean}`. Creates one
no-connect marker only at an actual unused pin. Refuse a pin already wired or
labeled; an existing marker is a no-op. Preview explicitly says this pin is
intentionally unused. This small additional operation is necessary to finish a
real Uno schematic with unused pins without suppressing ERC findings or wiring
unused inputs to fabricated nets. It is included in the proposed expansion below.

### `kicad.check_erc` — read/export

Input: `{schematic_path}`. Fixed native/Flatpak-adapted argv:
`sch erc --format json --units mm --severity-all --exit-code-violations --output
<owned-confined-temp-report> <confined-input>`; timeout 30 s. No caller output path,
define-var, suppression, or project-settings edits. Parse the bounded JSON report,
not human stdout; validate severity, description and item locations.

Output: `{checked:boolean,passed:boolean|null,fingerprint,errors:int|null,
warnings:int|null,violations:[{severity,description,items:[{description,x_mm,y_mm}]}],
degraded:boolean,reason:string|null}`. Distinguish a valid violations report from
process failure. `passed:true` only with a complete, valid report containing zero
errors AND zero warnings; exclusions are shown separately and never manufactured.
Unavailable/failing CLI returns `checked:false,passed:null,degraded:true` with an
honest reason. The existing synthesized netlist fallback is not an ERC engine.
Large reports use the existing ArtifactRef seam; reported totals cover the whole
report and an inline subset is explicitly marked, never silently truncated.

ERC runs on a private schematic snapshot using CLI defaults. It does not apply
external project-specific ERC settings. The result reports ignored checks and
must not be described as validation against a project's custom rule configuration.

## Planning, commit and read-back invariants

Common successful mutation result:
`{changed:boolean,schematic_path,before_fingerprint:null|Fingerprint,
after_fingerprint:Fingerprint,created:[{kind,uuid,reference?:string}],dry_run:boolean,
preview:[{label,before,after}]}`. The owned wrapper converts stable refusals into
MCP `isError`, which the companion maps to a failed ToolResult with no successful
fingerprint. Confinement refusals use the same error path. Examples:
`path_escapes_workspace`, `file_too_large`, `stale_plan`, `already_exists`,
`library_unavailable`, `unsupported_symbol`, `ambiguous_target`, `invalid_geometry`,
`guard_failed`, `cli_unavailable`. No content or host path in exception text.

Open-in-KiCad conflict: `stale_plan` is also the refusal when the schematic is
open in the KiCad GUI. A write is refused if the file's bytes differ from the
fingerprint Solus read (the user saved from KiCad since), or if KiCad's
`~<name>.lck` / `<name>.lck` editor lock exists beside it. Either way nothing
is written and the file is untouched; the user is told to save/close in KiCad
and re-read. Pinned by `tests/test_write_tool_open_in_kicad.py`.

Planner output fingerprints original bytes, exact proposed bytes, arguments,
resolved entities, selected library bytes and generated UUIDs. UUIDs derive from a
stable namespaced hash of workspace-relative file path, original fingerprint and
canonical operation, so fresh preview and execution are identical; collisions
refuse. A repeated create uses the same identity but refuses an existing target.

Structural writes extend the owned byte-offset parser: identify exact insertion
spans in the root and `lib_symbols`; splice generated nodes only at those spans.
A structural guard proves original tokens/bytes outside those insertions are
unchanged, insertion nodes exactly match the plan, and the result reparses with
unique UUIDs/references. This is separate from the existing one-string F10 guard;
do not loosen that guard or use a library load/save round-trip.

Commit under a per-file companion lock, re-read and compare complete original
bytes/fingerprint immediately before commit, then same-directory temp + fsync and
atomic replacement. A newly created file uses an atomic no-clobber publication,
not check-then-`os.replace`. Use directory-relative no-follow operations to prevent
symlink-swap escape. Refuse KiCad lock files/active editor ownership; do not claim
CAS protects against a non-cooperating external editor between check and rename.
No file mutation is reported successful before bytes are read back and match the
planned digest. A post-commit verification failure is nonretryable and says the
write outcome is uncertain, never claims nothing changed.

Existing companion change hints trigger KiCad netlist export and graph sync.
Verify the resulting nets and pin memberships after each operation. A local folder
project node alone is not evidence of schematic topology ingestion.

## Proposed allowlist and preview dispatch expansion

The user explicitly required building missing symbol, wire, label, new-sheet and
ERC capabilities, then granted full permission to complete the integrations and
requested continuation into these phases. That direct authorization covers the
eight bounded entries below and the no-connect markers necessary for honest ERC;
it governs the lower-level allowlist restriction in `integrations/mcp/CLAUDE.md`
rule 2. No existing confirmation flag is weakened and no provenance sign-off is
authored by an agent. These schemas are frozen for implementation.

| New suffix             | requires_confirmation | Purpose                                               |
| ---------------------- | --------------------- | ----------------------------------------------------- |
| get_symbol_definition  | false                 | Read a real installed symbol and pins                 |
| get_schematic_geometry | false                 | Read actual instance coordinates and fingerprint      |
| create_schematic       | true                  | Create a new schematic without overwrite              |
| add_symbol             | true                  | Add one actual library symbol                         |
| add_wire               | true                  | Connect explicit, verified endpoints                  |
| add_net_label          | true                  | Name an explicit electrical net                       |
| mark_no_connect        | true                  | Mark one intentionally unused pin                     |
| check_erc              | false                 | Read-only electrical check and owned temporary report |

New mutations use the existing generic dry-run preview seam, with these exact
composed names added to its owned support registry; no caller or advertised schema
can opt arbitrary tools into pre-approval execution. Every preview row includes
both original and planned full fingerprints alongside readable changes. All other
allowlist flags stay unchanged. Check ERC's bridge timeout exceeds its 30 s local
process bound (proposed 40 s). Update registration/trimming tests and inventory cap
tests; no upstream tool becomes incidentally exposed.

## Execution and ownership plan

Do not parallelize until shared helpers and schemas have passed tests.

1. **Serial foundation**: own new `solus/development/models.py`, `library.py`,
   `geometry.py`, `plan.py`, `structural.py`, `commit.py` and matching
   `tests/test_development_{models,library,geometry,plan,structural,commit}.py`.
   Own CLI adapter/detection and their tests in this same serial step. Establish
   deterministic plans, boundaries, flat/inherited symbol support and atomic guards.
2. **Parallel candidate A**: only new `solus/development/schematic.py`, `symbol.py`,
   `tests/test_development_schematic.py`, `test_development_symbol.py`.
   Implement create and placement against frozen foundation interfaces.
3. **Parallel candidate B**: only new `solus/development/wiring.py`,
   `tests/test_development_wiring.py`. Implement wire, label and no-connect.
4. **Parallel candidate C**: only new `solus/development/erc.py`,
   `tests/test_development_erc.py`. Implement bounded fixed-argv ERC.
5. **Serial integration**: parent owns `solus/development/registration.py`, existing
   registration/roster, allowlist, bridge dry-run registration, generic failure
   mapping and respective tests. Nobody in A/B/C touches those files. Parent writes
   actual `.Codex/state/ownership/*.list` manifests after freezing interfaces.
6. **Verification**: malformed syntax, UUID/reference collisions, escaped strings,
   byte-preservation, stale files/libraries, path races, fake dry runs, repeated
   approval, transformed pin positions, implicit-short refusal, quota/frame caps,
   timeouts and incomplete ERC reports. Then installed-CLI scratch generation,
   export and electrical connectivity checks; graph round-trip and UI review last.

## Deterministic new-project baseline

Create a new workspace-contained `solus-integration-check/` directory, not the
committed fixture and not an existing customer sheet. Author the minimal root
from the supported format grammar with deterministic UUIDs and title. If a project
file is needed, author a minimal fresh `.kicad_pro` through a separately reviewed
file-creation action; do not copy KiCad demo contents. Validate fresh output using
the installed CLI netlist export and ERC, then open it with the existing local
`open_in_tool` path. No claim of a working project before those checks.

Use real `Arduino_UNO_R3` and `Device:R` with 10 kΩ value. Resolve an actual driver
and FSR library symbol if available; otherwise use a real generic connector with
pin-to-net labels grounded in graph/datasheet evidence. The packet does not itself
establish the XIAO driver variant or its supply/UART pinout; unresolved board facts
are evidence gaps, not permission to invent pins. Wire the proven FSR divider to
A0 and the proven TX/RX/power/ground mapping, mark only intentionally unused pins,
and fix actual ERC findings. A clean resistor/connector smoke test proves tooling;
it does not prove the full requested three-device wiring diagram or rail-current
analysis. Rail totals require known per-part current definitions and explicit
missing-data reporting, never guessed ratings.

## Existing source binding — SOLUSDEV-261 UI completion

An already-created KiCad source can bind its live export using the existing
`PATCH /api/v1/projects/{project_id}/sources/{source_id}` with
`{"config":{"project_path":"relative/design.kicad_pro"}}`. This is the existing
MEMBER-authorized source configuration route, not a new file access endpoint.
The renderer sends no machine-absolute workspace path and writes no native registry.
KiCad now advertises the already-supported `project_path` configuration capability
alongside `export` and `board`, enabling the generic source-row project-link form.
The native fork validates the selected relative project path against its bound
workspace at acquisition time. Existing committed exports remain the fallback.

A successful PATCH proves configuration storage only. Authenticated companion
change hints re-export connected KiCad sources in the API process and persist the
normal connector graph. A local-folder detected project node, static XML import,
or a manual sync on an acquirer-less ARQ worker is not live-refresh evidence.

## Existing symbol property edits — complete preview binding

`set_symbol_property` adds `expected_fingerprint` (the complete digest observed by
`get_schematic_geometry`) and `dry_run:false`. Missing or stale fingerprints refuse
before writing, including legacy requests. The tool edits exactly one existing,
uniquely identified property; it retains Reference, Footprint and custom property
support. Central risk policy may keep structural identity/footprint edits manual.
A dry run returns complete before/after property text, relative schematic path and
full before/after file fingerprints without modifying the schematic. Each preview
value is bounded to 400 characters; oversized content refuses instead of truncating.

Execution repeats the same bounded plan, retains the byte-splice token guard,
then uses the existing descriptor-confined schematic publisher with editor-lock,
last-moment source comparison and actual byte readback. No parser library rewrites
the file. Publication errors or a changed parent namespace after publication return
`mutation_unverified`, never a claim that no edit occurred. Independent external
writers are not an atomic compare-and-swap participant; comparison and verified
readback detect observed races without promising future immutability.

## Graph rail-current report — SOLUSDEV-261

`analyze_rail_current` is a read-only SOL tool over the existing project-scoped
`SolSystems.get_graph_context` boundary, not a native file parser or new HTTP route.
Input is exactly `{rail_entity_id: UUID}`; project scope comes from the authenticated
factory closure. It reads a bounded degree-two graph around an electrical `net`
entity, including direct `connected_to` membership and explicit `powers` loads.
No foreign-project or missing entity is interpreted as an empty safe rail.

Each connected component is counted once, even with several pins/duplicate edges.
A finite nonnegative `current_draw_a` is counted only when explicitly attributed:
`current_rail` equals the selected net UUID (preferred) or its unique connected
net name, or an unambiguous `powers` relation names the selected rail as supplier.
An unqualified board-wide current, conflicting rail attribution, missing value,
bool, negative/nonfinite value or broken graph membership is unknown, not zero.
Optional `current_draw_source` is reported as graph-declared provenance, never
promoted to independently verified datasheet evidence. No current is guessed
from MPN, footprint, pin type, voltage label or an FSR's changing resistance.

The report includes the selected rail, observed member count, each bounded known
contribution and unknown reason, `known_subtotal_a`, nullable `total_current_a`,
`complete`, `truncated`, nullable declared `capacity_a` from the rail's explicit
`current_max_a`, and `capacity_status`. A known subtotal over an explicit capacity
is `over_capacity`; `within_declared_capacity` requires complete topology/data
and an explicit capacity; otherwise capacity status is `unknown`. This is a
budget of declared values, not measurement, peak/inrush prediction or proof of
physical safety. Empty/truncated graphs never produce a complete total. Oversized
member/name output is explicitly incomplete, never silently claimed exhaustive.
If the full report after ordinary redaction/ASCII/fence escaping exceeds the
64,000-character tool-result cap, return unavailable rather than a JSON prefix.
A nonrepresentable current sum is unknown, never infinity.

Pure analysis lives in `checkers/rail_current.py` and does not alter the existing
checker contract or its skip-unknown warning behavior. The tool lives in
`agent/tools/rail_current.py`; its factory accepts `(systems, project_id)` and
uses existing graph-budget/truncation and registry error/timeout boundaries.
The live Uno/FSR divider may have unknown currents/capacity; report those honestly.

### Authoritative bounded netlist reads

The existing `extract_project_netlist(project_path)` and
`analyze_schematic_connections(schematic_path)` read tools use the same confined,
verified snapshot and official `kicad-cli --format kicadxml` acquisition as export.
They do not report the legacy regex schematic parser as complete connectivity.
Their compact result retains all exported components and net-to-reference/pin
memberships, including generated singleton unconnected nets, with explicit native
provenance and completeness. Net names do not establish electrical ratings or
whether an unconnected pin is intentionally marked.

Malformed/ambiguous XML, DTD/entity declarations, unknown/duplicate references or
pin assignments, missing/failed CLI, and a complete result exceeding the existing
4,000-character model envelope bound produce explicit unavailable/invalid refusal.
No partial list is labeled complete. The existing export envelope and degraded
export behavior remain unchanged for connector acquisition; export XML may be too
large for a model message, so these bounded read tools are the topology evidence.
