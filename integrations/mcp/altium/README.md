# `integrations/mcp/altium/` — vendored Altium MCP server fork

Solus-owned fork of [`salitronic/eda-agent`](https://github.com/salitronic/eda-agent)
(Apache-2.0), vendored verbatim at pinned SHA `77966059eefd7ab94c1520096a95ad1cdce6dd28` per
ADR-031 and the layout law in `../README.md`. It drives a **live Altium Designer session** over
upstream's DelphiScript file-drop bridge, exposing a trimmed, read-mostly tool surface (project
status/stats, BOM, nets, component detail, a Solus-authored Protel netlist export, and two
confirmation-gated writes) to SOL as MCP tools running on the customer's machine, launched and
supervised by the bridge companion.

Two facts shape everything here: **Altium runs only on Windows** (so `bin/launch.cmd` is the
launcher that actually runs on customer machines, and the POSIX `bin/launch` is the posture
reference the tests pin), and **the fork is `byo_paid`** — Solus holds no Altium license, so
nothing requiring a live Altium session is provable in-house (see QA scope below).

## What is in this directory

| Path                    | Ownership              | Contents                                                                                                                                                                                                                                                                                                                             |
| ----------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `upstream/`             | third-party (frozen)   | Verbatim upstream tree at the pinned SHA — including the DelphiScript bridge sources (`scripts/altium/`, `Altium_API.PrjScr`), which ARE the bridge's other half. Never edit without a `PROVENANCE.md` modification row — prefer `solus/` shims.                                                                                     |
| `bin/launch`            | Solus                  | POSIX entrypoint and posture reference: fixed argv, `env -i` scrubbed environment (allowlist declared in `solus/env_allowlist.py`), fork-private interpreter `.venv/bin/python3`, zero network I/O, zero installs at launch, confined IPC pins.                                                                                      |
| `bin/launch.cmd`        | Solus                  | Human-approved Windows twin. cmd.exe cannot `env -i`, so the companion's `_child_env` allowlist is the authoritative Windows scrub (residual recorded in `SECURITY_REVIEW.md` §3); same pins, fails closed without `SOLUS_MCP_WORKSPACE`.                                                                                            |
| `requirements.lock.txt` | Solus                  | Fully hash-pinned runtime dependencies. The companion install/update step materializes `.venv/` from it with hash verification (never at launch).                                                                                                                                                                                    |
| `allowlist.yaml`        | Solus (human-ratified) | The single source of truth for exposed tools and per-tool `requires_confirmation`. Companion discovery keys on this file.                                                                                                                                                                                                            |
| `solus/`                | Solus                  | The hardening overlay: `server.py` (the only entry), `registration.py` + `trimming.py` (TrimmingRegistrar, write guards, pinned parameters), `confinement.py` (path-argument confinement), `pointer.py` (confined IPC), `env_allowlist.py`, `netlist_export.py` + `protel_emit.py` (the Solus-authored export tool), `workspace.py`. |
| `PROVENANCE.md`         | Solus                  | Upstream identity, Apache-2.0 license + NOTICE record, vendored-tree hash, modification log, shim evidence table, sign-offs.                                                                                                                                                                                                         |
| `SECURITY_REVIEW.md`    | Solus (append-only)    | Dated checklist copies against the pinned tree hash; the fork does not ship until both dev sign-offs in `PROVENANCE.md` pin the current hash.                                                                                                                                                                                        |
| `tests/`                | Solus                  | Launcher/provenance/lockfile/tree-hash law plus the overlay suites (trimming, meta-tool death, confinement, write guards, env allowlist, offline degrade), run by root `pytest` (`uv run pytest integrations/mcp/altium -q`).                                                                                                        |

## How the companion launches it

- `MCPServerSpec.command` names `bin/launch` and nothing else (`mcp_servers.py::ALTIUM`,
  `license_tier=byo_paid`, `license_secrets=("altium_license",)`). On win32 the companion
  resolves the sibling `bin/launch.cmd` and fails closed with a REFUSED log when it is absent
  (`docs/wireflows/license-capture.md`, Windows launcher note).
- The companion passes the project workspace via `SOLUS_MCP_WORKSPACE`. The launcher derives the
  three `EDA_AGENT_*` pins from it — never inherits them — so upstream's file-drop IPC exchange
  and pointer file live inside `<workspace>/.eda-agent-ipc/` and upstream's MACHINE-GLOBAL
  pointer default (`C:\ProgramData\eda-agent\workspace-path.txt`) is never read, written, or
  repointed. `solus/server.py` re-verifies the pins at startup and refuses to start on any
  mismatch; an unset workspace fails closed.
- The exec'd entry is `solus/server.py`, never upstream's `eda_agent.server` (which registers
  the full ~396-tool surface at import time, spawns a Flask dashboard thread, and probes ports).

## Tool surface — 11 registered, ~396 upstream

`allowlist.yaml` is authoritative; this table is a reader's map. Registration is enforced
fork-side by the `TrimmingRegistrar` (`solus/registration.py`): only three upstream register
modules are invoked, every non-roster sibling lands on a blocked audit trail, and upstream's
`tool_catalog`/`tool_invoke` meta-dispatch pair is **never created**
(`tests/test_meta_tools_are_dead.py`).

| Tool                            | Origin                                | Writes?                      | Notes                                                                                                                                                                                                          |
| ------------------------------- | ------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app_get_status`                | upstream                              | no                           | Altium reachability, version, active document.                                                                                                                                                                 |
| `proj_get_path`                 | upstream                              | no                           | Path of the focused project.                                                                                                                                                                                   |
| `proj_list_documents`           | upstream                              | no                           | Member documents of the project.                                                                                                                                                                               |
| `proj_get_stats`                | upstream                              | no                           | Sheet/component/pin/net counts.                                                                                                                                                                                |
| `proj_get_bom`                  | upstream                              | no                           | Designator/comment/footprint/lib_ref + pin-nets — the primary graph feed.                                                                                                                                      |
| `proj_get_nets`                 | upstream                              | no                           | Pin-net table. `force_recompile` is force-pinned to `False` and stripped from the schema (upstream's `True` saves all dirty documents — a disk write hidden behind a read).                                    |
| `proj_get_component_info`       | upstream                              | no                           | Single-component detail.                                                                                                                                                                                       |
| `list_nets`                     | upstream                              | no                           | Backend-agnostic net summary.                                                                                                                                                                                  |
| `export_netlist`                | **Solus** (`solus/netlist_export.py`) | no                           | Synthesizes a Protel netlist from `proj_get_nets`/`proj_get_bom` reads; inline ≤ 512 KiB, workspace artifact above; degrades to `{"degraded": true, "reason": …}` and never raises when Altium is unreachable. |
| `proj_set_parameter`            | upstream                              | **yes — confirmation-gated** | Project-parameter write, size/shape-bounded by `WRITE_GUARDS` before the body runs.                                                                                                                            |
| `sch_set_components_parameters` | upstream                              | **yes — confirmation-gated** | Bulk component-parameter stamp (batches ≤ 500), extracted by an inert closure harvester so its module's siblings (`obj_run_process`, object mutators) stay dead.                                               |

Every registered tool inherits the overlay hardening: path arguments confined to the workspace
(`solus/confinement.py`), `ctx` stripped, stdout diverted off the MCP protocol channel, and the
scrubbed child environment. Hard exclusions (meta-dispatch, `obj_run_process`, part-sourcing
network providers, the KiCad backend, ECO/output-job runners, export renderers) are recorded in
`allowlist.yaml`'s header and `SECURITY_REVIEW.md` so no later MR "rediscovers" them.

## BYO-license QA scope (`byo_paid`)

From `../README.md`, restated because it governs how this fork is tested: **BYO-paid tools are
validated on customer machines — they are NOT on the in-house QA path.** Solus does not hold an
Altium license; in-house QA covers free-tier tools only. This fork still ships with the full
paper trail (provenance, security review, allowlist), but its end-to-end validation against the
real Altium Designer application happens customer-side, gated by the customer's own license.

Concretely:

- The customer's license is captured in the desktop app's "Add license" modal and relayed via
  the companion (`credential_submit`, key name `altium_license`) to per-team Secrets Manager
  storage — key NAMES only in every log, ack, and status detail
  (`docs/wireflows/license-capture.md`, `docs/contracts/bridge-protocol.md` Addenda B+C).
- `GET …/bridge` surfaces per-server `license_state`: `ready` ·
  `bring_your_license` (plan-entitled, keys missing) · `upgrade_required` (plan not entitled —
  BASIC's `byo_paid_tools` limit is 0; PRO is unlimited).
- In-house, everything that does NOT need Altium is proven by the fork test suite and the QA
  plan's in-house section: launch confinement, trimming, guards, license capture, and
  `export_netlist`'s honest degraded envelope (`altium_unreachable`) feeding the
  `AltiumConnector`'s inline-export fallback (ADR-030).
- The split test plan is `docs/qa/COWORK_QA_altium-mcp.md`; the customer-side half runs off
  `docs/qa/RUNBOOK_altium-customer-validation.md`.

## How to re-vendor (upstream update / CVE response)

A CVE affecting a shipped code path starts the **14-day** re-vendor clock (ADR-031 /
`PROVENANCE.md` update policy; quarterly diff review otherwise):

1. Clone upstream OUTSIDE the repo; check out the new commit SHA; verify `LICENSE` is still
   Apache-2.0 and `NOTICE` is present (anything else: stop — human/legal decision). The NOTICE
   file ships verbatim with every distribution.
2. Delete and re-import `upstream/` byte-verbatim in a single commit, applying the approved
   exclusion (`.github/` only for this fork — `tests/`, `docs/`, `skills/`, `assets/`, and the
   DelphiScript sources under `scripts/altium/` ship verbatim; the Pascal sources ARE the
   bridge) — one `PROVENANCE.md` modification row per exclusion that existed upstream.
3. Regenerate `requirements.lock.txt` from the new upstream lock with hashes
   (`uv export --frozen --no-dev --no-emit-project`).
4. Update `PROVENANCE.md`: new SHA, fork date, and vendored tree hash
   (`git rev-parse HEAD:integrations/mcp/altium/upstream`).
5. Replay Solus-authored changes: the `[tool.ruff]` exclusion block appended to
   `upstream/pyproject.toml` (see its PROVENANCE row), then re-run
   `uv run pytest integrations/mcp/altium -q`. The suite is built to catch re-vendor drift:
   the env drift-guard re-greps `upstream/src` for new env names, the trimming tests re-count
   the upstream surface, and the tree-hash test recomputes the pin.
6. Re-run the security checklist (scoped re-review rules in `../SECURITY_REVIEW.template.md`
   §8) and APPEND the dated copy to `SECURITY_REVIEW.md`; both devs re-sign `PROVENANCE.md`
   against the new tree hash. The old sign-offs are void the moment the hash changes.
