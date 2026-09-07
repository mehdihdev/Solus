# Completion report — SOLUSDEV-250 · INTEGRATIONS I3 — The "VSCode item", properly named

Branch `SOLUSDEV-250-code-environment`, **stacked on `SOLUSDEV-251-sol-in-tools` (which stacks
on `SOLUSDEV-249-local-folders`)** — merge order I2 → I4 → I3. I3 extends I2's `local` server
scan and reuses I4's bridge previews and post-approval hooks. Not pushed; no MR opened. The
ADR-031 amendment (approved in-session by Mehdi per ADR-032) is the branch's first, dedicated
commit.

## What was built

- **Dependencies in the graph.** The `local` server's `scan_folder` now parses
  `requirements*.txt`, `pyproject.toml` (`[project]` deps + optional deps) and `environment.yml`
  (conda + nested pip) into bounded `dependencies` entries; the local-folder connector lands one
  `python_requirement` node per (source file, package) with a `requires` edge from the clone.
- **Conflict detection.** `checkers/environment.py::PinConflictChecker` (pure, registered in the
  default roster, `packaging` for PEP 440): CRITICAL when two files pin different exact versions
  (Isaac `torch==2.1.0` vs policy `torch==2.3.0`), WARNING when a pin falls outside another
  file's range; malformed specifiers are skipped, never guessed.
- **The proposal.** `propose_environments` (pure): one environment per conflicting requirement
  file (carrying the non-conflicting files), otherwise one `default`. Served by
  `GET /projects/{id}/code-environment?machine_id=` (with a live interpreter/venv probe over the
  caller's bridge) and by the read-only SOL tool `code.resolve_environment`.
- **Acting, through the gate only.** The Solus-authored `code` server (`integrations/mcp/code`):
  `probe_environment`, `plan` (reads) and the gated `create_environment`, `install`, `run`,
  `test` — argument lists assembled from validated arguments, workspace-confined, scrubbed
  child environment, timeouts, tailed output, never raises. The approval card's rows are the
  server's OWN `plan` argv (`bridge/previews.py`), so what is shown is what runs.
- **S5 — failures reach Error logging.** After an approved `code.run`/`code.test` exits
  non-zero, `confirmations._file_failure` files ONE entry (`<argv> exited <code>` + stderr
  tail, author `sol`) into the project's `.solus` Error logging section — the `AUTO` half of that
  section's chip is now true. Success files nothing; filing is best-effort after the fact.
- **Desktop.** "Code environment" row under Connected accounts › Software (probe status, conflict
  count) with a Details modal (interpreter, venv, requirements, conflicts, proposal) and "Ask SOL
  to set it up". The folder card's "Open in editor" rename landed in I2.

## Governing docs

`docs/api/code-environment.md` (new), `docs/architecture/code-environment.md` (new),
`docs/api/local-folder.md` §4 (extended), `docs/api/solus.md` (sections), `docs/contracts/
action-gate.md`, `docs/wireflows/home.md` (Software row), DECISIONS.md ADR-031 (amended),
ADR-034 §4 (the environment-requirements input the CUDA checker "had no source for").
`docs/design/SPEC.md` is a copy of the CI file and `docs/design/screens/` does not exist — noted.

## The false premise, handled

"Reuse the Environment/probing work; do not build a parallel path": no environment probe or
dependency extraction existed (`probe` in this repo meant connector change detection or USB
identity). The reuse is real elsewhere — the I2 scan and connector, the I4 previews and
post-approval hooks, `packaging`, the `.solus` entry write path — and nothing parallel was built.

## Verified live (this Mac: real API :8001, real Electron + companion, forks materialised)

Fixture: the I2 scratch clone `rover-fw` with `requirements.txt` (`torch==2.3.0`, `gymnasium>=0.29`,
`six==1.17.0`), `isaac/requirements.txt` (`torch==2.1.0`, `numpy`) and `tests/test_policy.py`
asserting `reward > 0` with `reward = -1`.

- **Dependencies in the graph.** The companion's re-scan landed 5 `python_requirement` nodes
  under the clone (`requires` edges visible in Workspace's cross-links: `rover-fw requires torch
  ==2.1.0`, `numpy`, `torch ==2.3.0`, `gymnasium >=0.29`, `six ==1.17.0`).
- **Conflict + split.** `GET /projects/{id}/code-environment?machine_id=…` answered one CRITICAL
  `python_pin_conflict` ("'torch' is pinned differently across isaac/requirements.txt,
  requirements.txt — one environment cannot satisfy both") and `split: true` with `isaac`
  (numpy, torch==2.1.0) and `policy` (gymnasium>=0.29, six==1.17.0, torch==2.3.0). Home ›
  Connected accounts › Software shows "Code environment · 3.9.6 · .venv · 5 requirements / 1
  dependency conflict — split proposed"; Details lists the interpreters (uv 0.11.21, conda not
  found), the venv's packages, both files, the conflict with both pins, and the two-environment
  proposal.
- **SOL proposes and every command is gated.** In Do mode SOL called `code.resolve_environment`,
  explained the split and parked `code.create_environment` — the approval card showed
  `command: uv venv --python 3.12 .venv`, `cwd: .`; approve → exit 0, `.venv` on disk.
  `code.install six==1.17.0` → card `uv pip install --python .venv/bin/python -- six==1.17.0`
  → approve → "Installed 1 package". `code.install pytest` was approved by clicking **Approve**
  on the card in the desktop (the card renders the same command/cwd rows). SOL also tried a
  `code.run` with `script='-c "import subprocess…"'`; the card carried the server's
  `refused: script must be a relative path inside the linked folder` row and nothing ran.
- **Failure → Error logging (S5).** `code.test` → card `.venv/bin/python -m pytest -q -- tests`
  → approve → `exit_code 1`; ONE entry appeared in `.solus` › Error logging (author `sol`):
  the exact command, "exited 1", and the pytest tail naming
  `tests/test_policy.py::test_reward_is_positive`. The Workspace node panel shows it. Asked "did
  the tests pass, and which test failed?", SOL answered from the outcome it was handed:
  "`tests/test_policy.py::test_reward_is_positive` failed … `AssertionError: reward must be
  positive`". With the test fixed the approved run exited 0 and filed nothing (entry count
  unchanged); SOL reported "exited 0 … all of them passed".
- Screenshots in the session scratchpad: `13`–`22` (row, modal, cards, applied state, Error
  logging).

## Found in the live run (all fixed before handoff)

- The next model turn only read "approved by you and applied ok" after a run that exited 1 —
  `ToolResult.ok` is the transport, not the command. `_decision_summary` now appends the
  command's exit and an output tail (`command_outcome_text`, ≤ 400 chars, still inside the fenced
  history block); `docs/api/code-environment.md` §5 amended.
- pytest reports on STDOUT; the Error logging entry and the outcome clause kept only stderr, so
  the failing test's name was missing. Both now take the output tail stdout-then-stderr
  (`output_tail`), capped as before.
- A `uv venv` ships no pip, so `python -m pip list` failed and the probe reported an empty venv;
  it now falls back to `uv pip list --python <venv python>` (fork test added).
- The local source linked before I2's security fix carried no `user_id` in its config, so the
  on-connect resync was declined as "source belongs to another user" and surfaced as "companion
  is not connected". Re-linking from Home writes it; no shipped data is affected (I2 is unmerged).
- Desktop: approval cards render for turns streamed by THIS desktop; a card parked by another
  client shows as prose. Pre-existing behaviour, noted in the QA plan.
- The dev user's trial subscription hit its all-time trial credit cap mid-run (`trial_cap`,
  honest 402-class refusal); the dev subscription was set active locally to finish the run.

## Phase 4 review findings (all fixed before handoff)

Code review (1 HIGH): the outcome clause treated any result carrying a `reason` key as a
refusal (`local.open_in_tool` answers `reason: null` on success) → a result is a command's only
when it carries `exit_code`; test added. Security review (1 CRITICAL, 3 HIGH, 3 MEDIUM, 4 LOW):
C1/H2 — a workspace directory that merely contained `bin/python` was treated as the venv, so a
cloned repo could plant an executable that the UNGATED probe (polled by the desktop) would run →
`plan.venv_python` now requires `pyvenv.cfg` AND an interpreter resolving outside the folder;
fork tests prove a planted script is never executed and every action refuses it. H3 — command
output tails reached Error logging, the tool turn and the next prompt unredacted → `output_tail`
applies `redact_text` and drops control characters. H4 — red-team fixtures added for the three
new prompt paths (adversarial output tail and forged close token in history; a sentence in a
specifier is refused at the connector boundary, which now enforces the PEP 440 pattern). M5 —
the cloud dispatch bound (30 s default) was below the server's 600 s cap → the Solus-owned
allowlist may declare `timeout_seconds` (≤ 900), the four gated tools declare 630, a test pins
it above the cap. M6 — the desktop's 30 s poll could overlap probes → one probe per (user,
project, machine) reused for 10 s, single in-flight. M7 — refusal reasons capped at 200 chars.
L8 — the probe kills the process group on timeout. L9 — same-team teammate isolation test.
L11 — `code_environment.viewed` event. L10 (user-writable `SEARCH_ROOTS`) stays for human
ratification in the fork's SECURITY_REVIEW.md.

## Decisions under delegated judgment

- The desktop's `react-hooks/set-state-in-effect` rule fires on the repo-wide
  `useEffect(() => { void load() })` hook pattern (six untouched hooks on main trip it too);
  `useCodeEnvironment`/`useLocalFolder` now derive the idle output for inactive scopes instead of
  writing state, the remaining hit is the shared pattern, left for a repo-wide pass.
- `docs/design/SPEC.md` is a copy of the CI file and `docs/design/screens/` does not exist.

## Tests

API: `tests/test_environment.py` (8: checker + proposal), `tests/test_code_environment.py` (5:
route incl. offline/isolation, resolve tool project scoping, failure text incl. stdout, a
confirmed failing test filed into Error logging end to end), `tests/test_local_folder.py` (+3
dependency nodes), `tests/test_previews.py` (+2 `code.*` previews), `tests/test_confirmations.py`
(+1 decision summary carries the exit outcome). Forks: `integrations/mcp/code/tests` (163) and
`integrations/mcp/local/tests/test_deps.py`. Desktop: vitest for the row, modal, sections, hook,
constants, API resource and the SOL hand-off. Full API suite result: see the final section.

## Values a human must set

- None new. `make mcp-forks` (or `scripts/install-mcp-forks.sh` with `SOLUS_MCP_FORK_PYTHON`)
  must materialise the new `code` server's venv on each machine.

## Humans must sign / decide

- `integrations/mcp/code/PROVENANCE.md` reviewer sign-offs (blank), `SECURITY_REVIEW.md` (DRAFT),
  `allowlist.yaml` (draft; four gated tools with reasons).
- `Pipfile` parsing is deferred (noted in the route plan).
