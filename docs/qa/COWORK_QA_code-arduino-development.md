# Arduino integration QA — SOLUSDEV-261

This checklist distinguishes implementation and isolated compiler evidence from
live SOL approvals and device proof. The Code server registers Arduino probe,
preparation and compilation. The engine passes disposable host verification;
live SOL approval and physical-device steps remain separate gates.

## Current evidence

- [x] Immutable nine-archive dependency closure matches the reviewed official index.
- [x] Seventeen foundation tests pass; source lint/types pass.
- [x] Probe and preview execute no subprocess and create no files.
- [x] Missing, replaced, symlinked and non-executable CLI fixtures are unavailable.
- [x] Real Linux ARM64 CLI 1.5.1 hash matches the pinned binary in this checkout.
- [x] Real preparation preview contains 38 complete rows; the central approval
  redactor changes none of them. The runtime directory remains absent.
- [x] All nine official archives downloaded to a temporary review directory and
  verified against their exact lengths and SHA-256 checksums, without extraction.
  Eight have no links; all 21 avr-gcc internal links were inspected and pinned.

Registration checks pass through the real `bin/launch` runtime: fourteen tools,
strict invalid-argument refusal and a read-only Arduino probe. Twenty-nine focused
registration tests pass; source and registration test typing pass. The final
complete Code suite passes 315 tests with 88.21% line coverage; 222 integrated
bridge/approval/prompt tests also pass. Independent code/Python and security
reviews passed with all findings resolved. The production
Arduino runtime remains absent; registration is not live installation proof.

Independent host QA subsequently prepared the exact toolchain under
`.venv/arduino-qa`, verified 2576 regular installed files and all reviewed links
against the pinned archives, and compiled a disposable Blink fixture for Uno.
The compiler reported success, 924 bytes of flash and 9 bytes of RAM. AVR ELF
machine identity and every HEX record checksum verified; upload_result was empty.
This is host toolchain evidence, not execution through SOL or a board flash.
The QA-only generated Arduino inventory identity was retired after accidental
diagnostic exposure; no value is retained in this QA document. Do not invoke CLI
against that retired QA runtime. Product installation must keep generated
inventory metadata private. Bubblewrap namespace isolation also passed a host
availability check. The final engine proof below additionally verifies its actual
fixed sandbox mounts and real compiler execution.

## Setup for the following executable slice

1. [ ] Start this checkout's `pnpm dev:all`, sign in and select the QA project.
2. [ ] Link a disposable local sketch folder through native Home → Local folder →
   Link folder → `/home/beeboss/Solus/tmp/integration-check-kicad`. The generated
   `Blink/Blink.ino` fixture is already present alongside the KiCad project. Do not alter the
   conflicted ForgeTS tree merely to establish a test fixture.
3. [ ] Confirm probe/prepare/compile tools have actually been implemented and
   registered against `docs/api/code-arduino-development.md` before continuing.
4. [ ] Request an Uno-targeted compile in Build mode. Review the exact dependency
   installation card before approving preparation; confirm no global Arduino
   configuration or system packages change.

## Preparation and compile gates — not verified

1. [ ] Reject preparation. Expect no directories, downloads or processes created.
2. [ ] Approve a fresh preview. Expect exact pinned dependencies installed only
   under the application virtual environment, with verified readiness published
   only after completion. Repeat preparation should be a verified no-op.
3. [ ] Change a pinned file after preview. Expect stale/integrity refusal and no
   compiler launch. A fake readiness receipt must not make a toolchain available.
4. [ ] Compile the explicit `arduino:avr:uno` target. Inspect the source snapshot,
   toolchain digest and output location on the card, then approve it manually.
   Expect actual compiler output and immutable artifact hashes after success.
5. [ ] Compile a syntax error. Expect nonzero outcome, no artifact manifest and
   an Error logging entry. A returned output tail is not incremental streaming.
6. [ ] Exercise timeout/output limits and disconnected sessions. Expect owned
   process cleanup and no automatic retry or false success.
7. [ ] Try sketch.yaml/sketch.yml, symlinks, extra arguments and string booleans.
   Expect refusal before compilation, downloads or device discovery.

## Device and cross-feature gates — not verified

- [ ] Identify the board connected to the selected stable device path; never infer
  identity from `/dev/ttyACM0` or from a successful Uno-targeted compile.
- [ ] Implement and review the separate flash artifact/device gate before testing
  a physical upload. The human reviews and approves the exact device and firmware.
- [ ] Verify upload readback and physical behavior with the human. An interrupted
  started upload is unknown device state, never success or an automatic retry.
- [ ] Verify the sketch's pins/buses appear in the graph and source changes update
  the Workspace node. Verify incremental build output through its actual transport
  once implemented; do not count the final tool response as streamed output.

## Review regressions

- [ ] A replaced builds directory cannot redirect creation or publication outside
  the owned runtime; assert the external directory stays untouched.
- [ ] Replacing the CLI between verification and launch never executes its new bytes.
- [ ] A child that closes both output pipes still stops promptly on cancellation.
- [ ] Deep or numerous empty sketch directories hit a bounded refusal.
- [ ] Exit zero with an unsuccessful compiler report produces a failed outcome,
  no artifact manifest and no misleading “applied ok” history.
- [ ] Reusing verified artifacts is described as a no-op, not a fresh compiler run.

## Actual engine proof

The final disposable runtime is `/home/beeboss/Solus/.venv/a2qe`. Its `proof.json`
records verified preparation/readiness, real offline compilation, artifact identities
and reuse with `started:false`. Build ID: `a4a1ffd8-cf2b-5a82-a168-c40b8de113c6`.
ELF machine identity and Intel HEX record checksums/EOF were independently checked.
Four artifacts were published: ELF, ordinary HEX, bootloader BIN and bootloader HEX.
No artifact was uploaded to a board; artifact presence grants no flash permission.

Earlier disposable a2qa/a2qb attempts found the Bubblewrap source-mount issue;
a2qc/a2qd found exact CLI metadata/layout differences. They remain preserved QA
data. Fixes have regression coverage; do not count those failed attempts as success.

- [x] Replaced-directory, partial-copy cleanup and retry regressions pass.
- [x] Complete compiler report is validated even when the returned tail is truncated.
- [x] Cached artifact reuse starts no compiler and is described truthfully.
- [x] Actual package launcher exposes 14 Code tools, including the three Arduino tools.
- [ ] Approve preparation in SOL, then compile the linked Blink fixture through its card.
- [ ] Verify graph/editor changes and physical firmware behavior through their own gates.

## Live companion checkpoint — 2026-09-12

After restarting the task-owned development stack, SOL in Build mode invoked
`code.arduino_probe`: Linux aarch64 supported, pinned CLI 1.5.1 available, production
Uno toolchain not ready. SOL then queued `code.arduino_prepare`; the rendered approval
card contained all 38 preview rows, including destination, nine archive identities
and sources, complete sandbox argv split across three rows, configuration and plan
fingerprint. The final fingerprint was
`28c2e6cc2862768796be46fd17d5d1b52927597af9264904e94e92bd752c4861`.

The card remains awaiting the human's approval. Neither the assistant nor SOL
approved it; this proves live tool registration and preview rendering, not live
installation or compilation. Production destination: `/home/beeboss/Solus/.venv/arduino`.
The native local-folder link is also still required before SOL can compile the
Blink fixture in `/home/beeboss/Solus/tmp/integration-check-kicad`.

## Approval failure regression and recovery

The human-approved installation exposed nondeterministic ordering in the CLI's
`installed.json` tools list. All versions, archives, installed file contents and
configuration matched; ordering alone triggered `integrity_mismatch`, leaving a
complete runtime without a readiness receipt. The comparison now normalizes only
that tools collection while preserving exact records, duplicates and scalar types.

The production runtime passed full read-only closure verification after this fix.
The recovery preview has 19 rows and names only publication of the missing receipt;
it never downloads, reinstalls, compiles or accesses devices. Probe stays not-ready
until the human approves that recovery. All 322 Code tests pass on the host,
including real sandbox checks; independent code/Python and security reviews pass.

1. [ ] Ask SOL to prepare again and confirm the card says **Publish verified
   readiness receipt** and **No command, download or extraction**.
2. [ ] Approve this fresh card. Expect `changed:true`, `action:finalize_ready` and
   the verified dependency identities, then confirm a new probe reports ready.
3. [ ] Repeat preparation. Expect the already-ready no-op, not another install.
4. [x] Regression tests reject modified metadata, duplicate dependencies, scalar
   type changes, partial installs, existing receipt symlinks and replaced roots.

Never retry the consumed failed card or manually manufacture its readiness receipt.

Live follow-up: after the companion restart, the UI rendered the complete recovery
card with `dry_run:false`, **Publish verified readiness receipt**, **No command,
download or extraction**, and fingerprint
`1f8daca33e9d6177d0b9d75b3473e6e62e76af3da10758c2823171ac30664e27`.
It remains unapproved. An earlier model-selected `dry_run:true` card was rejected
without executing anything; the gate obtains its preview itself, so the action
queued for actual approval must use `dry_run:false`.

## Readiness verified after preparation

On 2026-09-12 the production `.venv/arduino/ready.json` was present. A fresh
read-only call to the owned `arduino_probe` verified Linux aarch64 support, pinned
CLI1.5.1 integrity, `toolchain.ready:true`, and an empty missing-dependency list.
Manifest identity: `0b2719d260a1715c:b1e988ae25ea94fd:f441620b201aeb37:7eb73376db862410`.
No new installation, compilation, board access or upload was performed by this
verification. This closes toolchain readiness; physical hardware remains excluded.
