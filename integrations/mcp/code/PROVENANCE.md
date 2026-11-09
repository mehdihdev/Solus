# Provenance — `code`

> Filled from `integrations/mcp/PROVENANCE.template.md` (SOLUSDEV-250). This server is
> **Solus-authored, no upstream, no vendored tree; license MIT (Solus)**. The template's
> upstream fields are answered honestly below rather than dropped, so the reviewer sees the same
> sections on every fork. An unfilled field voids the sign-offs below.

## Identity

- **Server name:** `code` — equals this directory's name and the `server:` field of
  `allowlist.yaml` (`^[a-z][a-z0-9_]{0,31}$`). Composed tool names: `code.probe_environment`,
  `code.plan`, `code.create_environment`, `code.install`, `code.run`, `code.test`, the `code.git_*`
  and `code.arduino_*` tools, and (SOLUSDEV-317) `code.exec`, `code.process_start`,
  `code.process_stop`, `code.process_status`, `code.profile_capture`, `code.profile_list`,
  `code.profile_delete`.
- **Spec location:** none — like `local`, the server is not in `MCP_SERVER_CATALOG`
  (`packages/api/src/solus_api/agent/tools/mcp_servers.py`); the cloud reaches it through the
  bridge's `code.*` dispatch (`docs/api/code-environment.md` §4/§5).

## Upstream

- **Repository:** none — Solus-authored, no upstream, no vendored tree. Every file under
  `solus/`, `bin/`, and `tests/` is Solus code.
- **Commit SHA:** n/a (no upstream).
- **Tag / version:** n/a.
- **Fork date:** n/a — authored 2026-09-07 (SOLUSDEV-250).
- **Vendored tree hash:** n/a — there is no `upstream/` or `vendor/`. The reviewed unit is this
  directory itself: reviewers pin `git rev-parse HEAD:integrations/mcp/code` at review time on
  the sign-off lines below, and any later commit touching this directory is a re-review.

## License

- **SPDX:** `MIT` — Solus-authored code under the repository's license; nothing third-party
  ships from this directory (the runtime dependency closure in `requirements.lock.txt` is
  `mcp` and its transitive dependencies, all MIT/BSD/Apache-2.0, materialized at install time,
  never vendored).
- **LICENSE file:** n/a (no upstream tree to retain).
- **NOTICE (Apache-2.0 only):** n/a.
- **Copyright:** Solus, on every file under `solus/`, `bin/`, and `tests/`.

## Local modifications

No `upstream/` exists, so there are no in-tree edits to log. Solus-authored files need no rows.

| Date       | File(s)                                                                                                                                                                                                                                                       | What & why                                                                                                                                                                          | Author               |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| 2026-10-18 | `solus/` (new: `command_deny.py`, `command_plan.py`, `sandbox.py`, `git_guard.py`, `landlock_exec.py`, `profiles.py`, `processes.py`, `process_os.py`; changed: `plan.py`, `execute.py`, `server.py`, `roster.py`), `allowlist.yaml` (human-approved entries) | SOLUSDEV-317: sandboxed, confirmed command execution, long-running processes and environment profiles. Solus-authored (no upstream); recorded because it voids the sign-offs below. | agent (SOLUSDEV-317) |

Install-time note: `bin/launch` execs the fork-private interpreter
`integrations/mcp/code/.venv/bin/python3`. That virtualenv is NOT committed —
`scripts/install-mcp-forks.sh` materializes it from `requirements.lock.txt` with hash
verification. `bin/launch` performs zero network I/O and no installs. The installs the server
performs LATER, on confirmation, act on the USER's workspace venv (ADR-031 amendment
2026-09-07) — never on this one.

## Exposed tools

- **Allowlist:** `./allowlist.yaml` — authoritative; per-tool `requires_confirmation` lives THERE.
  DRAFT until human-ratified at the MR (integrations/mcp/CLAUDE.md rule 2).
- **Exposed / upstream total:** `25 / 25` — there is no upstream surface to trim; the server
  registers exactly the twenty-five allowlisted tools (`solus/roster.py`, pinned by
  `tests/test_code_allowlist_shape.py` and `tests/test_code_server.py`).
- **Allowlist additions, flagged for ratification (2026-10-29, SOLUSDEV-321 P6):** `ros2_nodes`
  and `ros2_topics` (`solus/ros2_reads.py`), two unconfirmed reads of the live ROS 2 graph. Each
  runs ONE fixed argv (`ros2 node list --no-daemon --spin-time 2`, `ros2 topic list --no-daemon
-t`) through the same planner, OS sandbox and executor as `exec`, with `ros2` resolved only
  through the captured profile the call names, and only when `command_plan.program_scope` judges
  that profile SYSTEM scope over all its search-path variables: a workspace overlay is refused
  ("use code.exec", which keeps its card). The commit security reviews of these reads (R136,
  R137) added Python's `PYTHONUSERBASE`, `PYTHONHOME`, `PYTHONPLATLIBDIR`, `PYTHONEXECUTABLE`,
  `PYTHONPYCACHEPREFIX` and `__PYVENV_LAUNCHER__`, the DDS configuration files and libcrypto's
  `OPENSSL_*` to those variables, and made any variable naming a path inside the folder count
  (the judge serves every plan, so this only ever turns a system judgement into a workspace one).
  The reads run from a fresh, empty, private temporary directory as their working directory —
  never the linked folder — while resolution, environment, sandbox and the scope re-judgement
  before spawn stay on the folder, and only once `~/.ros` exists. `--no-daemon` starts no ROS
  daemon, and the executor kills the command's group and every descendant once it exits. Their
  names are grammar-checked and bounded here, re-checked in the cloud (`agent/tools/ros_live.py`),
  and only ever raise existing inferred edges. When a listing's output tail was cut at the
  executor's tail cap, its first line is dropped: a cut tail starts inside a name, and a partial
  name (`/arm/x` from `/robot/arm/x`) would pass the grammar. Adding tools to this allowlist is a re-review
  trigger: the sign-offs below need re-signing against a dated `SECURITY_REVIEW.md` checklist; no
  sign-off line is written here.
- **Destructive tools:** `create_environment`, `install`, `run`, `test`, `git_commit`, `git_push`,
  `arduino_prepare`, `arduino_compile`, `arduino_upload`, `exec`, `process_start`, `process_stop`,
  `profile_capture`, `profile_delete` (all
  `requires_confirmation: true` — they write to, download into, or execute code on the customer
  machine; `run`/`test` are declared interpreter tools per the security template §5).
  `probe_environment`, `plan`, `git_status`, `git_log`, `git_diff` and `arduino_probe` are read-only
  (`plan` is pure). Git writes require complete dry-run previews and state checks;
  `docs/api/code-git-development.md` governs the SOLUSDEV-261 extension.
  `docs/api/code-arduino-development.md` governs the pinned, sandboxed Uno compiler
  and dependency preparation, with complete previews and no device access. Human
  shipping sign-offs below remain outstanding and are not supplied by agent tests.
  `docs/api/code-command-execution.md` (SOLUSDEV-317, ADR-031 amendment 2026-10-18) governs
  `exec`, the long-running `process_*` tools and environment `profile_*` tools; every
  executing tool now runs in the OS sandbox (`solus/sandbox.py`, `solus/landlock_exec.py`)
  or is refused. `process_status` and `profile_list` are read-only.

## Update / rebase policy

- **CVE intake:** the CI dependency-audit job (CLAUDE.md §7) against `requirements.lock.txt`
  on every pipeline, plus GitHub Security Advisories on `modelcontextprotocol/python-sdk` (the
  `mcp` package). The Python lock is byte-identical to the `local` fork's below
  the header: one advisory triage covers both. Arduino execution additionally uses
  the CLI and nine vendor archives pinned in `solus/arduino_manifest.py`, plus the
  installed Bubblewrap sandbox. Changes to those pins or sandbox assumptions require
  the Arduino API-plan and security re-review; never fetch rolling dependencies.
- **Cadence:** no upstream to diff. A CVE in a pinned dependency → regenerate the lock and
  re-materialize within **14 days**.
- **Rebase procedure:** n/a. Dependency bumps: regenerate `requirements.lock.txt`
  (`uv pip compile --generate-hashes --universal --python-version 3.12` over `mcp==<new>`),
  re-run `tests/test_code_lockfile.py`, re-run the §1 + §8 checklist, both devs re-sign.

## Security review sign-off

Both lines required before the server ships, and again after any re-review trigger
("reviewed by both devs" — no self-approval, no single-reviewer shipping). Humans fill these.

- **Reviewer 1:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`
- **Reviewer 2:** `<name>` — `<date>` — tree hash reviewed: `<SHA>` — checklist:
  `SECURITY_REVIEW.md §<date>`

## Re-review triggers (any of these voids the sign-offs above)

- Any change to `solus/` or `bin/launch` — the directory tree hash pinned on the sign-off lines
  makes this mechanical.
- Any allowlist **addition**, or any `requires_confirmation` flip **true→false**. (Removals and
  false→true shrink surface: one reviewer suffices.)
- Any change to the declared env allowlist (`solus/env_allowlist.py`, `solus/env.allow`), the
  pinned binary search roots (`solus/execute.py::SEARCH_ROOTS`), or the declared sandbox posture
  (including `solus/sandbox.py::HOME_CACHES`, the macOS profile, `solus/landlock_exec.py`, the
  `solus/command_deny.py` tables, `solus/profiles.py::CAPTURE_SCRIPT` and its filters).
- Any dependency added or version-changed in the lockfile.
- A published CVE in any dependency at a version the lockfile pins.
- Shipping a Windows launcher (`bin/launch.cmd`) — a new entrypoint is a new review.
