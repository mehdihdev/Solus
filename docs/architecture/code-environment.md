# Architecture — The Code environment (SOLUSDEV-250 / INTEGRATIONS I3)

What the "VSCode item" became: not a launcher button but the project's Code environment as
Solus knows it — the dependencies in the graph, the conflicts the checker catches, the
environment spec SOL proposes, and the commands that run on the machine only through the
approval card. Companion docs: `docs/api/code-environment.md` (routes, tool contract, wire
shapes — authoritative), `docs/api/local-folder.md` (the scan this extends),
`docs/architecture/local-folders.md`, DECISIONS.md ADR-031 as amended 2026-09-07.

## One path, no parallel probing

```
linked folder ── local.scan_folder ──► FolderScan.dependencies ──► python_requirement nodes
      (I2's server, extended)             (validated, bounded)       clone —requires→ req
                                                                          │
                                   checkers/environment.PinConflictChecker (pure) ─► Warning
                                                                          │
                            propose_environments (pure) ─► {environments[], conflicts[], split}
                                     ├── GET /code-environment (desktop row + modal)
                                     └── code.resolve_environment (SOL tool, read-only)
                                                                          │
   SOL (Build mode) ─► code.create_environment / install / run / test ── approval card ── companion
                    (bridge tools, requires_confirmation from the allowlist;   (the `code` server:
                     the card's rows are the server's OWN `plan` argv)          argv-only, confined,
                                                                                bounded, never raises)
                                                                          │
                          failed confirmed action ─► ONE `.solus` Error logging entry (author sol)
                          successful create/install ─► probe exact target ─► CODE record
```

I3 owns environment observation and execution. The SOLUSDEV-260 integration retains the I2
scan and I2/I4 bridge machinery and adapts SOL's environment records to I3. The former
`machine` environment executor is removed; SOL uses the existing `code` tools and confirmation
path. The adapter neither launches processes nor introduces a second command dispatcher.

## Observed environments and CODE records

Repository operations extend this Code server through
`docs/api/code-git-development.md`. Their state-bound dry-run previews cover the
staged diff or exact push destination and commit; they do not reuse argv-only
environment fingerprints as proof that repository state stayed unchanged.

Arduino compilation extends the same server through `docs/api/code-arduino-development.md`.
Its first slice isolates a pinned toolchain beneath the application worktree's
virtual environment and compiles a bounded snapshot for an explicit Uno target.
Preparation and compilation use the central approval gate. Device discovery,
flashing and incremental output are separate steps; a build does not establish
device identity or physical success.

`code.probe_environment` accepts an optional workspace-relative environment path. Without it,
the probe selects the first of `.venv`, `venv`, and `env`. An explicit target never falls back;
the existing confinement and interpreter checks reject escaping paths and planted workspace
executables. Failed or malformed package reads yield no venv facts. A genuine empty package
list is valid; capped lists or shortened package strings are marked truncated.

`services/code_environment_adapter.py` translates that probe into the inventory used by
`link_environment`. The callback remains scoped to the authenticated user's team and project
bridge. Linking probes the requested name; successful confirmed create/install also probes
the exact action target before updating its CODE record with provenance `sol`. Repeated
observations update the same identity. Missing, malformed or truncated observations preserve
the existing record and report that recording is unavailable, without changing the command's
outcome.

Only observed facts are recorded. I3 supplies no host OS/architecture or venv interpreter path,
so those fields remain null. Conda names and system interpreter summaries do not establish a
complete writable environment; conda/docker environment creation and arbitrary command
execution are not supplied by this adapter. CODE records retain their own renderer and graph
identity, separate from HARDWARE CONFIG subjects.

## Why the checker is pure and the proposal is a plan

`PinConflictChecker` is a `Checker` like every other rule: graph in, warnings out, malformed
specifiers skipped (never guessed), `packaging` doing the PEP 440 arithmetic. A CRITICAL is two
different exact pins across files; a WARNING is a pin another file's range excludes.
`propose_environments` derives the split deterministically from the conflict evidence: one
environment per requirement file that pins a conflicting package, carrying the shared,
non-conflicting files too. It is a proposal, never an action — the `code` server executes only
what the approval card showed, and the card shows the server's own `plan` argv.
Plans that cannot fit the bounded card are refused. The card includes a fingerprint of the
exact argv and cwd, so presentation normalization cannot hide a changed plan. The request-local
adapter keeps at most 64 canonical-argument preview snapshots, consumes a matching snapshot
once, and re-plans before invoking the existing tool. Missing or changed snapshots refuse
execution; these checks supplement the central confirmation gate rather than granting approval.

## Why commands live in a fork (ADR-031, amended)

The companion relays `tool_call`s to vendored servers; it has no generic command frame, and the
allowlist is where `requires_confirmation` comes from. The `code` server is Solus-authored
(no upstream), launched by `bin/launch` with a scrubbed environment and hash-pinned deps, and its
gated tools assemble argument lists from validated arguments: package names must be PEP 508
(no leading `-`, no URLs, no paths), scripts and targets must resolve inside the workspace,
timeouts are capped, output is tailed. The amendment records that installing into the USER's
venv is the user's pip under their approval — never Solus's runtime fetching code at launch.

## S5, finally

`confirmations.decide_confirmation` runs the confirmed command; a failed `code` action
becomes one bounded text entry in the project's `.solus` Error
logging section (the `AUTO` half of the chip the section always advertised), through the same
`add_text_entry` SOL's own filing tool uses. Successful commands file no Errors entry. Filing is best-effort and
after the fact: it can never alter or lose the result.

## What was verified live

See `docs/qa/COMPLETION_SOLUSDEV-250-i3-code-environment.md`.

### Incremental execution output

The existing code MCP process and authenticated companion socket carry execution
output as an optional bounded progress extension (code-environment API plan).
The bridge correlates each chunk only with an active approved invocation. An
in-memory, bounded per-confirmation buffer presents output to that confirmation's
owner through the existing API service; the card reads it during execution.
Like the existing in-memory bridge registry, this stays behind a replaceable
service seam. It is command output, not robot telemetry or a Live Bench channel.

### SOLUSDEV-317 — sandbox and generic commands

Every executing tool above now runs inside the OS sandbox (macOS `sandbox-exec`, Linux
Landlock), and the plan answer carries the `sandbox` and `profile` fields. The statement that
"arbitrary command execution [is] not supplied" is superseded by `code.exec` and
`code.process_*`, specified in `docs/api/code-command-execution.md` under the ADR-031
amendment of 2026-10-18.
