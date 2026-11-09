# Completion note — SOLUSDEV-319 follow-up, ADR-041 drive slice 3 (desktop and packaging)

Branch `SOLUSDEV-319-kicad-embedded-symbol-compare` (kept there at the human's request). Nothing pushed.

Governing: DECISIONS.md ADR-041 and its amendments — H1, slice 2, M2/M3, 2026-10-27 caller check
(13ba95ab) and 2026-10-27 C1 (5d892fcd); `docs/architecture/sol-drive.md` §2, §3, §5, §6 (178db0f1 and
this handoff). No API route or wireflow changes; the Settings row follows the existing SOL section and
Needs-attention patterns.

## Built

- **Helper** (`apps/desktop/native/solus-input`):
  - caller check: parent = the companion's identifier with no arguments, grandparent = Solus.app, own
    signature pinned, Developer ID clauses; refusal `caller_untrusted`;
  - fail-closed release while the team ID is a placeholder; debug-only unsigned mode;
  - `trust [--prompt]` command; `bounds` in capture and act replies;
  - `--within` refuses the home directory and its ancestors;
  - `solus-input-launch`: disclaims responsibility and execs in place, with `PATH`-only environment;
  - `bundle/` Info.plist + entitlements, and `scripts/build-solus-input.sh` (sign/verify when identities
    are set; asserts the release helper is not unsigned-dev).
- **Companion:** `drive_window` stdout lines (four numbers only); the helper-path ancestor rule allows
  root-owned group-writable directories (`/Applications`); macOS onedir build with signing identifier
  `com.solusforge.solus.companion`; `make desktop-mac`.
- **API:** `caller_untrusted` code and sentence; the progress line pinned as a stable format.
- **Desktop main/preload:**
  - `sol.drive` setting;
  - the nested-folder rule over every linked project (segment compare after realpath; firmlink paths
    refused);
  - availability reasons, mirroring the companion's helper path rule;
  - env gating: inherited drive variables stripped, and a workspace override disables drive;
  - respawn on any relevant change;
  - outline strips outside the bound window, ref-counted per window, 150 s safety timeout;
  - hotkey quiet period;
  - consent calls from the main window only;
  - `mac.signIgnore` for the helper and companion.
- **Renderer:**
  - Settings › SOL row with the reasons, the permission tag, a development tag, and a Needs-attention card
    that asks macOS;
  - the A3 strip (`DRIVING KICAD · STEP k OF N`, progress bar, Stop → STOPPING…) under an approved
    `drive.step`.

## Tests

- Swift: 76.
- Companion: 481.
- API drive (port, tool, executor): 99. All drive files were green earlier this slice (193).
- Desktop vitest: 5811 across 547 files.
- typecheck web and node clean; ruff/mypy clean on changed Python. eslint: the only errors are in files
  this slice did not touch (`useMentionPicker*`, `Markdown.tsx`, `SolWindow.test.tsx`,
  `useSettingsData.ts`, `hardwareLocalState.test.ts`).

## Reviews

- **Code review: REQUEST CHANGES → fixed.**
  - HIGH: `/Applications` made a packaged helper unusable while Settings said available.
  - MEDIUM: stale permission rows; untested companion drive lifecycle; companion signing identifier.
  - LOW: stale outline at step start; one window ending another's outline; Stop clearing too early.
  - Also: removed raw NUL bytes from `companion.test.ts`.
- **Security review: FAIL on C1 → decided, not fixed here.** The pid-based caller check can be
  bypassed by exec'ing signed binaries into the helper's ancestry. ADR-041 amendment C1 records it and
  moves the helper to a socket agent with audit-token checks in slice 3b. Until then release builds refuse
  every call, so nothing is exposed.
- **Security review, everything else fixed:**
  - H1 (osx-sign would re-sign with Solus.app's entitlements, and the launcher forwarded the environment);
  - M1 (path rule mismatch);
  - M2 (the SOL pill could give consent);
  - M3 (home directory as workspace);
  - L2/L3/L4/L5.
- **Security review, accepted:**
  - L1 (`trust --prompt` uncaller-checked; two booleans and a prompt);
  - L6 (a renderer can keep the hotkeys quiet; the kill switch does not depend on them);
  - L7 (a strip landing on a resized window's edge can only cause an `occluded` refusal).

## Decisions under delegated judgment

- Stop needs no route: the doc already relied on the kill switch.
- The listener filter became a quiet period, because `uiohook-napi` cannot read the event marker. The
  chord policy already forbids `ctrl`.
- Progress for the strip is parsed from the existing output line (stable format), not a new event.
- Outline geometry comes from the companion over stdout. The step lifecycle comes from the renderer.
- The companion became onedir on macOS (a onefile bootloader parent would break the caller check).
- Firmlink aliases are refused rather than mapped.

## Not verified / open

- Nothing has run with real driving this slice. Hardware QA:
  `docs/qa/COWORK_QA_SOLUSDEV-319-drive-slice3.md` (and slice 2's flows 1–23).
- Signing branches of both build scripts, `SecCode` paths and TCC behaviour of the disclaim launcher are
  untested (no identities). PyInstaller under the hardened runtime may need an entitlement. Add it only
  with evidence.
- The PyInstaller onedir build itself was not run (`bash -n` only).

## Human gates

- Slice 3b (socket agent), then signing identities and the real team ID.
- Allowlist ratification.
- Event contract and frequency cap; Redis lease.
- Cowork QA; push and MR.
