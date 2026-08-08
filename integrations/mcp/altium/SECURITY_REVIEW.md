# Fork security review — `altium` @ tree `7e08fbb7450cf0603c24bfe2facbd56a3ffcbe32` — `2026-08-08`

> Filled from `integrations/mcp/SECURITY_REVIEW.template.md` (SOLUSDEV-102 ALT-10 draft review).
> Append-only: later reviews are appended below, never rewrite this one. SIGNATURES LIVE IN
> PROVENANCE.md AND REMAIN BLANK — filling them is a human-only act. This checklist is drafted as
> EVIDENCE for the two human reviewers; items that require the companion install environment, CI,
> a real Windows machine, or a licensed Altium seat are dispositioned **PENDING(human/CI)** or
> **CUSTOMER-SIDE** explicitly rather than ticked on faith.
>
> Scope of this review: upstream `salitronic/eda-agent` pinned SHA
> `77966059eefd7ab94c1520096a95ad1cdce6dd28` (Apache-2.0 + NOTICE) plus the Solus overlay
> (`solus/`, `bin/launch`, `bin/launch.cmd`, `allowlist.yaml`). Exposed surface: the 11-tool
> roster in `allowlist.yaml` — 8 read-only upstream tools + 1 Solus-authored `export_netlist` +
> 2 confirmation-gated writes — out of upstream's ~396-tool surface. Upstream is Windows-first
> (Altium runs only on Windows) and drives Altium through a **file-drop IPC** to a DelphiScript
> bridge plus pywin32 COM attachment; the in-house test environment has **no Altium license and
> no Windows machine** — see "Known failure modes / NOT proven in-house" below for exactly what
> that leaves unproven.

## 1. Supply chain

- [x] `upstream/` matches the PROVENANCE-pinned state — evidence:
      `git rev-parse HEAD:integrations/mcp/altium/upstream` →
      `7e08fbb7450cf0603c24bfe2facbd56a3ffcbe32`, equal to the PROVENANCE "Vendored tree hash"
      (recomputed live by `tests/test_tree_hash.py::test_provenance_tree_hash_matches_a_recompute_of_upstream`
      and `test_recompute_matches_git_rev_parse_on_the_committed_tree` on every run). The tree
      deviates from a verbatim import of the pinned SHA only by the PROVENANCE-logged rows
      (`.github/` exclusion — the ONLY exclusion, human-approved; the ruff force-exclude block
      appended to `upstream/pyproject.toml`). Everything else, including upstream `tests/`,
      `docs/`, `skills/`, `assets/`, and the DelphiScript bridge sources under
      `scripts/altium/`, ships verbatim inside this review surface.
- [x] No runtime fetch — evidence: `bin/launch` (66 lines) and `bin/launch.cmd` (38 lines) read
      in full; token scans pinned by
      `tests/test_launch_entrypoint.py::test_launch_contains_no_network_or_installer_commands`
      and `test_launch_cmd_contains_no_network_or_installer_commands`. The entry
      `solus/server.py` read in full: sys.path bootstrap + pin verification + FastMCP
      construction + trimmed registration only; zero network primitives (see the §2 egress grep).
- [x] Registry install hooks — evidence: upstream is a plain hatchling/pyproject project; no
      `setup.py` exists, `grep -n "cmdclass" upstream/pyproject.toml` → zero hits. The fork is
      never pip-installed anyway: the companion materializes `requirements.lock.txt` into the
      fork-private venv and `bin/launch` runs sources in place from `sys.path`.
- [x] Lockfile committed, complete, hash-pinned — evidence: `requirements.lock.txt` carries
      **524** `--hash=sha256:` pins (`grep -c -- '--hash=sha256:' requirements.lock.txt` → 524).
      Upstream ships NO lockfile of its own (no `uv.lock`/`poetry.lock` in the vendored tree) —
      this is a Solus-generated universal lock. Shape enforced by `tests/test_lockfile.py`
      (`test_every_requirement_is_exact_pinned`, `test_every_requirement_carries_a_hash`,
      `test_upstream_runtime_deps_are_all_covered`); `pywin32==312` correctly keeps its
      `sys_platform == 'win32'` marker (`test_pywin32_keeps_its_windows_marker`) so the COM
      attachment dependency installs only where it can be used. **PENDING(human/CI):** the
      offline `pip install --require-hashes --no-index` reproduction in a network-disabled
      container (companion install-time follow-up, same as the kicad fork).
- [ ] Dependency audit — **PENDING(human/CI):** `pip-audit` against `requirements.lock.txt` is
      the CI dependency-audit job (CLAUDE.md §7); not runnable in this network-restricted
      session. Every advisory found there must be dispositioned in an appended review section
      before ship. CVE intake thereafter: watch-fork advisories + the per-pipeline audit
      (PROVENANCE "Update / rebase policy").
- [x] Reproducibility — evidence: all versions exactly pinned with hashes (see lockfile tests);
      two installs from the same tree cannot resolve different sets. Bit-identical artifacts are
      a template exclusion.

## 2. Least privilege

- [x] Runs as the invoking user — evidence:
      `grep -rn "sudo\|setuid\|seteuid\|runas" upstream/src solus bin` → **zero hits**.
      (The bridge attaches to an ALREADY-RUNNING Altium via
      `win32com.client.GetActiveObject("Altium.Application")` — COM attachment under the
      invoking user's session, no elevation, no process creation on the exposed paths.)
- [x] Filesystem scope — evidence (tier-1/tier-2 line-reads, §7): every registered tool passes
      through `solus/confinement.py` BEFORE its body runs — every path-shaped string kwarg must
      resolve (symlinks included) inside `SOLUS_MCP_WORKSPACE`; refusals are a stable
      `path_escapes_workspace` envelope and an unconfigured workspace fails closed
      (`solus/workspace.py`, never a cwd fallback). The overlay's only direct write path is
      `solus/netlist_export.py::_artifact_destination` (workspace-confined, resolved-path
      re-check). The file-drop IPC exchange is pinned INSIDE the workspace
      (`<workspace>/.eda-agent-ipc/`): `solus/server.py::verify_ipc_environment_pins` refuses
      startup unless `EDA_AGENT_WORKSPACE`/`EDA_AGENT_POINTER_FILE` byte-match the confined
      computation in `solus/pointer.py`, which itself refuses symlink escapes — upstream's
      machine-global pointer default (`C:\ProgramData\eda-agent\workspace-path.txt`) is
      unreachable on every code path (`tests/test_pointer_confinement.py::
    test_program_data_literal_appears_only_in_comments` plus the verify-pins suite in
      `test_overlay_support.py`). Pinned by `tests/test_confinement.py` (14 tests) and the
      per-tool refusal tests in `test_overlay_support.py` / `test_write_tool_guard.py` /
      `test_overlay_export_netlist.py::test_export_netlist_inherits_path_confinement`.
- [x] Network egress: **none on the exposed surface** — evidence:
      `grep -rEn "requests|urllib|http\.client|socket\.|fetch\(|axios|net\.connect|WebSocket"
    solus bin upstream/src/eda_agent/{tools/{application,project,eda,generic,registry}.py,config.py,bridge/}`
      → 3 hits, all comment/docstring text (`bridge/kicad_bridge.py:6,13` module docstring;
      `config.py:78` comment), zero executable network code. Honest residual, stated
      explicitly: the WHOLE vendored `upstream/src` contains network client code in **13
      files** (`libimport/` part-sourcing providers — Digi-Key/Mouser/Nexar/EasyEDA —
      `web/dashboard.py`, `bridge/kicad_bridge.py`, `schemas/`), all belonging to tools/modules
      the overlay never registers or never imports; the tool modules ARE imported via
      `eda_agent.tools.__init__` (import-time side effects reviewed — imports only define
      register functions), `web/` is never imported at all (`test_overlay_support.py::
    test_solus_server_never_touches_upstreams_server_dashboard_or_web`), and the full
      registration + export suite runs green with no network available
      (`tests/test_overlay_offline_degrade.py`). All part-sourcing endpoint/credential env
      knobs are additionally scrubbed by name (§4). No endpoint exemptions needed.
- [x] No `shell=True` / `os.system` — evidence:
      `grep -rn "shell=True\|os\.system\|os\.popen" upstream/src solus bin` → **zero hits**
      across the entire vendored tree. Subprocess use anywhere in `upstream/src` is confined to
      5 files (`checkpoint.py`, `server.py`, `render/rasterize.py`, `core/kicad_export.py`,
      `core/kicad_drc.py`) — all trimmed-dead, none imported by the overlay entry, none
      reachable through any registered tool; the exposed surface (`solus/`, `bin/`, the three
      invoked tool modules, `bridge/`, `config.py`) contains **zero** subprocess sites
      (grep → zero hits). The overlay itself spawns nothing: Altium is driven by file-drop IPC + COM attach to an existing process, never launched.
- [x] `spec.args` fixed — evidence: both launchers exec a fixed argv —
      `"$PYTHON" "$FORK_DIR/solus/server.py"` / the `launch.cmd` twin — with no `$@`/`$*`/`%*`
      passthrough (`test_launch_has_fixed_argv_with_no_argument_passthrough`,
      `test_launch_uses_only_the_fixed_private_interpreter`,
      `test_launch_cmd_exists_and_pins_the_private_interpreter`). `solus/server.py` does no
      argv processing at all. Nothing model- or server-supplied ever reaches any argv: no
      subprocess exists on the exposed paths (above).

## 3. Sandbox posture

- [x] **Declared posture** — see the "Declared sandbox posture" section below. Two OS stories,
      declared honestly: POSIX (the posture reference, used by tests and any macOS/Linux dev
      run) gets the full `env -i` scrub; **Windows — the OS this fork actually ships on — cannot
      `env -i` from cmd.exe**, so `bin/launch.cmd` only SETS the pins and never re-exports
      inherited values, and the authoritative Windows scrub is the companion's child-environment
      allowlist (`solus_companion.supervisor::_child_env` builds the child env from scratch).
      Residual: a NON-companion caller invoking `launch.cmd` directly hands it an unscrubbed
      environment (the launcher's own pins still override the three `EDA_AGENT_*` names and the
      IPC stays confined; the residual exposure is the remaining inherited names). Recorded in
      the `launch.cmd` header and pinned by
      `test_launch_entrypoint.py::test_launch_cmd_documents_the_companion_scrub_residual`.
- [x] Functions under the strictest declared posture — evidence: the offline-degrade suite runs
      the full registration and every `export_netlist` path with no Altium, no network, and a
      scrubbed environment: the roster registers, degraded envelopes
      (`{degraded: true, reason: ...}`) come back instead of crashes, and the server never
      raises (`tests/test_overlay_offline_degrade.py`, 8 tests;
      `tests/test_overlay_export_netlist.py`). An unconfigured workspace refuses startup before
      anything serves (`test_overlay_support.py::test_main_refuses_to_start_before_building_the_server`).
      **PENDING(human/CI):** the deny-by-default container run with read-only mounts outside
      the workspace. **CUSTOMER-SIDE:** behavior with a live Altium attached (see Known failure
      modes).
- [x] Nothing detects/disables sandboxing or self-modifies the install — evidence: tier-1 read
      of `bin/launch`, `bin/launch.cmd`, and all of `solus/` (11 files, 100%);
      `sys.dont_write_bytecode` keeps the vendored tree byte-pristine; the §2/§4/§5 greps show
      no self-modification and no writes outside the workspace helpers. Upstream's `server.py`
      re-exec behavior (`_EDA_AGENT_BACKEND_REEXEC`) is never reachable — that module is never
      imported, and the env name is in the scrub set.

## 4. Secret hygiene

- [x] Environment access confined to the written allowlist — evidence: overlay env reads are
      exactly `solus/workspace.py:34` (`SOLUS_MCP_WORKSPACE`) and `solus/server.py:109,121`
      (the three `EDA_AGENT_*` pins) — all in `CHILD_ENV_ALLOWLIST` (10 names,
      `solus/env_allowlist.py`). Upstream's env surface is enumerated as a WRITTEN declaration:
      `UPSTREAM_ENV_NEVER_FORWARDED` — **45 names**, including all part-sourcing network
      endpoints and 8 distributor credential NAMES (names only, rule 7: `DIGIKEY_CLIENT_ID`,
      `DIGIKEY_CLIENT_SECRET`, `MOUSER_API_KEY`, `NEXAR_CLIENT_ID`, `NEXAR_CLIENT_SECRET`,
      `ELEMENT14_API_KEY`, `TME_TOKEN`, `TME_SECRET`) — listed precisely so nobody ever
      allowlists them. `env -i` drops them mechanically on POSIX; the drift-guard test
      RE-GREPS `upstream/src` on every run so a re-vendor cannot silently widen the surface
      (`tests/test_overlay_env_allowlist.py::test_every_upstream_env_name_is_declared`,
      `test_scrub_set_covers_the_known_upstream_surface`,
      `test_scrub_set_is_disjoint_from_the_child_allowlist`,
      `test_launch_scrubs_environment_to_the_declared_allowlist`). No secret-shaped name in the
      child allowlist (`test_declaration_admits_no_secret_shaped_names`). Windows caveat: the
      cmd.exe scrub gap is §3's declared residual — the companion `_child_env` is the scrub.
- [x] No credential logged — evidence: overlay logging call sites (tier-1 read: `solus/server.py`
      `_configure_logging` + the registration/refusal log lines) log tool names, counts, and
      confined paths only; stderr-only, no log files (upstream's `eda_agent.server` file/stdout
      logging is never imported). Degraded envelopes carry stable reason strings, never env or
      credential content. The exposed upstream handlers (tier-2 read, §7) log via module
      loggers to the same stderr config.
- [x] No telemetry/phone-home on the exposed surface — evidence: the §2 egress grep over the
      exposed surface is empty; nothing to strip. Upstream's Flask dashboard (`web/`) — the
      closest thing to a phone-home surface — is never imported (test-pinned, §2) and its
      enable/disable env knobs are scrubbed.
- [x] No credential persistence — evidence: file-write sites on the exposed paths are (1) the
      workspace-confined netlist artifact (`solus/netlist_export.py`), (2) the file-drop IPC
      command/response files the bridge exchanges under `<workspace>/.eda-agent-ipc/` (tool
      arguments and Altium responses — nothing token-shaped exists in the fork to write), and
      (3) `ipc_dir.mkdir` at startup. Nothing writes dotfiles, caches outside the workspace
      (`EDA_AGENT_CACHE_DIR` and the Windows profile roots `USERPROFILE`/`LOCALAPPDATA` that
      upstream's cache fallbacks read are all scrubbed), or anything under `upstream/`.
- [x] SecretStore delivery seam — evidence: the fork reads no Solus config or credential store
      anywhere (the env reconciliation above is exhaustive). `altium` is `license_tier=byo_paid`
      with `license_secrets: ("altium_license",)` — that gating happens CLOUD-SIDE at invoke
      time (`mcp_servers.py`); the license credential is never delivered to, read by, or
      persisted by this fork. The name appears in this tree only as a name (rule 7).

## 5. Untrusted I/O

- [x] Tool inputs treated as hostile — evidence: path confinement pre-body for every registered
      tool (§2); `WRITE_GUARDS` refuse pre-body on the write tools — parameter names ≤ 64 chars
      and shape-locked (`PARAMETER_NAME_PATTERN` excludes `=`, `;`, `~~`, and every control
      character — the file-drop IPC wire format's `key=value;…` / `~~`-joined-stamp
      metacharacters), values ≤ 4096 bytes (measured in encoded bytes,
      `test_multibyte_value_is_bounded_by_bytes_not_characters`), stamp batches ≤ 500
      (`tests/test_write_tool_guard.py`, 17 tests). A smuggled `force_recompile` on
      `proj_get_nets` is overwritten by the pin, never honoured
      (`test_proj_get_nets_wrapper_neutralizes_a_smuggled_force_recompile`). No archive
      extraction exists anywhere on the exposed surface (`grep -rn "zipfile\|tarfile"` over
      `solus/` + the invoked upstream modules + `bridge/` → zero hits), so zip-bomb bounds are
      n/a for this fork.
- [x] Parsers/emitters bound input and output — evidence: bridge RESPONSES are treated as
      untrusted data: `solus/netlist_export.py` shape-checks defensively
      (`_MalformedPayloadError` → stable `netlist_data_malformed` degrade) and every field
      value flows through the neutralizing emitter `solus/protel_emit.py`, which (a)
      neutralizes the FULL `str.splitlines()` line-boundary set to spaces so an embedded
      `"\n]\n("` collapses into one inert data line — structure can only be forged by minting a
      line, and it cannot be; (b) refuses a field whose entire value IS a structural delimiter
      (no inert spelling exists); (c) refuses dash-bearing node designators outright — the
      cloud parser splits node lines on the FIRST `-`, so emitting one would silently corrupt
      component identity, and refusal beats silent corruption; (d) bounds output at 20k
      components / 20k nets / 200k nodes / 4 MiB, with a 512 KiB inline-vs-artifact branch.
      Every failure returns the degraded envelope `{degraded: true, reason: <stable string>}` —
      the tool NEVER raises (`export_netlist_impl`'s final `except Exception` is the
      never-crash-the-stdio-server guarantee). Degraded envelopes intentionally FAIL the cloud
      `_ExportToolValue` validation, so acquisition declines and the connector falls back to
      the committed export (ADR-030) — a degrade can never masquerade as a good export.
      Evidence: `tests/test_overlay_export_netlist.py` (14 tests: real-parser round-trip,
      hostile-fields-inert, bare-delimiter refusal, dash refusal, all four bounds, cloud-model
      validation of the inline envelope, artifact confinement) and
      `tests/test_overlay_offline_degrade.py`.
- [x] No hidden `eval`/`exec`/dynamic import — evidence:
      `grep -rn "[^a-z_]eval(\|[^a-z_]exec(\|__import__(" upstream/src solus bin` → **zero
      hits** across the entire vendored tree. The DECLARED interpreter surface —
      `obj_run_process` and the `tools/generic.py` object mutators, which execute arbitrary
      DelphiScript/process calls inside Altium — is a HARD EXCLUSION (allowlist.yaml header):
      never allowlisted, never registered, and never even reaches the registrar's audit trail
      because `sch_set_components_parameters` is closure-harvested instead of running
      `register_generic_tools` against the registrar
      (`test_generic_modules_other_tools_stay_dead_and_off_the_audit_trail`).
- Note (template): fork outputs are untrusted upstream regardless — cloud ingress caps and
  redaction own that side; nothing in this review relies on output hygiene. That matters
  doubly here: everything Altium returns through the IPC drop files is customer-machine data
  this review could not sample (see Known failure modes).

## 6. Destructive actions

- [x] Classification — independent classification from handler code (§7 reads) diffed against
      `allowlist.yaml`: **zero differences**. 9 tools non-destructive (8 upstream reads +
      `export_netlist`, whose only write is its own workspace-confined artifact — an export
      product per `docs/contracts/metadata-extraction.md` §2.1, not a mutation of design data);
      2 destructive (`proj_set_parameter` — mutates a project parameter;
      `sch_set_components_parameters` — bulk schematic component-parameter write, higher blast
      radius, drafted with an explicit cut-it-here note for the human ratifiers). Every entry
      carries a `reason`. Pinned by `tests/test_overlay_allowlist_shape.py` (roster ↔ yaml
      equality, write-roster ↔ confirmation-gated equality).
- [x] Every destructive tool carries `requires_confirmation: true` — evidence: the two write
      entries in `allowlist.yaml`;
      `test_write_tool_guard.py::test_allowlist_still_pins_both_writes_confirmation_gated`.
      Server-side `destructiveHint` annotations were NOT relied on — the allowlist is
      authoritative and the cloud ingress ignores server-sent hints.
- [x] No side effects beyond descriptions — evidence: tier-2 reads found exactly ONE, and it is
      neutralized rather than shipped: upstream's `proj_get_nets(force_recompile=True)` default
      SAVES ALL DIRTY DOCUMENTS before recompiling (Project.pas `ForceRecompileIfRequested`) —
      a disk write hidden behind a read-only tool. The overlay force-pins
      `force_recompile=False` and removes the parameter from the advertised schema, so a
      caller can neither trigger nor see it (`PINNED_PARAMETERS`; the allowlist `reason` on
      `proj_get_nets` discloses it; `test_catalog_view_of_the_trimmed_table_omits_the_pinned_parameter`).
      Additional shrinking deltas vs upstream docstrings: `ctx` stripped (never
      model-suppliable), and every upstream tool that opens/saves/exports/executes is not
      exposed at all.

## 7. Code-review depth — the honest tiers

- [x] **Tier 1 — 100% line-read:** `bin/launch` (66 lines), `bin/launch.cmd` (38 lines);
      `solus/` in full (11 files: `__init__`, `env_allowlist`, `workspace`, `pointer`,
      `confinement`, `trimming`, `roster`, `registration`, `server`, `netlist_export`,
      `protel_emit` — all Solus-authored) and the full `tests/` directory (15 test modules).
      Upstream tier-1 (the exposed surface's spine): `upstream/src/eda_agent/config.py` (env
      reads, the machine-global pointer default this overlay confines),
      `upstream/src/eda_agent/bridge/` — `altium_bridge.py`, `payload.py` (the `payload_safe`
      wire sanitiser the write guards back-stop), `script_launcher.py` (the pywin32 COM
      attach), `process_manager.py`, `exceptions.py` — and `tools/registry.py` +
      `tools/application.py`'s `register_meta_tools` (to characterize the meta-dispatch pair
      being killed). Every §2/§4/§5 grep hit above was opened and dispositioned.
- [x] **Tier 2 — line-read (every allowlisted handler):** `tools/application.py`
      (`app_get_status`), `tools/project.py` (the six `proj_*` reads incl. the
      `force_recompile` finding, plus `proj_set_parameter`), `tools/eda.py` (`list_nets`),
      `tools/generic.py::sch_set_components_parameters` (the harvested closure) plus a
      characterization read of its excluded siblings (`obj_run_process`, the object mutators —
      read to CONFIRM they are the hard exclusions the allowlist header says they are), and
      the Solus-authored `netlist_export.py`/`protel_emit.py` (already tier-1).
- [x] **Tier 3 — spot-check:** no remainder — every allowlisted handler is tier-2 above (the
      roster is 11 tools; all were line-read), so the ≥20% sample requirement is vacuously
      exceeded. Recorded rather than skipped so the next reviewer knows nothing was sampled
      away.
- [x] Non-allowlisted tool code disabled via the `solus/` shim (preferred path): the
      `TrimmingRegistrar` never forwards non-roster registrations (implements ONLY `.tool()` —
      a prompt/resource registration after a re-vendor crashes loudly instead of widening the
      surface), only three upstream register functions are ever invoked, and
      `register_backend`/`register_meta_tools`/`register_all_tools` are never called — so
      `tool_catalog`/`tool_invoke` are never created and no `ToolRegistry` exists in-process;
      the resurrection drill proves even upstream's REAL `tool_invoke` over the trimmed table
      can only refuse (`tests/test_meta_tools_are_dead.py`, `tests/test_overlay_tool_trimming.py`).
      **Residual, stated explicitly:** the remaining ~170 of the 182 Python files under
      `upstream/src` (libimport/part-sourcing, web dashboard, render, checkpoint, the design
      agent, the kicad backend, placement/route/sim/review/…) are TRIMMED-DEAD code reviewed
      for **import-time side effects only** (imports define register functions; nothing
      registers without a register call) and swept by the tier-1 greps — they were NOT
      line-read, and they still ship in the venv. Upstream `docs/`, `skills/`, `tests/`,
      `assets/`, and the DelphiScript Pascal sources under `scripts/altium/` were not line-read
      either; the Pascal sources ARE the bridge's other half and their runtime behavior is
      customer-side-validated only (see Known failure modes).
- [x] Depth recorded — the boundary this review claims is exactly the above: Solus overlay +
      tests line-by-line; upstream exposed-surface spine closely; everything else greps +
      import-time review only. **Prompt-injection surface note:** the vendored tree contains
      substantial instruction-shaped content (a 96 KB `README.md`, `docs/`, `skills/` —
      agent-facing playbooks). Nothing in the Solus tree reads or feeds any of it to a model;
      it is inert bytes on the customer disk. Recorded so nobody later wires a doc-serving
      tool without noticing what it would serve.

## 8. Update path

- [x] Re-review triggers in force; hash matches — evidence: PROVENANCE re-review triggers list
      unchanged (upstream change, allowlist addition/gate-loosening, launcher/env-allowlist/
      posture change, dependency change, published CVE); recorded hash
      `7e08fbb7450cf0603c24bfe2facbd56a3ffcbe32` equals the live recompute (test-pinned on
      every run). This review covers exactly that tree.
- [x] On rebase: this checklist re-runs per the template's scoped rules (tier 1 full; tiers 2–3
      scoped to the diff). A pure dependency-bump CVE backport scopes to §1 + §8. Both
      sign-offs required either way.
- [ ] Sign-offs — **PENDING(human):** both PROVENANCE sign-off lines are BLANK by design.
      This fork remains PROVISIONAL and not wireable until both devs sign against this tree
      hash (integrations/mcp/CLAUDE.md rule 3).

---

## Declared sandbox posture (altium fork, 2026-08-08)

- **Windows (the deployment OS — Altium runs only on Windows):** invoking user's OS
  permissions only, hardened by: the companion's `_child_env` allowlist as the authoritative
  environment scrub (cmd.exe cannot `env -i`; `bin/launch.cmd` sets only the pins and never
  re-exports inherited values); `launch.cmd` fails closed without `SOLUS_MCP_WORKSPACE`; cwd
  pinned to the workspace; fork-private interpreter at a fixed path
  (`.venv\Scripts\python.exe`, no PATH resolution); the three `EDA_AGENT_*` pins derived from
  the workspace so the file-drop IPC and pointer file live inside
  `<workspace>\.eda-agent-ipc\` and the machine-global `C:\ProgramData` pointer is never read,
  written, or repointed; server-side pin verification refuses any drift at startup. Residual:
  a non-companion caller of `launch.cmd` inherits its own environment (§3).
- **macOS / Linux (posture reference; test and dev runs — no Altium exists here):** everything
  above PLUS the full `env -i` scrub to the 10-name allowlist and the fixed child
  `PATH=/usr/bin:/bin`. All writes confined to the workspace (`solus-artifacts/`,
  `.eda-agent-ipc/`); bytecode writes disabled; zero network code on the exposed surface
  (grep-verified §2).
- **Assumed companion additions later:** install-root verification, process supervision/kill,
  and OS-level sandboxing (read-only outside the workspace) per ADR-031's revisit clause —
  writes are already workspace-confined and the roster already passes an offline/deny
  posture (degraded envelopes, never crashes), so tightening should be behavior-neutral.

## Known failure modes / NOT proven in-house (read before signing)

Honest statement of what this review could NOT demonstrate, for the two human reviewers and
for the customer-side QA scope (`integrations/mcp/README.md` — `byo_paid` forks are **not on
the in-house QA path**):

1. **No Altium license or Windows machine in-house.** The DelphiScript file-drop round trip,
   the REAL payload shapes of `project.get_nets`/`project.get_bom` (every in-house test feeds
   the documented shapes through a monkeypatched bridge seam), the pointer-file interaction
   with a live Altium session, and the two write tools' ACTUAL effect on a project are
   validated **CUSTOMER-SIDE only**. The fork-side postures (confinement, guards, degrade)
   are proven; the Altium-side behavior is not.
2. **`bin/launch.cmd` cannot env-scrub** (cmd.exe has no `env -i`). The companion's
   `_child_env` allowlist is the authoritative Windows scrub — and companion-side Windows
   launcher resolution is itself tested only under a monkeypatched `sys.platform`
   (`packages/companion/tests/test_companion_windows_launch.py`), never on real Windows.
3. **Upstream is experimental.** Its own README warns that some tools can crash the
   DelphiScript engine inside Altium. Mitigated by the 11-tool read-mostly surface, the
   confirmation gate on both writes, and the degraded-never-raises posture on the export path —
   but a crashed bridge script inside a customer's Altium session is a real possible outcome
   the companion's supervision must tolerate.
4. **Prompt-injection-shaped content ships in the vendored tree** (96 KB README, `docs/`,
   `skills/`). Nothing feeds it to a model today (§7); the risk is a future tool that serves
   tree content without re-reading this note.
5. **Dead code still ships.** ~170 upstream source files (part-sourcing network clients
   included) are import-time-reviewed only; they are unreachable through the MCP surface but
   present in the installed venv (§7 residual).

## Exclusions and known failure modes of the scheme

Per the template §Exclusions (no "no vulnerabilities exist" claim; no full line-audit theater;
no sandbox-escape proof; no bit-identical builds; no fuzzing campaign). The template's scheme
failure modes and mitigations apply as written; the stale-fork clock (14-day CVE re-vendor)
and allowlist-drift triggers are recorded in PROVENANCE.md.

---

## Addendum — Phase 4 fresh-context audit and fix verification (2026-08-08)

Append-only record (integrations/mcp/CLAUDE.md rule 3). A fresh-context security-reviewer
audit of the full SOLUSDEV-102 diff returned four HIGH and four fix-required MEDIUM findings;
all eight were fixed test-first the same day and independently re-verified by the original
reviewer re-running each failure scenario as a live probe. Verdict after verification: PASS
for handoff. The fixes are data-driven entries in the existing mechanisms — no new wrapper
branches.

| # | Finding | Fix (commit) | Verified by |
|---|---|---|---|
| H1 | Confinement guard refused the MCP SDK's own default args (`project_path=None`, `sheet_path=""`), breaking 7 of 11 tools; the real SDK call path had zero coverage | `_is_absent()` in `solus/confinement.py` — None/"" skip as unsupplied; every other non-str and every non-confined string still refuses (`02617db`) | Real-FastMCP `call_tool` drill over all roster tools; escape probes still refuse |
| H2 | `list_nets(backend=...)` let a model argument switch onto the KiCad backend | `PINNED_PARAMETERS["list_nets"] = {"backend": "altium"}` — schema-stripped, smuggle-proof (`d5f25be`) | Schema empty; kicad/KiCad/both/padded variants all neutralized; `KiCadBackend` never constructed |
| H3 | Upstream `tag_response()` injected MANDATORY-worded datasheet imperatives (with attacker-influencable schematic fields) into model-facing tool results | `sanitize_result()` + `STRIPPED_RESULT_KEYS` and dunder-key stripping, one nesting level, values untouched (`a9d6f42`) | Real `tag_response` over the hostile-BOM red-team fixture; instruction keys gone, hostile text inert as leaf data |
| H4 | Model-controllable `timeout` (unbounded) and `limit` (unbounded) could wedge the bridge's single worker thread | `timeout` pinned None + schema-stripped; data-driven `NUMERIC_BOUNDS` refusing `limit` > 100000/20000 (`92b18cf`) | Boundary probes at cap/cap+1; `numeric_bound_refused` envelope |
| M1 | `confinement_refusal` raised on NUL-byte paths | catch `(OSError, ValueError)` → refusal envelope (`0cb2180`) | NUL probe through real `call_tool` |
| M2 | Stamp batches unbounded in keys/total bytes (500×N×4 KiB) | `STAMP_MAX_KEYS=32`, `STAMPS_TOTAL_MAX_BYTES=1 MiB` (`d75f53b`) | Original 60 MB attack payload refused |
| M3 | Windows child-env scrub claims were false (MCP SDK merges env onto `get_default_environment()`, incl. USERPROFILE/LOCALAPPDATA) | Claims corrected in `bin/launch.cmd` + `env_allowlist.py`; runtime child-env test added (also closes M5) (`5ae651a`) | `bin/launch` exec'd with hostile parent env; observed child env ⊆ allowlist |
| M4 | >64 KiB stdin line killed the companion control channel (StreamReader limit) | Reader limit raised + drop-and-continue; desktop 16 KiB pre-check + modal maxLength (`bd10342`, `940e5b2`) | 200 KiB line dropped, loop survives and resyncs; subsequent token+credential lines apply |
| M6 | Vendored docstrings become model-facing tool descriptions unpinned | SHA-256 snapshot test over the 11 exposed descriptions (`22bd15d`) | Suite |
| L1 | `EDA_AGENT_BACKEND` unset silently passed pin verification | Fail-closed like the sibling pins (`ee04078`) | Parametrized missing-pin test |
| L2 | `bridge:token` IPC ungated | `isMainRendererSender` gate matching `bridge:license` (`940e5b2`) | Desktop suite |

**Accepted residuals (open, non-blocking, re-raised only on material change):**
L3 — raw upstream exception text may ride `reason`/`error` keys; deliberately NOT stripped
because the same keys carry Solus's own refusal/degraded envelopes (rationale comment at
`solus/trimming.py::STRIPPED_RESULT_KEYS`). L4 — `launch.cmd` interpolates
`SOLUS_MCP_WORKSPACE` unvalidated (companion-caller-only residual, documented in the header).
L5 — IPC-dir symlink TOCTOU between verification and use (inherent to the file-drop design).
L6 — `protel_emit` silently drops a component whose designator neutralizes to empty (no count
surfaced). Plus the pointer-handshake gap: `upstream/scripts/altium/Main.pas` hardcodes the
machine-global pointer path while the fork confines it — first-run customer validation must
confirm the bridge halves meet (runbook troubleshooting §; needs a fork-side decision before
customer rollout).
