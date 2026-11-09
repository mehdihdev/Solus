# Completion note — SOLUSDEV-319 follow-up, ADR-041 drive slice 3b (helper as an XPC agent)

Branch `SOLUSDEV-319-kicad-embedded-symbol-compare` (kept there at the human's request). Nothing pushed.

## Governing decisions and docs

- DECISIONS.md ADR-041 amendments:
  - C1: the slice 3 caller check was bypassable.
  - 3b: 440eb8fe.
  - 2026-10-28 XPC: e525372c, which supersedes the C1 and 3b transports.
- `docs/architecture/sol-drive.md`:
  - §2 Caller, §2.1 (agent, residuals), §3 (relay), §5 (packaging, bundle seal, main and the agent, companion environment), §6.
  - Commits: 494e783a, ecd6eb65, bb314b0b, 1f8319f3, 9e886437.
- No API route or wireflow changes. The Settings row follows the slice 3 patterns.

## History, for review

1. **Socket design, first attempt** (494e783a…11505aeb). A launchd agent on a Unix socket, checking the peer's `LOCAL_PEERTOKEN` plus a session token. The security review **disproved** it, and I reproduced the PoC on this machine:
   - macOS answers the peer token for the socket's _current_ process, so send-then-exec of a signed binary passes.
   - A squatted socket leaked the token.
2. **XPC redesign** (e525372c…b0b5c386), approved in-chat:
   - Mach service, with the Solus.app requirement checked per message against the send-time audit token. Exec changes the pidversion, so a stale token fails; verified here.
   - Solus.app main is the only client, through a Node-API module.
   - The companion relays over its stdio pipe to main.
   - Hardening:
     - packaged companion environment allowlisted;
     - fuses locked and read back;
     - no `allow-dyld-environment-variables` and no `allow-unsigned-executable-memory`;
     - the packaged command line allowlisted on macOS.
3. **Review rounds:**
   - **First XPC security review:** FAIL. C1 confirmed closed, but HIGH-1 open (a relocated copy with swapped companion files) → own-bundle seal check, `bundle_modified` (137294c5, 1f8319f3).
   - **Re-check:** PASS. Two MEDIUMs fixed:
     - no replay of `act` after an interruption;
     - the client's hardened runtime required.
   - LOWs fixed in the same pass (1e31edfb, 6a501259).

## Built (final state)

- **Agent** (`apps/desktop/native/solus-input`):
  - XPC listener `com.solusforge.solus.input.agent` with `setConnectionCodeSigningRequirement` (Solus.app + Developer ID + entitlement exclusions + `CFBundleVersion` floor) and a hardened-runtime client check.
  - Per-request ids and `cancel(id)`; a queued request that is cancelled replies `stopped`.
  - Serial work. Idle exit after 60 s, decided atomically. Drain exits after the send barrier.
  - Own signature checked at start.
  - Release accepts only `serve`; debug accepts only argv commands.
  - The plist is on demand (MachServices, no KeepAlive).
- **Native module** (`apps/desktop/native/solus-input-xpc`):
  - `request(json, timeoutMs) → {id, promise}`, `cancel(id)`, `checkOwnBundle()`.
  - The agent's requirement is set on the client.
  - Retries once after an interruption, and only for `trust`, `identify` or `capture`, never `act`.
- **Companion:**
  - The `drive_request` / `drive_reply` / `drive_cancel` relay over stdio. Socket client and session code removed.
  - The stdin limit is 25 MiB, but only for lines that start `{"type":"drive_reply",`.
  - PyInstaller pinned to 6.22.3 (not yet built with it).
- **API:** `agent_unavailable` code and sentence. `bad_token` and `caller_untrusted` are retired and now normalise to `unknown`.
- **Desktop main:**
  - XPC and dev transports.
  - The relay answers only the drive child it spawned, only for identify/capture/act, only with `--within` equal to the checked workspace, one call at a time, with argv and reply caps.
  - SMAppService registration while the setting is on and the helper is installed.
  - Own-bundle check at launch and at every drive spawn, failing closed. Unavailable reason `bundle_modified`.
  - Packaged companion environment allowlist.
  - Startup guard: an argv allowlist on macOS; Linux and Windows keep a switch denylist.
  - `afterPack` fuse read-back; Login Items link.
- **Renderer:** the Login Items approval card, the "not installed correctly" note, and the `bundle_modified` sentence.

## Tests

- Swift: 75 core + 17 XPC.
- Native module: 7 (Node).
- Companion: 480.
- API drive: 196.
- Desktop vitest: 5,953 across 553 files.
- Fuse script: 6.
- typecheck web and node clean. eslint shows no new problems; there are pre-existing errors in files this work didn't touch.

## Decisions under delegated judgment

- **Agent lifecycle:** it depends only on "setting on + helper installed", not on the active project, so it doesn't churn on project switches.
- **Run deadline:** main's per-call deadline is 30 s.
- **Startup guard:** Linux and Windows keep the switch denylist (no drive there, and AppImage needs `--no-sandbox`).
- **Entitlements:** `allow-unsigned-executable-memory` dropped along with the dyld entitlement (Electron's own defaults use only `allow-jit`). If a signed build crashes in JIT, restore it first.
- **Hardened-runtime check:** reads the client by pid, because the audit-token accessors are private. Identity itself is still per-message by audit token.

## Accepted residuals (also in sol-drive.md §2.1)

- **Bundle swap after the check:** files swapped after the own-bundle check (between check and use) are not re-checked. HIGH-1 is narrowed, not eliminated.
- **Consent in `~/.solus`:** consent and the folder registry are user-writable. A forger still needs the real Solus.app and the user's session to get a drive step.
- **Mach service squatting:** a user LaunchAgent claiming the service name first sees main's requests but cannot answer them.
- **Pid reuse:** for the hardened-runtime read, between accept and read.
- **Proxy variables:** a packaged companion doesn't get them (known limitation; a follow-up decision).

## Not verified (needs signing, notarisation and registration)

- Real Mach-service XPC and SMAppService registration.
- TCC attribution to SolusInput.app.
- The requirements, the hardened-runtime check and `checkOwnBundle` against signed builds, including a modified-file copy.
- Check duration.
- Interruption and retry with a launchd relaunch.
- Electron JIT without `allow-unsigned-executable-memory`.
- The pinned PyInstaller build.
- **Hardware QA:** `docs/qa/COWORK_QA_SOLUSDEV-319-drive-slice3b.md`, plus slice 3 flows 1–12 and 15–16 on a dev build.

## Human gates

- **Signing:**
  - set the team ID in `SolusInputShared.h`;
  - raise the `CFBundleVersion` floor past every prerelease of the first signed 3b build;
  - signing identities and notarisation (SOLUSDEV-148/149).
- **Policy and infrastructure:**
  - ratify the drive allowlist;
  - decide the event contract and frequency cap;
  - Redis lease;
  - decide on proxy variables.
- **Release:** Cowork QA; push and MR.
