# Fork security review — `kicad` @ tree `56f30452214d88aa6b84807d6df7a6e903c48e52` — `2026-08-03`

> Filled from `integrations/mcp/SECURITY_REVIEW.template.md` (SOLUSDEV-100 T1b draft review).
> Append-only: later reviews are appended below, never rewrite this one. SIGNATURES LIVE IN
> PROVENANCE.md AND REMAIN BLANK — filling them is a human-only act. Items that require the
> companion install environment or CI are dispositioned **PENDING(human/CI)** explicitly rather
> than ticked on faith.
>
> Scope of this review: upstream pinned SHA `98c9ea41cb393393a8bafd157a93e84431e00afb` plus the
> T1b Solus overlay (`solus/`, `bin/launch` argv change, `allowlist.yaml`). Exposed surface:
> the 6-tool read roster in `allowlist.yaml` (5 upstream + 1 Solus-authored `export_netlist`);
> `set_symbol_property` is allowlisted (confirmation-gated) but NOT implemented or registered
> until T2b.

## 1. Supply chain

- [x] `upstream/` matches the PROVENANCE-pinned state — evidence:
      `git rev-parse HEAD:integrations/mcp/kicad/upstream` → `56f30452214d88aa6b84807d6df7a6e903c48e52`,
      equal to the PROVENANCE "Vendored tree hash" (recomputed live by
      `tests/test_launch_entrypoint.py::test_provenance_tree_hash_matches_a_recompute_of_upstream`
      and `tests/test_overlay_tool_trimming.py::test_upstream_tree_hash_matches_provenance_after_overlay_work`
      on every run). The tree deviates from the verbatim import only by the PROVENANCE-logged rows
      (`.github/` exclusion; the ruff force-exclude deviation block in `upstream/pyproject.toml`).
- [x] No runtime fetch — evidence: `bin/launch` read in full (44 lines); token scan pinned by
      `test_launch_contains_no_network_or_installer_commands` (bans npx/uvx/pip install/uv/curl/wget/
      git clone/nc/ftp/rsync/ssh). The T1b entry `solus/server.py` read in full: imports + `FastMCP`
      construction + registration only; zero network primitives (see §2 egress grep).
- [x] Registry install hooks — evidence: upstream is a plain setuptools project;
      `upstream/pyproject.toml` + `MANIFEST.in` read: no `cmdclass`, no custom `setup.py` (none
      exists), no install hooks. The fork is never pip-installed anyway: the companion materializes
      `requirements.lock.txt` into a private venv and `bin/launch` runs sources in place.
- [x] Lockfile committed, complete, hash-pinned — evidence: `requirements.lock.txt` carries 565
      `--hash=sha256:` pins; shape enforced by
      `test_lockfile_exists_and_every_requirement_is_hash_pinned` and
      `test_lockfile_pins_the_upstream_runtime_dependencies` (mcp, fastmcp, pandas, pyyaml,
      defusedxml present). **PENDING(human/CI):** the offline `pip install --require-hashes
--no-index` reproduction in a network-disabled container (companion install-time follow-up).
- [ ] Dependency audit — **PENDING(human/CI):** `pip-audit` against `requirements.lock.txt` is
      the CI dependency-audit job (CLAUDE.md §7); not runnable in this network-restricted session.
      Every advisory found there must be dispositioned in an appended review section before ship.
- [x] Reproducibility — evidence: all versions exactly pinned with hashes (see lockfile test);
      two installs from the same tree cannot resolve different sets. Bit-identical artifacts are a
      template exclusion.

## 2. Least privilege

- [x] Runs as the invoking user — evidence:
      `grep -rn "sudo\|setuid\|seteuid\|runas" upstream/kicad_mcp upstream/main.py solus/ bin/`
      → **zero hits**.
- [x] Filesystem scope — evidence (tier-2 line-reads, §7): the overlay's only write path is
      `solus/netlist_export.py:139` (`destination.write_bytes`), confined by
      `solus/workspace.py::artifact_destination` (bare-filename check + resolved
      `is_relative_to(workspace)`); traversal refusal pinned by
      `test_overlay_env_allowlist.py::test_artifact_destination_refuses_traversal_attempts`
      (8 hostile shapes) and the artifact-inside-workspace assertion in
      `test_export_netlist_writes_a_workspace_artifact_above_the_inline_cap`.
      **Declared read scope beyond the workspace:** `list_projects` walks `KICAD_USER_DIR` +
      `KICAD_SEARCH_PATHS` (launcher-allowlisted knobs) and upstream defaults under `~`
      (`upstream/kicad_mcp/utils/kicad_utils.py::find_kicad_projects`, line-read), and the other
      read tools accept absolute project/schematic paths readable by the invoking user. This is the
      tools' documented function (read-only enumeration/parse); confinement of reads to the
      workspace is a possible future tightening, recorded here as accepted residual for v1.
- [x] Network egress: **none** — evidence:
      `grep -rEn "requests|urllib|http\.client|socket\.|fetch\(|axios|net\.connect|WebSocket"
upstream/kicad_mcp upstream/main.py solus/ bin/` → **zero hits**. No endpoint exemptions
      needed.
- [x] No `shell=True` / `os.system` — evidence:
      `grep -rn "shell=True\|os\.system\|os\.popen" upstream/kicad_mcp upstream/main.py solus/ bin/`
      → **zero hits**. Live subprocess sites (tier-1 line-read): `solus/netlist_export.py::_cli_export`
      — fixed argv list against the pinned CLI, 30 s timeout, failure → degrade (never raise).
      Upstream subprocess sites (`kicad_utils.open_kicad_project`, `export_tools`, `drc_impl/cli_drc`,
      `kicad_cli.py` version probes, `kicad_api_detection`) belong to tools the overlay never
      registers — dead in-process (§7).
- [x] `spec.args` fixed — evidence: `MCPServerSpec(name="kicad",
command="integrations/mcp/kicad/bin/launch")` (mcp_servers.py) passes no args;
      `test_launch_has_fixed_argv_with_no_argument_passthrough` bans `$@`/`$*` and pins the exec
      line `"$PYTHON" "$FORK_DIR/solus/server.py"`. Nothing model- or server-supplied reaches any
      argv: the only subprocess argv takes `cli` (pinned detection), `destination`
      (workspace-confined), `schematic` (path validated + discovered via `get_project_files`).

## 3. Sandbox posture

- [x] **Declared posture (all OSes the companion supports — macOS/Windows/Linux):** OS user
      permissions + `bin/launch` env scrub (`env -i` + the `solus/env_allowlist.py` declaration) +
      fixed `PATH=/usr/bin:/bin` + cwd pinned to `SOLUS_MCP_WORKSPACE` + fork-private interpreter +
      `sys.dont_write_bytecode` (vendored tree stays byte-pristine). No OS-level sandbox today.
      Assumed companion additions later: process supervision limits, and OS sandboxing when ADR-031's
      "revisit when" fires — file writes are already workspace-confined so a read-only-outside-
      workspace mount will not break the roster.
- [x] Functions under the strictest declared posture — evidence: the headless-degrade suite runs
      every export path with a scrubbed PATH (empty dir) and no `KICAD_CLI_PATH`: the roster
      operates fully (KiCad-free parse), returns `degraded: true`, exits zero
      (`tests/test_overlay_headless_degrade.py`, 10 tests). **PENDING(human/CI):** the
      deny-by-default container run with read-only mounts outside the workspace.
- [x] Nothing detects/disables sandboxing or self-modifies the install — evidence: tier-1 read
      of `bin/launch` + `solus/` (8 files, 100%); the §2/§4/§5 greps show no self-modification,
      no dynamic code, no writes outside the workspace helper.

## 4. Secret hygiene

- [x] Environment access confined to the written allowlist — evidence:
      `grep -rn "os\.environ\|getenv" upstream/kicad_mcp upstream/main.py solus/` hits reconciled:
      `config.py:62` KICAD_SEARCH_PATHS (allowlisted); `utils/kicad_cli.py:130` KICAD_CLI_PATH
      (allowlisted; module not imported by the overlay); `utils/drc_history.py:16` APPDATA (DRC
      tools not registered — dead); `utils/env.py` + `main.py` (see the shim row below —
      unreachable from the Solus entry); `solus/workspace.py:20` SOLUS_MCP_WORKSPACE and
      `solus/cli_detect.py:38` KICAD_CLI_PATH (both allowlisted). The script/declaration agreement
      is pinned by `test_launch_env_block_matches_the_solus_declaration` and
      `test_launch_scrubs_environment_to_the_declared_allowlist`; no secret-shaped names
      (`test_declaration_admits_no_secret_shaped_names`).
- [x] No credential logged — evidence: logging call sites in the exposed paths (project_tools,
      netlist_tools, bom_tools handlers — tier-2 line-read) log paths, counts, and tool names only.
      **T1a flag (b), shimmed:** `upstream/kicad_mcp/utils/env.py:63` logs env VALUES parsed from a
      dropped `.env` file (`logging.info(f"Setting os.environ['{key}'] = '{value}'")`). Its only
      caller is `upstream/main.py:38`, which `bin/launch` no longer execs — the Solus entry never
      imports `kicad_mcp.utils.env` (import-audit test) and never calls `load_dotenv`, so no `.env`
      is ever read and no env value is ever logged. Additionally the launcher's `env -i` scrub means
      a secret could only enter via an allowlisted name, and none is secret-shaped.
- [x] No telemetry/phone-home — evidence: the §2 egress grep is empty; nothing to strip.
- [x] No credential persistence — evidence: file-write grep over the roster paths
      (project/netlist/bom tools, netlist_parser, file_utils, solus/) → single hit,
      `solus/netlist_export.py:139` (netlist bytes, workspace-confined). `drc_history.py` writes
      JSON history under APPDATA but only for DRC tools — not registered, dead.
- [x] SecretStore delivery seam — evidence: the fork reads no Solus config or credential store
      anywhere (env grep above is exhaustive); `kicad` is `license_tier=free` — no license
      credentials exist for this fork.

## 5. Untrusted I/O

- [x] Tool inputs hostile — evidence: `export_netlist` validates suffix + existence and raises
      `ValueError` (a tool error, not a crash) on bad input; its only write is traversal-guarded
      (§2). Upstream read handlers check `os.path.exists` and return `{"success": false}` envelopes
      (tier-2 line-read). No archive extraction exists anywhere in the exposed roster (no zipfile/
      tarfile in roster paths), so zip-bomb bounds are n/a for this fork.
- [x] Parsers bound behavior on malformed input — evidence: upstream's `SchematicParser` and the
      BOM parsing wrap handler bodies in try/except returning error envelopes;
      `test_export_netlist_rejects_a_missing_project` / `_a_non_project_path` exercise the refusal
      paths, and the minimal-fixture tests exercise a parseable file. **Residual (recorded):**
      upstream's regex S-expression parser has no explicit input-size cap — a pathological
      multi-hundred-MB `.kicad_sch` would cost memory/time proportional to file size before the
      cloud-side result caps apply. Bounded by: the tools run on the customer's own machine against
      the customer's own files, the companion supervises the process, and cloud ingress caps bound
      what returns. A size pre-check is a cheap T2b/hardening follow-up.
- [x] No hidden eval/exec/dynamic import — evidence:
      `grep -rn "eval(\|exec(\|__import__(" upstream/kicad_mcp upstream/main.py solus/` → one hit:
      `validation_tools.py:155` `__import__("datetime")` — constant string, not input-influenced,
      and `validation_tools` is registered by NEITHER upstream `server.py` nor the overlay (dead
      code either way). No interpreter tool exists in this fork.
- Note (template): outputs are untrusted upstream regardless — cloud ingress owns that side.

## 6. Destructive actions

- [x] Classification — independent classification from handler code (§7 reads): all 6 roster
      tools are non-destructive reads (`export_netlist` writes only its own workspace-confined
      artifact — an export product, not a mutation of user design data;
      `docs/contracts/metadata-extraction.md` §2.1 invariant 5 explicitly classifies export tools
      as non-destructive reads). Diff against `allowlist.yaml`: zero differences — every roster
      entry `requires_confirmation: false` with a reason; `set_symbol_property` (mutates a design
      file) is `requires_confirmation: true` with a reason. Pinned by
      `tests/test_overlay_allowlist_shape.py`.
- [x] Every destructive tool confirmation-gated — evidence: `set_symbol_property` is the only
      destructive entry; `test_validate_inventory_flags_set_symbol_property_as_confirmation_gated`
      proves the cloud gate derives the flag from THIS file. Server-side `destructiveHint` is not
      consulted anywhere (`mcp_tool.py` ignores it; the allowlist is authoritative).
- [x] No side effects beyond descriptions — evidence: tier-2 reads found none in the roster.
      Two behavior notes vs upstream docstrings, both shrinking surface: (1) tools no longer accept
      a `ctx` argument (the overlay strips it — progress reporting disabled, `ctx` never
      model-suppliable); (2) upstream tools whose docstrings mention opening KiCad or writing files
      (`open_project`, `export_bom_csv`, thumbnails, DRC) are not exposed at all.

## 7. Code-review depth — the honest tiers

- [x] **Tier 1 — 100% line-read:** `bin/launch` (44 lines); `solus/` in full (8 files:
      `__init__`, `env_allowlist`, `roster`, `workspace`, `cli_detect`, `trimming`,
      `netlist_export`, `server`); `upstream/main.py` (replaced, read to characterize flags a/b);
      `upstream/kicad_mcp/server.py` (upstream wiring, to enumerate the 16-tool universe);
      `upstream/kicad_mcp/context.py` (lifespan the overlay reuses);
      `upstream/kicad_mcp/utils/env.py` (flag b); `upstream/kicad_mcp/utils/kicad_cli.py`
      (superseded by `solus/cli_detect.py`); `upstream/kicad_mcp/config.py` (import-time env reads).
      Every §2/§4/§5 grep hit above was opened and dispositioned.
- [x] **Tier 2 — line-read (every allowlisted handler touching files):**
      `project_tools.py` (all 3 handlers incl. unexposed `open_project`), `netlist_tools.py`
      (all 4 handlers), `bom_tools.py::analyze_bom`, `utils/kicad_utils.py::find_kicad_projects`,
      `utils/file_utils.py::get_project_files`, `utils/netlist_parser.py` (load/extract/component
      parse paths, lines 1–200). `set_symbol_property` has no handler yet (T2b) — its review lands
      with its code.
- [x] **Tier 3 — spot-check (≥20% of remaining allowlisted-handler helpers):**
      `bom_tools.py::parse_bom_file` region (grep-guided: csv/json/pandas readers; the one XML
      parse at `bom_tools.py:319` uses `defusedxml.ElementTree.parse` — the safe parser),
      `utils/netlist_parser.py::analyze_netlist`. Sample listed by file:function here.
- [x] Non-allowlisted tool code disabled via the `solus/` shim (preferred path): the
      `TrimmingRegistrar` never forwards non-roster registrations, upstream register modules for
      analysis/export/drc/pattern/validation tools and ALL upstream resources/prompts are never
      invoked, and `test_unregistered_upstream_tools_are_dead_in_process` +
      `test_registrar_never_forwards_blocked_registrations` pin it. Residual: dead code still ships
      in the venv (imports exist in the tree) — swept by the tier-1 greps above; nothing in it is
      reachable through the MCP surface.
- [x] Depth recorded: everything not named in tiers 1–3 (docs/, upstream tests/, prompts/,
      resources/, remaining tool modules) was NOT line-read — covered by greps only. That is the
      honest boundary this review claims.

### T1a flags → T1b shims (each also a PROVENANCE "Solus overlay shims" row)

| Flag                             | Upstream behavior                                                                                                      | Shim                                                                                                                                                                     | Pin                                                                   |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------- |
| (a) log file in upstream/        | `main.py` opens `kicad-mcp.log` next to itself (mode "w")                                                              | `bin/launch` execs `solus/server.py`; logging is stderr-only (`_configure_logging`, `force=True`); `sys.dont_write_bytecode` stops `__pycache__` writes into `upstream/` | tree-hash tests; `test_solus_server_module_imports_cleanly`           |
| (b) env-value logging            | `utils/env.py::load_dotenv` (called only by `main.py`) reads a dropped `.env` and logs `key='value'` pairs             | entry never imports/calls it; no `.env` is ever read; env comes solely from the launcher's scrubbed allowlist                                                            | import-audit test; §4 grep reconciliation                             |
| (c) child PATH posture           | upstream CLI prober walks common install paths (user-influenceable)                                                    | `solus/cli_detect.py`: `KICAD_CLI_PATH` or pinned-PATH `which` only, cached once; absent/broken CLI → stable `degraded` reason, exit 0                                   | `test_child_process_path_posture_note`; the detection + degrade suite |
| (d) stdout prints (found in T1b) | upstream tool bodies `print()` to stdout — the MCP stdio protocol channel                                              | registered wrappers divert tool-body stdout to stderr (`solus/trimming.py::_harden`)                                                                                     | `test_registered_wrappers_redirect_stdout_prints_to_stderr`           |
| (e) ctx exposure (found in T1b)  | tools annotate the MCP SDK `Context` against a fastmcp 2.x server; `ctx` could surface as a model-suppliable parameter | wrappers strip `ctx` from the schema-visible signature and always pass `ctx=None` (upstream's own null-ctx workaround path)                                              | `test_registered_wrappers_strip_the_ctx_parameter`                    |

## 8. Update path

- [x] Re-review triggers in force; hash matches — evidence: PROVENANCE re-review triggers list
      unchanged; recorded hash `56f30452214d88aa6b84807d6df7a6e903c48e52` equals the live recompute
      (test-pinned on every run). This review covers exactly that tree.
- [x] On rebase: this checklist re-runs per the template's scoped rules (tier 1 full; tiers 2–3
      scoped to the diff). A pure dependency-bump CVE backport scopes to §1 + §8.
- [ ] Sign-offs — **PENDING(human):** both PROVENANCE sign-off lines are BLANK by design.
      This fork remains PROVISIONAL and not wireable until both devs sign against this tree hash.

---

## Declared sandbox posture (kicad fork, 2026-08-03)

- **macOS / Linux / Windows (today):** invoking user's OS permissions only, hardened by:
  `env -i` scrub to the 11-name allowlist (`solus/env_allowlist.py`); fixed child
  `PATH=/usr/bin:/bin`; cwd pinned to `SOLUS_MCP_WORKSPACE`; fork-private interpreter at a fixed
  path (no PATH resolution); zero network code in the tree (grep-verified); all writes confined
  to `<workspace>/solus-artifacts/`; bytecode writes disabled. Reads extend to the user's KiCad
  project locations (documented tool function).
- **Assumed companion additions later:** install-root verification (already specified),
  process supervision/kill, and OS-level sandboxing (read-only outside the workspace) per
  ADR-031's revisit clause — the fork already passes a headless/deny posture for its write
  paths, so tightening should be behavior-neutral.

## Exclusions and known failure modes

Per the template §Exclusions (no "no vulnerabilities exist" claim; no full line-audit theater;
no sandbox-escape proof; no bit-identical builds; no fuzzing campaign). Known failure modes and
mitigations as in the template; the stale-fork clock (14-day CVE re-vendor) and allowlist-drift
triggers are recorded in PROVENANCE.md.

---

## SOLUSDEV-100 T2b — `set_symbol_property` (2026-08-03)

> Scoped addendum to the T1b review above (not a re-review of §1–§8 in full): covers ONLY the new
> `solus/write/` package and its registration surface. Tree hash unchanged from the T1b header —
> this task never touches `upstream/` or `vendor/` (evidence:
> `test_upstream_tree_hash_is_unaffected_by_this_tree_of_work`,
> `tests/test_vendor_sch_api.py::test_provenance_vendor_tree_hash_matches_a_recompute`, both green).
> Sign-offs remain the SAME pending pair in PROVENANCE.md — this addendum does not ship the tool on
> its own; it stands until `set_symbol_property` is actually wired into `solus/registration.py`
> (flagged below and in the completion report as outside this task's file-ownership manifest).

### Threats considered

1. **Path/value injection** — a caller-supplied `schematic_path` escaping the workspace (symlink,
   `..`, absolute path outside), or a property `value` containing bytes that corrupt the
   S-expression structure on write (unescaped quotes/backslashes, control characters).
2. **Guard bypass** — a locator or splice bug producing a byte diff wider than the one claimed
   property value, silently reformatting or corrupting the rest of the file (the exact failure
   mode `tests/test_vendor_sch_api.py`'s strict-xfail proves the vendored load/save library
   exhibits — this tool exists specifically to not repeat it).
3. **Partial write** — a crash or exception between opening the destination for write and
   completing it, leaving a truncated or half-written schematic on disk.

### Evidence

- **Path/value injection** — `solus/write/paths.py::resolve_confined_schematic_path` resolves
  symlinks before the workspace-confinement check and rejects wrong-suffix, missing, and oversize
  targets; `solus/write/escaping.py::encode_kicad_string` refuses (never encodes) any value
  containing a C0/C1 control character. Evidence:
  `tests/test_write_tool_paths.py` (traversal, absolute-outside, symlink-escape, missing,
  wrong-suffix, directory-as-file, empty-path, oversize, at-cap — 12 tests) and
  `tests/test_write_tool_escaping.py` (control-character refusal boundary,
  `test_control_characters_are_not_round_trippable`, plus the adversarial quotes/backslashes/
  parens/Unicode/100KiB round-trip proofs — 25 tests). End-to-end proof against the real committed
  fixture in `tests/test_write_tool_set_symbol_property.py::test_adversarial_values_produce_a_correct_splice`
  and `test_values_with_control_characters_refuse_cleanly_and_never_corrupt`.
- **Guard bypass** — `solus/write/guard.py::verify_byte_stable_splice` re-tokenizes both the
  original and spliced bytes with the owned tokenizer (`solus/write/sexpr.py`) and requires the
  raw byte diff confined to the located span AND the flat token streams identical except exactly
  one STRING token whose decoded before/after values match the caller's claim. Evidence:
  `tests/test_write_tool_guard.py` (12 tests: clean splice at equal/longer/shorter/escaped
  lengths; injected corruption of a second token, an out-of-span byte, token-count drift, a
  non-string target, a wrong claimed old/new value, and unparseable spliced output — all refuse
  `guard_failed`). End-to-end: `test_guard_injection_via_monkeypatch_refuses_and_leaves_no_temp_litter`
  monkeypatches `verify_byte_stable_splice` to always fail and proves the original file is
  byte-identical afterward AND no temp file exists in the workspace (the guard runs strictly
  before `atomic_write` is ever called, so there is nothing to clean up).
- **Partial write** — `solus/write/atomic_write.py::atomic_write` writes to a `tempfile.mkstemp`
  file in the SAME directory as the destination, `fsync`s it, then calls `os.replace` (atomic
  rename on one filesystem); any exception before the replace unlinks the temp file and leaves the
  destination untouched. Evidence: `tests/test_write_tool_atomic_write.py` (7 tests, incl.
  monkeypatched `os.fsync`/`os.replace` failures proving destination-untouched + no litter, and a
  spy proving the destination's bytes are unchanged right up to the replace call).

### Destructive-action classification

`set_symbol_property` is the fork's one destructive tool: it mutates a design file on the
customer's machine. `allowlist.yaml` already carries `requires_confirmation: true` with the reason
"mutates a design file on the customer machine" (drafted at T1b, unchanged here — this task does
not touch `allowlist.yaml`, per `integrations/mcp/CLAUDE.md` rule 2). Evidence this classification
reaches the cloud gate independent of the fork's own wiring state:
`tests/test_overlay_allowlist_shape.py::test_validate_inventory_flags_set_symbol_property_as_confirmation_gated`
(pre-existing, unmodified by this task) and the new
`tests/test_write_tool_set_symbol_property.py::test_allowlist_yaml_already_maps_set_symbol_property_confirmation_gated`.
No side effect beyond the one property value: the guard's token-stream-identical-except-one-token
assertion is precisely the "no side effects beyond description" proof for this tool.

### Residuals / v1 limitations (recorded, not silently absorbed)

1. **Property creation unsupported** — v1 edits only an EXISTING `(property "Name" "Value" ...)`
   entry; a reference or property that does not already exist refuses (`reference_not_found` /
   `property_not_found`) rather than inserting a new node. Adding creation is a follow-up ticket.
2. **Escaping whitelist, not blacklist** — only backslash and double-quote are escaped on write;
   any value containing a C0/C1 control character (raw newlines, tabs, CR, NUL, DEL, ...) is
   refused outright (`unsupported_value`) rather than attempting an escape this module cannot
   prove KiCad will re-open identically. This is intentionally conservative.
3. **Root-level symbol instances only** — the locator walks only the schematic's TOP-LEVEL
   `(symbol (lib_id ...) ...)` nodes (siblings of `wire`/`label`/`no_connect`); hierarchical-sheet
   nested instances are out of scope for v1 (the committed fixture is single-sheet).
4. **Malformed/unparseable input** — an unparseable `.kicad_sch` (not one of the seven stable
   reasons in the locked vocabulary) surfaces as `reference_not_found` rather than a dedicated
   reason; recorded here rather than inventing an eighth reason unilaterally.
5. **Registration wiring** — `register_write_tools` is NOT yet called from
   `solus/registration.py`, and `solus/roster.py::PENDING_WRITE_TOOLS` still lists
   `set_symbol_property` as pending. Both files are outside this task's file-ownership manifest
   (`.claude/state/ownership/T2b-write-tool.list`); the wiring is a small (~3 line) follow-up
   flagged in the T2b completion report, not silently done here.

### Code-review depth

**Tier 1 — 100% line-read (new code only):** every file in `solus/write/` (`__init__.py`,
`errors.py`, `sexpr.py`, `escaping.py`, `paths.py`, `locator.py`, `guard.py`, `atomic_write.py`,
`set_symbol_property.py` — 9 files, ~650 lines) and every test in
`tests/test_write_tool_*.py` (7 files, 102 tests). No network code, no subprocess calls, no
`eval`/`exec`/dynamic import anywhere in this package (grep: `eval(\|exec(\|__import__(\|subprocess\|socket\.\|requests\|urllib` over `solus/write/` — zero hits).

### Sign-off

No new sign-off line added — this addendum stands under the SAME pending pair in PROVENANCE.md
(both blank; the fork remains provisional). A human re-review covering this addendum should record
against the same tree hash once `set_symbol_property` is wired into `registration.py`.

## 2026-08-03 — Reconciliation: `set_symbol_property` is now REGISTERED (orchestrator)

The T2b addendum above was written while the tool was built but unwired; commit
`0785fa8` registered it through the same `TrimmingRegistrar` as the reads
(`solus/registration.py::register_write_tools`, `solus/roster.py::WRITE_ROSTER`,
served surface = `FULL_ROSTER`). Statements above that the overlay "does not
register it yet" are superseded by this section (append-only; nothing rewritten).

Risk assessment re-affirmed unchanged: the tool remains reachable only through
the allowlist gate with `requires_confirmation: true` (allowlist.yaml entry
drafted with the fork; `tests/test_overlay_tool_trimming.py::
test_set_symbol_property_is_registered_and_confirmation_gated` and
`tests/test_overlay_allowlist_shape.py` pin both facts), the cloud runtime
refuses all confirmation-gated tools until the confirmation flow ships
(`agent/runtime.confirmation_refusal`), and every T2b control (workspace
confinement, splice guard, atomic replace, escaping whitelist) is unaffected
by registration. NOTE for human ratification: the allowlist.yaml header comment
still says the tool is pending implementation — stale, flagged rather than
edited (allowlist edits are human-only per integrations/mcp/CLAUDE.md rule 2).

Sign-off status: unchanged (blank; both-devs gate still open).

## 2026-08-03 — Phase 4 remediation (FIX-B: fork + companion side)

> Scoped addendum: fixes for findings H2, H3 (both halves), M5, M6 (fixture half), L1, L2
> (solus-side docstring half), L3 from the Phase 4 security review. Tree hash unchanged from the
> T1b header — this task never touches `upstream/` or `vendor/`. Sign-offs remain the SAME pending
> pair in PROVENANCE.md.

### H2 — read-tool path arguments are now workspace-confined

**Prior state:** every registered tool that accepted a `project_path`/`schematic_path` argument
(the 5 upstream reads, `export_netlist`) passed it straight to the tool body with no confinement
check — a prompt-injected model call could pass an absolute path to any KiCad project readable by
the invoking user, and that content would flow into the wrong team's graph. This revises the §2
"Declared read scope beyond the workspace" residual recorded at T1b: reads are no longer
unconfined for the roster's path-shaped arguments.

**Fix:** `solus/confinement.py` (new module) resolves every STRING keyword argument whose name is
path-shaped (substring `path`, case-insensitive — matches the roster's actual schemas:
`project_path`, `schematic_path`) against `solus.workspace.workspace_root()`, symlinks included,
BEFORE any tool body runs. `solus/trimming.py::_harden` calls it first, for every registered tool
(read and write alike) — ONE place, not per-tool duplication. A tool with no path-shaped argument
(`list_projects`) is unaffected and never consults the workspace. `set_symbol_property` keeps its
own, stricter `.kicad_sch`-specific check (`solus/write/paths.py`) as defense in depth — pinned by
a dedicated test proving the generic layer refuses BEFORE the write-specific one is ever reached.

**Residual, now closed:** the §2 note "confinement of reads to the workspace is a possible future
tightening" is superseded — implemented. `list_projects` itself still scans
`KICAD_USER_DIR`/`KICAD_SEARCH_PATHS` system-wide (it takes no path argument to confine); that
narrower residual is unchanged and remains documented at T1b.

**Evidence:** `tests/test_confinement.py` (20 tests: no-op on path-less kwargs, confined
absolute/relative paths pass, traversal/absolute-outside/symlink-escape/empty/non-string all
refuse, multi-kwarg partial failure, name-shape detection). `tests/test_overlay_tool_trimming.py`
— new "H2/H3" section (per-roster-tool traversal/absolute-outside/symlink-escape refusal,
in-workspace success, `set_symbol_property`'s defense-in-depth proof, the tool-body-never-invoked
proof).

### H3 — fail-closed workspace resolution (both halves)

**Fork half:** `solus/workspace.py::workspace_root()` now raises `WorkspaceNotConfiguredError`
when `SOLUS_MCP_WORKSPACE` is absent or empty — no cwd fallback. `solus/write/paths.py` maps that
to the existing `path_escapes_workspace` reason (closest honest bucket, same style as the
locator's unparseable-input mapping) rather than letting it escape as a bare exception; the H2
confinement layer does the same for every other registered tool. Evidence:
`tests/test_overlay_env_allowlist.py` (workspace_root/artifact_destination refuse cleanly when
unset), `tests/test_write_tool_paths.py::test_refuses_cleanly_when_the_workspace_is_unconfigured`,
`tests/test_confinement.py::test_refuses_cleanly_when_the_workspace_is_unconfigured`,
`tests/test_overlay_tool_trimming.py::test_registered_wrappers_refuse_cleanly_when_the_workspace_is_unconfigured`.

**Companion half:** `packages/companion/src/solus_companion/config.py` gains
`SOLUS_COMPANION_WORKSPACE` (optional; `CompanionConfig.workspace`, populated by
`config_from_env`). `discover_servers(root, *, workspace=None)` sets
`env={"SOLUS_MCP_WORKSPACE": workspace}` on every discovered `ServerLaunch` when _workspace_ is
given (non-empty), and omits it otherwise — unchanged from today's behavior when omitted.
`supervisor.py::_child_env` already merged `ServerLaunch.env` over the scrubbed `{PATH, HOME}`
base (no change needed there); pinned directly by two new unit tests. Evidence:
`packages/companion/tests/test_companion_config.py` (workspace-omitted/None/empty-string/set
cases for `discover_servers`; `config_from_env` workspace default-None and read-when-set),
`packages/companion/tests/test_companion_supervisor.py::test_child_env_passes_solus_mcp_workspace_through_when_declared`
and `..._omits_..._when_not_declared`. The pre-existing
`packages/companion/src/solus_companion/artifacts.py::server_workspace()` already reads
`launch.env["SOLUS_MCP_WORKSPACE"]` (falls back to the fork dir when absent) — that consumer needed
no change; this fix is what actually starts populating the value it reads.

**Judgment call / flagged residual:** `__main__.py` (the only production caller of
`discover_servers`) and `artifacts.py` are OUTSIDE this task's file-ownership manifest
(`.claude/state/ownership/FIX-B-fork.list` lists only `config.py`, `supervisor.py`, and
`tests/`). `__main__.py` must be updated to call
`discover_servers(config.integrations_root, workspace=config.workspace)` for this fix to take
effect in production — flagged here and in the completion report as a small, targeted follow-up,
not silently done outside the ownership manifest. Separately: the kicad fork's own
`bin/launch` (also outside this task's ownership — explicitly listed as off-limits) still
defaults `SOLUS_MCP_WORKSPACE` to the fork directory itself when the variable arrives unset from
the companion, rather than leaving it truly absent; until that default is removed (a `bin/launch`
change, not a `solus/` one), the fork's own fail-closed `workspace_root()` is fully exercised only
when the process is invoked WITHOUT going through `bin/launch`'s own fallback. Recorded here as an
honest residual rather than silently worked around.

### M5 — sexpr resource guards; RecursionError/OSError never escape

**Fix:** `solus/write/sexpr.py` adds `MAX_TOKENS` (200,000) and `MAX_NESTING_DEPTH` (200), both
enforced incrementally (the token list never grows past the cap regardless of input size) and
raise `GuardExceededError` (a `SExprSyntaxError` subclass). `_parse_node` is rewritten ITERATIVELY
(an explicit stack of open list frames replaces the call stack), so pathological nesting can never
raise `RecursionError` at all — `MAX_NESTING_DEPTH` additionally bounds the stack's own memory as
defense in depth. `solus/write/locator.py` maps `GuardExceededError` to the dedicated
`file_too_large` reason (not the generic `reference_not_found` bucket plain malformed syntax
gets). `solus/write/set_symbol_property.py`'s tool wrapper additionally catches `RecursionError`
and `OSError` (stat/read/atomic-write races, permissions, disk full) and maps both to
`guard_failed` — belt-and-braces, since the pipeline itself should no longer raise either.
`solus/write/locator.py::locate_property_value` explicitly `del`s the parsed tree once its result
is extracted (audited: the flat token list was already function-local to `tokenize()`/`parse()`
and released by CPython refcounting on return — there was no actual cross-phase retention to fix,
this makes the lifetime intent explicit).

**Evidence:** `tests/test_write_tool_sexpr.py` (the exact repro —
`parse(b"("*50000 + b")"*50000)` — refuses via `GuardExceededError`, never `RecursionError`; token
cap at/over/monkeypatched boundary tests; an at-real-cap wall-time-budget test; a 6-shape hostile
sweep asserting only `SExprSyntaxError`/`GuardExceededError` ever escapes).
`tests/test_write_tool_locator.py::test_refuses_pathological_nesting_depth_as_file_too_large`.
`tests/test_write_tool_set_symbol_property.py` (the same two-shape hostile sweep through the full
`set_symbol_property_impl` pipeline; monkeypatched `RecursionError`/`OSError` injection through the
registered tool wrapper, both mapping to `guard_failed`).

### M6 (fixture half) — hostile netlist fixture

`tests/fixtures/solus_sample/solus_sample_hostile.net.xml`: the same design as the committed
`solus_sample.net.xml` (same 9 components, same 22 nets, same designator roster), with adversarial
instruction strings embedded in C1's `<value>`, U2's MPN (`<field>` and `<property>`), and one net
name (an escaped `</export>`-lookalike plus `IGNORE ALL PREVIOUS INSTRUCTIONS`/tool-call-shaped
text, and a markdown code-fence "SYSTEM OVERRIDE" block) — valid XML (adversarial `<`/`>`/`"` are
entity-escaped, never literal), parses through the real
`solus_api.connectors.kicad_netlist.parse_kicad_netlist` with zero warnings. Fork-side evidence
(`tests/test_hostile_fixture.py`, 10 tests): well-formed XML with identical component/net counts
and designator roster vs the benign fixture; zero parse warnings; the injected strings land
VERBATIM as component/net data (never a second `<export>` root, never a structural split); the
renamed net keeps the EXACT SDA-bus node topology, proving the injection changed a string, not
connectivity. FIX-A's cloud e2e half exercises the same fixture through the full ingestion
pipeline (`packages/api/tests/`), outside this task's ownership.

### L1 — stdout diversion is now concurrency-safe

**Prior state:** `solus/trimming.py::_harden` used `contextlib.redirect_stdout(sys.stderr)` held
open across an `await` inside the async wrapper — a global, non-reentrant save/restore. Two
overlapping async tool calls could interleave such that an OUTER call's `__exit__` (restoring the
pre-diversion stdout) ran while an INNER, still-executing call's diversion was still logically
needed, leaking that call's remaining `print()` output onto the real MCP stdio protocol channel.

**Fix:** a process-wide, reference-counted diversion (`_begin_stdout_diversion` /
`_end_stdout_diversion`, guarded by a `threading.Lock`): the real `sys.stdout` is captured only on
the 0→1 transition and restored only on the 1→0 transition, so any interleaving of overlapping
diversions (all redirecting to the same target, `sys.stderr`) is safe regardless of exit order —
this was preferred over "divert once at server startup" because the existing stdout-diversion test
simulates the transport rebinding `sys.stdout`/`sys.stderr` around each call, which a one-time
install at import time cannot observe.

**Evidence:** `tests/test_overlay_tool_trimming.py::test_registered_wrappers_redirect_stdout_prints_to_stderr`
(pre-existing, still green — unchanged behavior for the non-concurrent case) plus the new
`test_concurrent_calls_do_not_clobber_each_others_stdout_diversion` (regression: two overlapping
async tool calls, the second finishing first while the first is still mid-`await`; asserts real
stdout never receives either call's output).

### L2 (solus-side half) — stale docstring corrected

`solus/write/set_symbol_property.py`'s module docstring claimed `register_write_tools` was "NOT
yet wired into `registration.py`" — stale since commit `0785fa8` (see the "2026-08-03 —
Reconciliation" section above). Corrected to point at that reconciliation. `allowlist.yaml`'s
header comment carries the same staleness and is intentionally left alone (allowlist edits are
human-only, `integrations/mcp/CLAUDE.md` rule 2) — that half is the orchestrator's, not this task's.

### L3 — spliced property value size bound

`solus/write/escaping.py` gains `MAX_PROPERTY_VALUE_BYTES` (64 KiB — a KiCad symbol property value
is a short field in practice; 64 KiB is generous headroom over any legitimate use while bounding
the worst-case splice size a single confirmed write can inject). `encode_kicad_string` refuses
(raises `ValueError`, mapped to the existing `unsupported_value` reason by
`set_symbol_property_impl` — no new reason minted) when the FULL encoded literal (quotes included)
exceeds the cap. The pre-existing 100 KiB "adversarial size" round-trip test cases (in
`tests/test_write_tool_escaping.py` and `tests/test_write_tool_set_symbol_property.py`) were
reduced to 32 KiB — still comfortably adversarial, now within the new cap — since 100 KiB legitimately
now refuses under this fix; this is the intended tightening, not a regression. Evidence:
`tests/test_write_tool_escaping.py` (at-cap succeeds and round-trips; one-byte-over refuses;
a multibyte-character case demonstrating the cap is measured in encoded bytes, not characters),
`tests/test_write_tool_set_symbol_property.py::test_a_value_over_the_l3_size_cap_refuses_cleanly_and_never_corrupts`.

### Code-review depth (this addendum)

**Tier 1 — 100% line-read (new/changed code only):** `solus/confinement.py` (new),
`solus/trimming.py`, `solus/workspace.py`, `solus/write/paths.py`, `solus/write/sexpr.py`,
`solus/write/locator.py`, `solus/write/set_symbol_property.py`, `solus/write/escaping.py`,
`packages/companion/src/solus_companion/config.py` (the changed regions), plus every test file
touched. No network code, no subprocess calls, no `eval`/`exec`/dynamic import introduced anywhere
in this diff (grep re-run: `eval(\|exec(\|__import__(\|subprocess\|socket\.\|requests\|urllib`
over the touched `solus/` files — zero new hits).

### Sign-off

No new sign-off line added — this addendum stands under the SAME pending pair in PROVENANCE.md
(both blank; the fork remains provisional).
