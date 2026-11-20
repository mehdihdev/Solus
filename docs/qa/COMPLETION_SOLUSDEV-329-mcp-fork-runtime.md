# Completion report — SOLUSDEV-329: MCP fork runtimes on customer machines

**Branch:** `SOLUSDEV-329-more-fixes` (local, unpushed). All sub-branches are merged and deleted.
**QA plan:** `docs/qa/COWORK_QA_mcp_fork_runtime.md`.

## What was built

Solus's local MCP tools (kicad, code, local, altium, gazebo, isaac) now run from a packaged
install on any machine, with no developer setup.

- **Envs live outside the app.** Each tool's Python env is built at setup time into an owner-only
  app-data folder (`mcp-envs/<fork>/`). It is built with `venv --copies`, then
  `pip install --require-hashes --only-binary=:all: --no-deps` from the fork's committed lockfile.
  Pip uses 5 retries and a 60 s socket timeout. Nothing installs at launch.
- **Base interpreter.** The user's CPython 3.12 or 3.13, either auto-detected or chosen in
  Settings. Detection refuses the Store alias, PyPy, 3.14+/≤3.11, venvs, relative PATH entries and
  the macOS Xcode stub (without triggering its install dialog). The fallback is a consented,
  hash-pinned python-build-standalone 3.12. It is wired but switched off until hashes are added
  (see the human gates).
- **The companion trusts an env only when** its interpreter resolves inside `mcp-envs`, the folder
  is owner-only (POSIX 0700 plus uid; Windows DACL of user + SYSTEM, inheritance off), and the
  stamp matches the shipped lockfile. Otherwise the fork reports `needs_setup:<code>` and is
  never launched or silently skipped.
- **Launchers** take the interpreter only from `SOLUS_MCP_PYTHON`, which must be an absolute path.
  kicad, code and local gain Windows `launch.cmd` files. gazebo and isaac gain `platform.json`.
- **Desktop.** A new Settings section, "Python for local tools", covers detection, choice, the
  picker, setup with per-tool progress, Repair, and the managed-Python offer behind a
  main-process consent dialog. It also adds a Needs-attention card. All copy follows Guide/Expert
  mode. There are three `python_tools.*` client events, none carrying paths.
- **Dev flow.** `make mcp-forks` builds the same app-data envs through the same code. The companion
  build bundles its package data and ships no `.venv` or `__pycache__`.

## Governing docs

- DECISIONS.md: ADR-031 amendment 2026-11-19 and ADR-034 amendment 2026-11-19, both approved in
  chat and each committed on its own.
- New: `docs/architecture/mcp-fork-runtime.md`.
- Updated: `docs/contracts/local-state.md`, `docs/wireflows/settings.md`, `docs/api/API.md`,
  `PRODUCTION-LAUNCH-PLAN.md` (D4/E1), `companion-packaging.md`, `integrations/mcp/README.md` and
  `RUNBOOK.md`.

## Decisions taken under delegated judgment

Human-approved in chat:

- Managed-Python fallback.
- CPython 3.12 and 3.13 only.
- PyPI at setup.
- Windows owner-only means user + SYSTEM.
- gazebo runs on linux+darwin; isaac on linux.

Agent interpretations, all recorded in the architecture doc:

- `auto` mode means the best detected candidate, with 3.12 preferred.
- The health check runs before pip.
- Proxy variables are not passed through (a follow-up).
- A renderer-supplied path is executed only if it matches a detected candidate; any other path
  must come from main's file picker.
- `first_run` is reserved.

**Wording deviation:** the approved ADR-034 text said `config.json` "gains its first key". A `sol`
key already exists, so the committed text reads "gains a key (beside `sol`)".

## Defects found and fixed during verification

These were found on a real machine, against PyPI:

- **KiCad could never install.** `pyperclip==1.9.0` publishes only an sdist. It is bumped to
  1.11.0, and a new test, `integrations/mcp/tests/test_lock_wheels.py`, checks every lockfile
  against PyPI.
- **`provision` reported `ok` while building zero forks** when it found no forks folder. That
  affected dev desktop and `make mcp-forks`; it now fails clearly.
- **The PyInstaller build omitted `managed_manifest.json`.** It now builds with `--collect-data`.
- **Large wheels timed out**, which pip reported as `pip_failed`. Pip now retries, and dropped or
  incomplete downloads are classified as `network_unreachable`.
- **`solSettings.ts` wrote back a stale startup snapshot**, which would have erased `mcp_runtime`.
  It now re-reads before writing.

The Phase 4 reviews found no CRITICAL or HIGH issues. Every finding was fixed:

- venv bases are refused (`python_is_venv`);
- the renderer can no longer make main execute an arbitrary path;
- managed-download consent is confirmed in main;
- the Windows ACL calls declare their ctypes types, and a failure fails closed per fork;
- relative PATH entries are skipped;
- an interrupted swap recovers on the next run;
- stamp validation errors no longer escape as tracebacks;
- a cancelled or failed run keeps the "choice changed" marking;
- the attention card follows Guide/Expert mode;
- `usePythonTools` was over the complexity limit and now passes.

## Verification

**Live on macOS (arm64).** From PyPI, on python.org 3.13 and on uv's python-build-standalone 3.12:
code, local, gazebo and kicad built and passed `runtime status`. altium and isaac were correctly
skipped. Started through their real launchers, each server completed an MCP handshake: kicad
exposes 18 tools, code 25 and local 3.

**Test suites:**

| Suite                         | Result                                  |
| ----------------------------- | --------------------------------------- |
| Companion                     | 788 passed (runtime coverage 95% at T1) |
| API events                    | 100 passed                              |
| Desktop                       | 646 files, 7,173 tests passed           |
| mypy, ruff, desktop typecheck | clean                                   |

The fork suites have 66 failures, identical by test ID to `main`: arduino-cli is not installed, the
gazebo `zip()` fails on this Python, and isaac assumes Linux. None comes from this branch.

## Human gates (open)

1. **Security re-review and both devs' sign-off** for kicad, code, local, altium, gazebo and
   isaac. Each fork's launcher changed, and kicad's lockfile changed. Each `SECURITY_REVIEW.md`
   has a PENDING entry, and nothing is signed.
2. **Managed Python go-live.** Pick the python-build-standalone release and its
   `install_only_stripped` assets. Fill in the per-OS/arch SHA-256 values in
   `runtime/managed_manifest.json` and set `verified: true`.
3. **Windows.** No `launch.cmd` or ACL code has run on Windows yet (Cowork QA Flow 8).
4. **Push, MR and review**, which are human actions.

## Follow-ups (not blocking)

- **Proxy and corporate-CA support** for setup (doc §12).
- **Unrelated `lint` errors.** `pnpm lint` still fails on errors in other files that were there
  before this ticket.
- **Two untracked `.docx` files** are sitting at the repo root.
