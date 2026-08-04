---
name: kicad-parsing
description: Use this skill when parsing KiCad netlists (kicadxml), reading or splicing .kicad_sch S-expression files, invoking kicad-cli, or working with the committed KiCad sample fixtures. Captures the SOLUSDEV-100 domain knowledge — field encodings, DTD refusal, byte-offset splicing, headless degradation — so it is not re-derived (or gotten wrong) per ticket.
origin: Solus (SOLUSDEV-100)
---

# KiCad Parsing & Writing

Domain procedures stabilized by SOLUSDEV-100 (KiCad connector phase 1 + KiCad MCP fork
phase 2). Consult BEFORE improvising any KiCad file handling. The reference
implementations are law; this skill tells you where they are and why they are shaped
that way.

## When to Activate

- Parsing a KiCad netlist into the graph (any EDA connector work).
- Reading or MUTATING a `.kicad_sch` schematic file.
- Invoking `kicad-cli` from any Solus-owned code.
- Building or consuming KiCad test fixtures.

---

## 1. KiCad XML netlist parsing (`kicadxml`)

Reference: `packages/api/src/solus_api/connectors/kicad_netlist.py` (governing contract:
`docs/contracts/metadata-extraction.md` §5.2).

**Target format.** The v1 parse target is the **XML netlist**
(`kicad-cli sch export netlist --format kicadxml`) — the documented intermediate all other
netlist formats derive from, schema-stable v5–v10, stdlib-parseable. The default S-expr
`.net` is NOT parsed: refuse it with `ConnectorError("export_format_unsupported")` and a
message naming the re-export command (detect it cheaply: stripped text starts with
`(export`).

**The two custom-field encodings (both are live in the wild):**

- **v5:** `<comp><fields><field name="MPN">LM358DR</field></fields></comp>` — value in the
  element TEXT.
- **v6+:** `<comp><property name="MPN" value="LM358DR"/></comp>` — value in the `value`
  ATTRIBUTE, `property` a direct child of `comp` (no wrapper).

Merge both, **later (v6+) wins on a name collision**. The MPN is matched by alias after
lowercasing and stripping non-alphanumerics (`mpn`, `manufacturerpartnumber`,
`mfrpartnumber`, `mfrpn`, `mfrpart` — so "MPN", "Mfr. Part #", "Manufacturer_Part_Number"
all land) and is **popped out of properties** into `modality_hints.part_number`: identity
signals are the fingerprint's channel, not display properties. Other identity hints:
`schematic_symbol_name` from `<libsource part>`, `datasheet_ref` from `<datasheet>`.

**`~` means unset.** KiCad writes `"~"` for an empty value/datasheet — treat it (and `""`)
as absence, never as content.

**DTD refusal (security, CLAUDE.md §7).** stdlib `xml.etree` still expands INTERNAL
entities — a billion-laughs vector. A KiCad netlist never declares a DTD, so refuse
outright BEFORE parsing: if `"<!DOCTYPE"` or `"<!ENTITY"` appears anywhere in the text,
raise `ConnectorError("export_invalid")`. Do not try to "safely parse around" it.

**Scoped traversal (anti-smuggling).** Only read the documented positions — direct
`comp` children of `components`, direct `net` children of `nets`, direct `field`/`property`
children at their documented spots. Never a whole-subtree walk (`.iter()`/`.findall(".//")`):
adversarial content nested elsewhere in an untrusted export must have nowhere to land.

**Lenient WITHIN valid XML.** Structural unusability (malformed XML, wrong root, DTD,
S-expr) raises; a component without `ref`, a net without `name`, a node missing `ref`/`pin`
is SKIPPED and counted onto `Netlist.warnings` so one bad element never fails a sync and
partial parses stay visible.

**Graph mapping** (`connectors/eda.py`): components → `component` entities keyed by
refdes; nets → first-class `net:<NAME>` entities (never O(n²) pairwise edges);
connectivity → `connected_to` edges carrying the pins in `properties.pins`. Identity is
content-derived only (§2.1 invariant 2) — never from temp paths, artifact ids, or call ids.

---

## 2. S-expression handling (`.kicad_sch`)

Reference: `integrations/mcp/kicad/solus/write/` (sexpr.py, locator.py, guard.py,
escaping.py, atomic_write.py, set_symbol_property.py).

**The load-bearing finding (T2a, measured 2026-08-03):** library round-trips of
`.kicad_sch` are **NOT byte-stable**. `kicad_sch_api.Schematic.load(...).save_as(...,
preserve_format=True)` on the Solus fixture re-emits canonical multi-line KiCad style
(43,513 B / 655 lines → 65,603 B / 4,003 lines), reorders top-level elements, injects
format-version fields (`fields_autoplaced`, `show_name`, `embedded_fonts`, …), and
REPLACES embedded `lib_symbols` with definitions resolved from the machine's local KiCad
libraries when installed. This is pinned as a **strict xfail**
(`integrations/mcp/kicad/tests/test_vendor_sch_api.py::test_roundtrip_is_byte_identical_on_the_solus_fixture`)
— if it ever starts passing, the truth changed and the write design should be revisited.
Consequence: **never implement a schematic mutation as load→modify→save through a parsing
library.** A one-property edit must not rewrite (and silently reformat) a customer's
design file.

**The splice approach instead:**

1. **Tokenize with byte offsets** (`sexpr.py`): an owned tokenizer over the raw bytes where
   every token carries its exact `[start, end)` byte span. Grammar subset: parenthesized
   lists, bare atoms, double-quoted strings with backslash escaping of `"` and `\`.
   Deliberately NOT `sexpdata`/`kicad_sch_api` — those decode to Python values with no
   offset trail, leaving nothing to splice against.
2. **Locate** the one STRING token to change (`locator.py` — top-level symbol instances
   only, never inside `lib_symbols` definitions).
3. **Splice** the encoded new value into the located span only (`escaping.py` encodes
   strictly on write; decoding is lenient on read — an unrecognized escape is preserved
   literally so an unusual existing file never fails to parse).
4. **Guard before writing** (`guard.py`, F10): re-tokenize BOTH versions and refuse
   (`RefusalError`) unless (a) the raw byte diff is confined to the located span and
   (b) the flat token streams are identical except exactly ONE STRING token whose old/new
   decoded values match expectations. Defense in depth against locator bugs.
5. **Write atomically** (`atomic_write.py`): temp file in the SAME directory + fsync +
   `os.replace`. Never truncate-and-rewrite in place.

Also: workspace confinement is mandatory for every path a tool touches
(`solus/workspace.py` / `write/paths.py`) — resolve symlinks FIRST, then
`is_relative_to(root)`; refuse, never silently correct.

---

## 3. kicad-cli invocation posture

Reference: `integrations/mcp/kicad/solus/cli_detect.py` + `solus/netlist_export.py`;
launcher posture in `integrations/mcp/kicad/bin/launch`.

- **Never probe "common install paths"** (upstream `kicad_mcp.utils.kicad_cli` does — that
  is exactly the user-influenced path resolution CLAUDE.md §7 forbids). The CLI comes ONLY
  from a launcher-passed `KICAD_CLI_PATH` (must be an executable regular file) or
  `shutil.which` under the launcher's fixed `PATH=/usr/bin:/bin`.
- Detect ONCE per process (`functools.cache`) — availability is a launch-posture fact.
- Invoke with a **fixed argv list** (no shell, no interpolation), `capture_output=True`,
  and a timeout; output to a workspace-confined destination.
- **Headless degradation, never failure:** absent or failing CLI → synthesize the result
  from the KiCad-free schematic file parse and return `degraded: true` with one of the
  STABLE reason strings (`KICAD_CLI_UNAVAILABLE_REASON` / `KICAD_CLI_FAILED_REASON`).
  Headlessness is an expected environment, not an error: no exception, no non-zero exit.

---

## 4. Fixture conventions (`solus_sample`)

Reference: `integrations/mcp/kicad/tests/fixtures/` + `integrations/mcp/kicad/tests/paths.py`.

- **Exactly ONE copy on disk**: `integrations/mcp/kicad/tests/fixtures/solus_sample/`
  (`.kicad_pro`, `.kicad_sch`, `solus_sample.net.xml` ~13 KiB, and
  `solus_sample_large.net.xml` ~737 KiB / 1001 components — the ArtifactRef-path fixture,
  sized between the 512 KiB inline cap and the 1 MiB frame cap). Every consumer —
  including `packages/api/tests/fixtures/kicad_project.py` — resolves it through the
  repo-root-walk convention in `tests/paths.py` (first `.git` up from the consuming file;
  a `.git` FILE counts, so worktrees resolve; topmost `pyproject.toml` fallback for
  git-less checkouts). Never copy the fixture; never hardcode absolute paths.
- The large variant is **generated deterministically** by `gen_large_fixture.py` (no
  randomness, uuid5 namespace); BOTH the script and its output are committed, and
  `test_fixture_integrity.py` regenerates and asserts byte-equality — change the script →
  rerun it → commit both in the same commit.
- The component roster (refdes → MPN, e.g. `U1` → `STM32F030F4P6`) is pinned by
  `packages/api/tests/test_kicad_ingest_e2e.py`; keep additions realistic (real MPN
  `<property>` per component, named nodes per net) so the fixture parses warning-free.
- Fork tests that genuinely need `sexpdata` use the fork's private venv
  (`integrations/mcp/kicad/.venv`, materialized from `requirements.lock.txt`) and SKIP
  with a materialization hint when absent — never add fork dependencies to the uv
  workspace.
