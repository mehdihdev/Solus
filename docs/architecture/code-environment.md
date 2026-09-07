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
   SOL (Do mode) ─► code.create_environment / install / run / test ── approval card ── companion
                    (bridge tools, requires_confirmation from the allowlist;   (the `code` server:
                     the card's rows are the server's OWN `plan` argv)          argv-only, confined,
                                                                                bounded, never raises)
                                                                          │
                          exit ≠ 0 on run/test ─► ONE `.solus` Error logging entry (author sol)
```

The premise "reuse the Environment/probing work" had no referent in the repo (nothing probed
interpreters or parsed dependencies); the reuse is the I2 scan (dependencies ride the same
`scan_folder` answer, the same digest, the same redaction-safe segment shape) and the I2/I4
bridge machinery (acquirer, previews, the confirmation gate, the post-approval hooks). No second
path was built.

## Why the checker is pure and the proposal is a plan

`PinConflictChecker` is a `Checker` like every other rule: graph in, warnings out, malformed
specifiers skipped (never guessed), `packaging` doing the PEP 440 arithmetic. A CRITICAL is two
different exact pins across files; a WARNING is a pin another file's range excludes.
`propose_environments` derives the split deterministically from the conflict evidence: one
environment per requirement file that pins a conflicting package, carrying the shared,
non-conflicting files too. It is a proposal, never an action — the `code` server executes only
what the approval card showed, and the card shows the server's own `plan` argv.

## Why commands live in a fork (ADR-031, amended)

The companion relays `tool_call`s to vendored servers; it has no generic command frame, and the
allowlist is where `requires_confirmation` comes from. The `code` server is Solus-authored
(no upstream), launched by `bin/launch` with a scrubbed environment and hash-pinned deps, and its
gated tools assemble argument lists from validated arguments: package names must be PEP 508
(no leading `-`, no URLs, no paths), scripts and targets must resolve inside the workspace,
timeouts are capped, output is tailed. The amendment records that installing into the USER's
venv is the user's pip under their approval — never Solus's runtime fetching code at launch.

## S5, finally

`confirmations.decide_confirmation` already ran the confirmed command; a non-zero exit from
`code.run`/`code.test` now becomes one bounded text entry in the project's `.solus` Error
logging section (the `AUTO` half of the chip the section always advertised), through the same
`add_text_entry` SOL's own filing tool uses. Success files nothing. Filing is best-effort and
after the fact: it can never alter or lose the result.

## What was verified live

See `docs/qa/COMPLETION_SOLUSDEV-250-i3-code-environment.md`.
