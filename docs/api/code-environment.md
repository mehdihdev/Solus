# Code environment — the "VSCode item", properly named (SOLUSDEV-250 / INTEGRATIONS I3)

Repository operations added by SOLUSDEV-261 are specified in
[`code-git-development.md`](code-git-development.md); they use this same Code server
and central confirmation path.

Route plan + wire shapes. Tier-1 (ADR-032). Companion docs: `docs/api/local-folder.md` (the
`local` source and server this extends), `docs/api/solus.md` (the `.solus` sections — `code` is
"Code environment", `errors` is "Error logging"), `docs/contracts/action-gate.md` (every command
is confirmation-gated), DECISIONS.md ADR-031 as amended 2026-09-07 (a Solus-authored server may
run installs/scripts/tests in the USER's environment: argv-only, gated, confined, bounded).

## 1. What it is

The project's Code environment is the linked folder on THIS machine plus the interpreter and
virtual environment that run it. Solus:

- **knows the dependencies** — the `local` server's scan now also parses dependency
  declarations (`requirements*.txt`, `pyproject.toml` `[project]` dependencies and optional
  dependencies, `environment.yml` conda + pip deps) into `python_requirement` graph nodes under
  the local clone, one per (source file, package);
- **detects conflicts** — `PinConflictChecker` (pure, `checkers/environment.py`) flags the same
  package pinned differently across files (Isaac pins `torch==2.1.0`, the policy wants
  `torch>=2.3`) and proposes a split;
- **proposes an environment spec** — `code.resolve_environment` (in-process SOL tool, read-only):
  one environment per conflicting source file, otherwise one `default`, each with its
  requirement list; the same proposal feeds the desktop row;
- **acts through the approval card** — the Solus-authored `code` server exposes
  `probe_environment` and `plan` (reads) and `create_environment`, `install`, `run`, `test`
  (all `requires_confirmation: true`); the card shows the EXACT argv the server will execute,
  read back from the server's own `plan` before parking;
- **files failures** — a confirmed `run`/`test` that exits non-zero is filed as one entry in the
  project's `.solus` Error logging section (author `sol`), which is what S5 promised.

Nothing here executes on the cloud. No shell strings anywhere: the server assembles argument
lists from validated arguments.

## 2. Routes

| Method | Path                                                          | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                               | Success |
| ------ | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| GET    | `/api/v1/projects/{project_id}/code-environment?machine_id=…` | This machine's Code environment: `{source, bridge: {connected, code_server}, probe, requirements: {count, files: [..]}, conflicts: [Warning…], proposal}`. `probe` is a LIVE `code.probe_environment` over the caller's own bridge session (null when offline / the server is not ready; one probe per (user, project, machine) is reused for 10 s and never two in flight); `requirements`/`conflicts`/`proposal` come from the graph (`python_requirement` nodes of the machine's local source) and are pure. MEMBER+. | `200`   |

The route emits `code_environment.viewed` ({linked, probed, conflicts}). No other routes: installs, runs and tests happen only through SOL turns and the existing
`POST /sol/confirmations/{id}` gate.

## 3. Scan extension (the `local` server, `docs/api/local-folder.md` §4)

`scan_folder` gains `dependencies` (≤ **500** entries, `truncated_dependencies: bool`):

```json
{
  "parts": ["isaac", "requirements.txt"],
  "ecosystem": "python",
  "name": "torch",
  "specifier": "==2.1.0",
  "extras": [],
  "line": 3
}
```

- Sources parsed, bounded to 256 KiB each: `requirements*.txt` (PEP 508 lines; `-r`/`-e`/
  options and comments skipped, never followed), `pyproject.toml` (`[project].dependencies`,
  `[project.optional-dependencies].*`; `tomllib`, no execution), `environment.yml` (the
  `dependencies:` list — conda `name=ver` → `==ver`, and the nested `- pip:` block; parsed by a
  minimal line reader, no YAML library), `Pipfile` is NOT parsed (TOML sections of packages are
  version-dict shaped; deferred).
- `name` is PEP 503-normalised (lower-case, `[-_.]+` → `-`); `specifier` is the raw PEP 440 set
  (`""` when unpinned) ≤ 128 chars; `extras` ≤ 8 entries.
- Every string stays under the ingress-redaction threshold by construction (segments, short
  specifiers); a specifier over 40 base64-ish chars is truncated.

The connector lands: `python_requirement` (domain `code`, key `req:<source path>:<name>`,
name `<name> <specifier>`, props `{name, specifier, extras, source_file, ecosystem, line}`) and a
`requires` edge from `clone:` to each. The cursor carries `dependencies_truncated`.

## 4. The `code` server's tools (`integrations/mcp/code/allowlist.yaml`)

Workspace-confined; the workspace IS the linked folder. Composed names `code.<tool>`.

| tool                 | gated   | args                                                                                       | answer                                                                                                                                                                                                                                                                                                                                                                    |
| -------------------- | ------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `probe_environment`  | no      | `{environment?: "sim"}`                                                                                       | `{python: {path, version} \| null, interpreters: [{path, version}] ≤8, venv: {path, python_version, packages: [{name, version}] ≤300, truncated} \| null, conda: {path, envs: [names] ≤32} \| null, uv: {path, version} \| null}` — `venv` is the workspace's `.venv`/`venv`/`env` (first found); packages via `<venv>/bin/python -m pip list --format json`, or `uv pip list --python <venv python>` when the venv has no pip — a `uv venv` ships none (argv, 60 s) |
| `plan`               | no      | `{action: create_environment\|install\|run\|test, args: {...}}`                            | `{argv: [...], cwd: ".", ok: bool, reason: str \| null}` — the EXACT argv the action would run, or the refusal reason. Pure: no execution                                                                                                                                                                                                                                 |
| `create_environment` | **yes** | `{path?: ".venv", python?: "3.12"}`                                                        | `{ok, path, argv, exit_code, stdout_tail, stderr_tail, duration_ms}` — `python3[.X] -m venv <path>` (uv when present: `uv venv --python X <path>`); refuses an existing path                                                                                                                                                                                              |
| `install`            | **yes** | `{packages: [≤64 PEP 508 strings], environment?: ".venv"}`                                 | same result shape — `<venv>/bin/python -m pip install -- <pkgs…>` (uv pip when present); refuses `-`-prefixed items, URLs, paths                                                                                                                                                                                                                                          |
| `run`                | **yes** | `{script: "policy/train.py", args?: [≤32], environment?: ".venv", timeout_seconds?: ≤600}` | same — `<venv>/bin/python -- <script> <args…>`; script confined to the workspace                                                                                                                                                                                                                                                                                          |
| `test`               | **yes** | `{target?: "tests", environment?: ".venv", timeout_seconds?: ≤600}`                        | same — `<venv>/bin/python -m pytest -q -- <target>`; target confined                                                                                                                                                                                                                                                                                                      |

Rules: a workspace directory counts as a venv only when it carries a `pyvenv.cfg` AND its
interpreter resolves OUTSIDE the linked folder (every venv links or copies the base
interpreter; a repo can commit an executable at `.venv/bin/python`, and that is workspace
content, never run — not even by the ungated probe). `stdout_tail`/`stderr_tail` ≤ **16 KiB**
each (tail), `exit_code` verbatim, `ok` = exit 0; a refused action answers `{ok:false, exit_code:null, reason}`; every tool returns a
dict, never raises; the child runs with `cwd` = workspace, a scrubbed environment (`PATH`,
`HOME`, `LANG`, `TMPDIR`, `VIRTUAL_ENV`) and `start_new_session`; a timeout kills the process
group. No network at LAUNCH of the server (ADR-031) — `install` reaching PyPI is the USER's pip
under the amendment. The four gated tools declare `timeout_seconds: 630` in the allowlist (the
cloud dispatch bound; above the server's own 600 s cap, so the cloud never reports TIMEOUT
while a child still runs).

## 5. SOL tools and the approval card

- `code.resolve_environment` (in-process, read-only; params `{}`): `{environments: [{name,
source_files, requirements: [{name, specifier, source_file}]}], conflicts: [Warning…],
split: bool}`. Not gated.
- Bridge tools `code.create_environment`, `code.install`, `code.run`, `code.test`
  (`requires_confirmation: true` from the allowlist): the cloud preview (`bridge/previews.py`)
  calls `code.plan` with the same args and renders the exact command in bounded rows with
  its working directory and plan fingerprint. A failed or oversized plan is refused.
  The gate re-plans at approve time; a one-use snapshot also rejects changes between
  that final preview and invocation.
- After an approved `code.run`/`code.test` with `exit_code != 0`, the API files ONE Error logging
  entry: `"<argv joined> exited <code>\n\n<output tail ≤ 3000 chars: stdout then stderr>"`
  (pytest reports on stdout, a crashing script on stderr; redacted, control characters
  dropped), author `sol`, `created_by` = the
  approving user (S5). Success files nothing.
- The tool turn the NEXT model reads carries the command's outcome, not just the gate's:
  `code.test → approved by you and applied ok; the command exited 1 — output tail: …` (≤ 400
  chars, redacted like every untrusted machine text; `exited 0` on success; `the server refused
  to run it: <reason ≤ 200>` on a refusal). Only a result carrying an `exit_code` key is a
  command's. Without it SOL could only say "applied ok" about a failed run.

## 6. Errors

`404 not_found` (non-member, unknown source), `409 bridge_offline` is NOT used here — the route
answers `probe: null` with `bridge.connected` false rather than failing; tool refusals are
tool results, never HTTP errors.

## SOLUSDEV-260 named environment observation

The existing ungated `code.probe_environment` accepts optional `environment`, a
workspace-relative virtual environment path under the same confinement and
interpreter validation as `code.install`. Omission preserves first-match
`.venv`/`venv`/`env` detection. An explicit target never falls back to another
environment; absent, invalid, escaping or untrusted target yields no venv facts.
Successful confirmed create/install re-probes that exact path before updating its
CODE record with provenance `sol`. It does not scan arbitrary machine paths or
add another environment executor. Missing/partial observations remain unavailable.

## Incremental command output — SOLUSDEV-261 completion

Existing code.run/code.test keep their exact command approval and final outcome.
During an authorized call, the owned code server reports bounded stdout/stderr
chunks using MCP progress messages. The companion forwards them through the
existing authenticated channel's extension mechanism as `tool_output` frames:
`{call_id, sequence, stream: "stdout"|"stderr", text}`. Text is at most 2,048
characters, sequence strictly increases, and at most 256 chunks/256 KiB are
accepted for one in-flight call. Output never authorizes a tool or resolves its
result; exactly one final tool_result remains required. Unknown/finished call IDs,
wrong sessions and replayed chunks are ignored. Existing ingress redaction applies.
Commands are never automatically replayed after a transport failure.

A project/owner-scoped GET `/api/v1/projects/{project_id}/sol/confirmations/{id}/output`
returns bounded incremental output for a confirmation being executed, with an
integer cursor, truncation marker and completion status. The compact confirmation
card polls while its existing approve request is pending, showing escaped plain
text before process completion. Output is ephemeral, bounded and expires; final
stdout/stderr tails and normal failure filing remain the durable outcome. No
credentials, arbitrary file reader, shell command or new approval bypass is added.

The optional `truncated` boolean (default false) on a progress frame reports sender
suppression explicitly. The receiver also marks its own byte ceiling. Both ends
buffer complete lines before redaction, suppress oversized lines rather than
splitting secrets, and flush bounded final lines on completion. Companion progress
is paced below five frames/second across calls; final and control frames do not
wait behind that progress lock.

## SOLUSDEV-317 — sandbox, generic commands, profiles

`docs/api/code-command-execution.md` adds `code.exec`, `code.process_*` and `code.profile_*`.
It extends the `code.plan` answer with `sandbox`, `profile` and `environment` for every action,
and wraps `create_environment`, `install`, `run` and `test` in the OS sandbox. The output tail
the model reads for `code.run`/`code.test` grows from 400 to 3000 characters.

### SOLUSDEV-317 Phase 4 — the probe no longer executes the venv

Superseding the `probe_environment` row in §4: the probe never starts `<venv>/bin/python`, pip
or `uv pip list` for a workspace venv. Packages come from `site-packages/*.dist-info/METADATA`
(name and version; at most 300 entries, then `truncated`), and the Python version from
`pyvenv.cfg`. A workspace venv can contain attacker-controlled `.pth` files, which would run on
interpreter start outside the sandbox and without approval
(`docs/api/code-command-execution.md` §9.1). The `probe_environment` reason text in
`integrations/mcp/code/allowlist.yaml` still says "pip list". Correcting it is a human allowlist edit.
