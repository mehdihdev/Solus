# Provenance — `altium`

> Filled from `integrations/mcp/PROVENANCE.template.md` (MCP-03, SOLUSDEV-102 ALT-1).
> An unfilled field, or a stale vendored-tree hash, voids the sign-offs below.

## Identity

- **Server name:** `altium` — equals `MCPServerSpec.name` and this directory's name
  (`^[a-z][a-z0-9_]{0,31}$`).
- **Spec location:** `packages/api/src/solus_api/agent/tools/mcp_servers.py::ALTIUM` — the one
  spec that binds to this fork (`license_tier: byo_paid`, `license_secrets: ("altium_license",)`).

## Upstream

- **Repository:** `https://github.com/salitronic/eda-agent` — the canonical upstream, not a
  mirror.
- **Commit SHA:** `77966059eefd7ab94c1520096a95ad1cdce6dd28` — the exact commit vendored.
- **Tag / version:** `none` — upstream publishes no release tags; its `pyproject.toml` declares
  version `0.5.0`.
- **Fork date:** `2026-08-08` — when `upstream/` was imported at that SHA.
- **Vendored tree hash:** `7e08fbb7450cf0603c24bfe2facbd56a3ffcbe32` — recompute with
  `git rev-parse HEAD:integrations/mcp/altium/upstream`. Any change to `upstream/` changes this
  hash and mechanically voids the sign-offs (`tests/test_tree_hash.py` recomputes it on every
  test run).

## License

- **SPDX:** `Apache-2.0` — verified against `upstream/LICENSE` and
  `upstream/pyproject.toml` (`license = "Apache-2.0"`) before import.
- **LICENSE file:** `upstream/LICENSE` — retained verbatim, never edited.
- **NOTICE (Apache-2.0 only):** `upstream/NOTICE` ("eda-agent, Copyright 2026 George Saliba")
  preserved verbatim and shipped with every distribution of the fork.
- **Copyright:** original headers retained in all `upstream/` files; Solus headers only on files
  under `solus/` and `bin/`.

## Local modifications

One row per deviation from a verbatim import of the pinned SHA (files under `solus/` and `bin/`
are Solus-authored and need no rows). The import is byte-identical to upstream at the pinned SHA
**except** the exclusions below (human-approved F6 exclusion pattern, re-approved for
SOLUSDEV-102 as `.github/` only — everything else, including `tests/`, `docs/`, `skills/`,
`assets/`, and the DelphiScript bridge sources under `scripts/altium/`, ships verbatim because
the Pascal sources ARE the bridge and belong inside the security-review surface).

| Date       | File(s)                                                | What & why                                                                                                                                                                                                                                                                                                                                               | Author                    |
| ---------- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| 2026-08-08 | `.github/` (6 files: CI workflows, repo automation)    | Not vendored — upstream repo automation, never imported at runtime; F6 `.github/`-only exclusion human-approved in-session for SOLUSDEV-102.                                                                                                                                                                                                             | SOLUSDEV-102 orchestrator |
| 2026-08-08 | `upstream/pyproject.toml` (`[tool.ruff]` section only) | Appended a Solus-marked ruff exclusion block (`force-exclude = true`, `extend-exclude = ["**"]`). Ruff resolves the NEAREST config per file, so this vendored pyproject — not the repo root — governs `upstream/`; without the block the H8/H10 quality hooks lint reviewed third-party code. No runtime behavior change (packaging/lint metadata only). | SOLUSDEV-102 orchestrator |

Install-time note (not an `upstream/` edit): `bin/launch` execs the fork-private interpreter
`integrations/mcp/altium/.venv/bin/python3` (POSIX) / `.venv\Scripts\python.exe` (Windows via
`bin/launch.cmd`). That virtualenv is NOT committed — the companion install/update step
materializes it from `requirements.lock.txt` with hash verification (`--require-hashes`
semantics). The launchers themselves perform zero network I/O and no installs.

## Exposed tools

- **Allowlist:** `./allowlist.yaml` — authoritative; per-tool `requires_confirmation` lives
  THERE. The whole file is human-ratified at the MR. The `ServerAllowlist` model forbids extra
  fields, so the exposed/total ratio is recorded HERE, not in the yaml.
- **Exposed / upstream total:** `8 / ~396` — upstream's register modules define roughly 396
  tools (test-guarded floor of 300: `tests/test_overlay_tool_trimming.py::
test_upstream_surface_is_large_and_contains_the_whole_roster`); the overlay registers 8 of
  them (`app_get_status`, `proj_get_path`, `proj_list_documents`, `proj_get_stats`,
  `proj_get_bom`, `proj_get_nets`, `proj_get_component_info`, `list_nets`) plus 1
  Solus-authored tool (`export_netlist`, `solus/netlist_export.py`) plus 2 confirmation-gated
  upstream write tools (`proj_set_parameter`; `sch_set_components_parameters`) — **11
  registered total**. Enforcement is fork-side, not just cloud-side: `bin/launch` /
  `bin/launch.cmd` exec `solus/server.py` (never upstream's `eda_agent.server`), and
  `solus/registration.py` invokes only three upstream register functions
  (`register_application_tools`, `register_project_tools`, `register_eda_tools`) through the
  `TrimmingRegistrar` — every non-roster sibling lands on the registrar's blocked audit trail,
  never on the server. Upstream's `register_backend` / `register_meta_tools` /
  `register_all_tools` are never invoked, so the `tool_catalog`/`tool_invoke` meta-dispatch
  pair is **never created** and no `ToolRegistry` dispatch table ever exists in-process — a
  resurrected `tool_invoke` over the trimmed table can only refuse, proven against upstream's
  real mechanism (`tests/test_meta_tools_are_dead.py`). `sch_set_components_parameters` is
  extracted from `tools/generic.py` by an inert `_ClosureHarvester` (captures the ONE wanted
  closure, registers it through the hardened path, drops every sibling unregistered), so the
  module's hard-excluded tools (`obj_run_process`, the object mutators) never even reach the
  audit trail (`tests/test_write_tool_guard.py::
test_generic_modules_other_tools_stay_dead_and_off_the_audit_trail`).
- **Destructive tools:** two allowlisted — `proj_set_parameter` and
  `sch_set_components_parameters`, both `requires_confirmation: true` with a `reason` in the
  yaml; fork-side depth behind the cloud gate is the data-driven `WRITE_GUARDS`
  (`solus/trimming.py`): parameter names ≤ 64 chars and shape-locked against the IPC
  wire-format metacharacters (`=`, `;`, `~~`, control characters), values ≤ 4096 bytes, stamp
  batches ≤ 500 — refusing BEFORE the tool body runs (`tests/test_write_tool_guard.py`). One
  hidden write was found behind a read and neutralized rather than shipped: upstream's
  `proj_get_nets(force_recompile=True)` saves ALL dirty documents to disk — see shim row (d).
- **Solus overlay shims** (all in `solus/` and `bin/`, zero `upstream/` bytes changed — the
  vendored tree hash is unaffected; full evidence in `SECURITY_REVIEW.md` §7):

  | Row | Flag                                                                                                                                                  | Shim                                                                                                                                                                                                                                                       | Pin                                                                                                                                                |
  | --- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
  | a   | upstream's entry (`eda_agent.server`) registers the FULL surface at import time, spawns a Flask dashboard thread, probes ports, re-execs on CLI flags | `solus/server.py` is the only entry; it never imports `eda_agent.server` or `eda_agent.web`; stderr-only logging; `sys.dont_write_bytecode` keeps `upstream/` byte-pristine                                                                                | `test_overlay_support.py::test_solus_server_never_touches_upstreams_server_dashboard_or_web`; tree-hash tests                                      |
  | b   | `tool_catalog`/`tool_invoke` meta-dispatch can invoke ANY of the ~396 tools by name, making any allowlist decorative                                  | `register_meta_tools`/`register_backend` never invoked: the pair is never created and no `ToolRegistry` exists in-process; even a resurrected `tool_invoke` over the trimmed table only refuses                                                            | `tests/test_meta_tools_are_dead.py` (9 tests, incl. the resurrection drill against upstream's real implementation)                                 |
  | c   | upstream's file-drop IPC defaults to a MACHINE-GLOBAL pointer file (`C:\ProgramData\eda-agent\workspace-path.txt`) shared with any Altium session     | launchers SET `EDA_AGENT_BACKEND/WORKSPACE/POINTER_FILE` derived from `SOLUS_MCP_WORKSPACE` (never inherited); `solus/server.py` refuses to start on any env-pin mismatch; `solus/pointer.py` refuses symlink escapes; unconfigured workspace fails closed | `tests/test_pointer_confinement.py`; `test_launch_entrypoint.py::test_launch_sets_the_ipc_pins_and_never_inherits_them`; the `verify_pins` suite   |
  | d   | `proj_get_nets(force_recompile=True)` saves all dirty documents — a disk write hidden behind a read-only tool                                         | `PINNED_PARAMETERS` force-pins `force_recompile=False` (a smuggled value is overwritten) and removes the parameter from the advertised schema                                                                                                              | `test_overlay_support.py` pinned-parameter tests; `test_meta_tools_are_dead.py::test_catalog_view_of_the_trimmed_table_omits_the_pinned_parameter` |
  | e   | tool path arguments are unconfined upstream — a prompt-injected call could read any project the invoking user can                                     | `solus/confinement.py`: every path-shaped string kwarg must resolve (symlinks included) inside the workspace, refused pre-body in ONE place for every registered tool                                                                                      | `tests/test_confinement.py` (14 tests); per-tool refusal tests in `test_overlay_support.py`                                                        |
  | f   | write-tool parameters ride an IPC wire format of `key=value;…` pairs and `~~`-joined stamps — unbounded/metacharacter values could corrupt framing    | `WRITE_GUARDS` shape-lock and size-bound names/values/batches before the body (see Destructive tools above)                                                                                                                                                | `tests/test_write_tool_guard.py`                                                                                                                   |
  | g   | a `ctx` parameter could surface as a model-suppliable input after a re-vendor                                                                         | wrappers strip `ctx` from the advertised signature and pin it to `None` on the call                                                                                                                                                                        | `test_overlay_support.py::test_registered_wrappers_strip_the_ctx_parameter`                                                                        |
  | h   | upstream tool bodies `print()` onto stdout — the MCP stdio protocol channel                                                                           | reference-counted process-wide stdout→stderr diversion, safe under overlapping async tool calls                                                                                                                                                            | `test_overlay_support.py::test_registered_wrappers_redirect_stdout_prints_to_stderr` and the concurrent-diversion regression test                  |
  | i   | upstream reads a 45-name env surface incl. distributor credentials and part-sourcing network endpoints                                                | `env -i` + the 10-name `CHILD_ENV_ALLOWLIST`; the 45 scrubbed names are DECLARED (`UPSTREAM_ENV_NEVER_FORWARDED`) and a drift-guard test re-greps `upstream/src` so a re-vendor cannot silently widen the surface                                          | `tests/test_overlay_env_allowlist.py` (incl. `test_every_upstream_env_name_is_declared`, `test_scrub_set_covers_the_known_upstream_surface`)       |

- **Env-allowlist declaration:** the written declaration lives in `solus/env_allowlist.py`
  (10 names: `HOME`, `USER`, `LANG`, `LC_ALL`, `TMPDIR`, `PATH`, `SOLUS_MCP_WORKSPACE`, plus
  the three launcher-SET `EDA_AGENT_*` pins); `bin/launch`, `bin/launch.cmd`, and
  `tests/test_launch_entrypoint.py` are pinned to it. On Windows (`bin/launch.cmd`, no
  `env -i`) the companion's `_child_env` allowlist is the authoritative scrub — the residual
  is recorded in `SECURITY_REVIEW.md` §3.

## Update / rebase policy

- **CVE intake:** GitHub Security Advisories + Dependabot alerts on a Solus-owned watch fork of
  `salitronic/eda-agent`, plus the CI dependency-audit job (CLAUDE.md §7) run against
  `requirements.lock.txt` on every pipeline.
- **Cadence:** quarterly upstream diff review; a CVE affecting a shipped code path → re-vendor
  within **14 days**.
- **Rebase procedure:** re-import `upstream/` at the new SHA as a fresh verbatim commit (same
  exclusion rows re-evaluated), replay Solus-authored changes (the ruff block row above), update
  SHA + tree hash above, regenerate `requirements.lock.txt`, re-run the security checklist
  (scoped re-review rules in `SECURITY_REVIEW.template.md` §8). Step-by-step in `./README.md`.

## Security review sign-off

Both lines required before the fork ships, and again after any re-review trigger
("reviewed by both devs" — no self-approval, no single-reviewer shipping).

- **Reviewer 1:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`
- **Reviewer 2:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`

## Re-review triggers (any of these voids the sign-offs above)

- Any change to `upstream/` (rebase, backport, in-tree edit) — the tree hash makes this
  mechanical.
- Any allowlist **addition**, or any `requires_confirmation` flip **true→false**. (Removals and
  false→true shrink surface: one reviewer suffices.)
- Any change to `bin/launch` / `bin/launch.cmd`, the declared env allowlist
  (`solus/env_allowlist.py`, pinned by `tests/test_launch_entrypoint.py`), or the declared
  sandbox posture.
- Any dependency added or version-changed in the lockfile.
- A published CVE in any dependency at a version the lockfile pins.
- For url-transport specs bound to this record: any endpoint URL change.
