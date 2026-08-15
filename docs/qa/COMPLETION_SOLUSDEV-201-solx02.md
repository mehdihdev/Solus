# Completion report — SOLUSDEV-201 (SOLX-02): the persistent SOL orb

**Lane:** C (SOLUSDEV-68) · **Date:** 2026-08-08 · **Consolidates:** SOL-04 (132), SOL-05 (133), SOL-06 (134) — all closed as superseded per the Phase 0 approval.

## What was built (desktop, `apps/desktop`)

One persistent orb replacing three planned surfaces:

- **Presence + docking:** `features/sol/MiniOrb.tsx` evolved in place (same export/props — `WorkspaceShell` untouched): always visible, click toggles an anchored chat panel, drag snaps between corners (click-suppression on drag), state in `features/sol/orbStore.ts` (Zustand, immutable, pure selectors; dock/expand/conversation-per-project persisted, runtime flags never persisted).
- **Expand-to-chat (SOL-04's acceptance):** `OrbChat.tsx` over `useSolChat.ts` + `solApi.ts` + `solStream.ts` (a pure SSE parser — chunk-boundary framing, CRLF, malformed/unknown frames dropped, tool args discarded at the parse boundary, 1MB runaway-buffer guard). Streamed tokens render progressively; **citations render only from the structured `citations` array on the message event, in a dedicated region, never linkified, 64-char display cap, never parsed from prose** (the SOL-02 obligation); collapsible tool/step trace shows tool name + ok/error only; per-project history from `GET /turns`; Guide/Do `Segmented` posts `action_mode`; `useClassifyPreview` + `ClassifyIndicator` finally wired (built for this in MO-04).
- **Detach (SOL-06's acceptance):** `main/sol-window/solWindow.ts` — the app's second `BrowserWindow`: always-on-top, frameless, window registry with `closed` teardown (the T1 pattern), loads `#/orb` (`OrbWindow.tsx`, frameless drag header, return-to-app, own auth guards; route added to `AppRoutes.tsx` by the orchestrator — the @shared touch, flagged). `attachOrbOverlayWire` on creation so the detached orb owns the CTR-06 wire. Invoke channels `sol-window:*` from constants in one module (literal-ratcheted), preload surface `solus.solWindow`.
- **CTR-06 handoff seam:** `overlayHandoff.ts` — the orb side over `window.solus.orbOverlay`: controller-generated `handoffId`, **all foreign-handoffId inbound dropped** (the SOL-IPC-01 H2 obligation), GuideStep text / `failed.reason` treated as untrusted display text (M7). Tested exclusively against `createLoopbackPorts()` + `createStubOverlay()` — no overlay window exists or is created.
- **Perf budget (SOL-05 carried forward — defined fresh, since no prototype ever existed), ratcheted in `orbPerf.test.tsx`:** idle = **zero scripted animation frames** (source ratchet: no rAF/timers in orb modules; runtime spies confirm), CSS transform/opacity only, pulse ≤ 1 animation and only while streaming/thinking, `prefers-reduced-motion: reduce` → `animation: none` (the pre-existing `sol-orb-pulse` a11y gap closed in `assets/main.css`).
- **SolScreen** is now the full-page chat reusing OrbChat; the stale "renders no chat input until the backend is wired" pin replaced with input-renders + history-loads tests.

## Acceptance → evidence

| Acceptance                    | Evidence                                                                                               |
| ----------------------------- | ------------------------------------------------------------------------------------------------------ |
| Persists across the workspace | MiniOrb always mounted (hidden only on the SOL screen, unchanged contract); orbStore persistence tests |
| Expands to chat               | OrbChat tests (streaming fold, citations region, trace, guide/do)                                      |
| Docks/undocks                 | corner-snap + click-suppression tests                                                                  |
| Detaches always-on-top        | solWindow tests (structural fakes: options, registry, teardown, wire attach); OrbWindow tests          |
| SOL-05 perf budget met        | `orbPerf.test.tsx` ratchets (0 idle timers/rAF, reduced-motion)                                        |
| CTR-06 handoff via stubs      | overlayHandoff full-lifecycle tests incl. reclaim-restores-state, failSpawn, foreign-id drop           |

## Verification

Desktop suite **739 passed** (baseline 666 → net +73), `typecheck:node` + `typecheck:web` clean, eslint clean over the diff (18 pre-existing repo-wide lint errors in untouched files — flagged, not mine). Phase-4 code + security reviews run on the staged desktop diff; findings and resolutions appended below.

## Phase-4 review findings and resolutions

Code review: WARNING (1 HIGH, 2 MEDIUM, 1 LOW). Security review: FAIL (3 HIGH, 5 MEDIUM, 3 LOW) — no CRITICAL, no tenant-isolation gap, no injection or secret. **All HIGHs and the security MEDIUMs fixed in-diff**; desktop suite 745 passing (was 739), typecheck clean.

**Fixed:**

- **SEC-H1:** the detached window now denies `window.open` (routes to the system browser) and blocks `will-navigate` off the renderer bundle — the main window's guards, on the app's most exposed surface.
- **SEC-H2:** `SOL_WINDOW_WEB_PREFERENCES` is explicit and asserted (`contextIsolation: true`, `nodeIntegration: false`, `webviewTag: false`) instead of inherited from Electron defaults; a template bump can no longer flip it silently.
- **SEC-H3:** every send carries an `AbortController`; unmount and project switches abort the in-flight stream, clear `sendingRef`, and drop the streaming flag (this also closes CR-M2's project-switch composer freeze); per-turn content is capped at 200k chars. Tested both.
- **CR-HIGH (drag):** `setPointerCapture`/`releasePointerCapture` on the orb button — a real mouse drag that leaves the 44px target no longer strands the orb mid-flight with a stale corner.
- **SEC-M2:** `render-process-gone` closes the frameless always-on-top window (no undismissable ghost).
- **SEC-M3:** all three SOL path segments are `encodeURIComponent`-wrapped; a traversal-shaped persisted id can no longer redirect a bearer-authenticated request. Tested.
- **SEC-M4:** `orbStore.resetForSignOut()` clears per-account conversation ids, subscribed to the auth store's authenticated→unauthenticated transition from lane-owned code (no @shared edit). Tested.
- **SEC-M5:** the citations region renders at most 12 tokens.

**Accepted / deferred, with owners:**

- **CR-MEDIUM (auto-scroll during streaming):** the list scrolls on item count, not on token growth — a cosmetic gap in long replies. Not fixed here (it wants a scroll-anchoring decision, e.g. "stick to bottom unless the user scrolled up"); noted for the first UI polish pass.
- **SEC-L1 (handoff is unwired):** `overlayHandoff.ts` has no production caller and the wire has no subscriber until LANE D's overlay exists — by design (CTR-06 stubs are the test path). The M7 *render-site* test is therefore still owed by whoever renders GuideStep text; recorded, not claimed as done.
- **SEC-L2/L3, CR-LOW:** project-name chip visible pre-auth in the detached window, `void detach()` swallowing a rejection, and an `act()` warning in a MiniOrb test — cosmetic; noted for the polish pass.
- **SEC test #9 (backend cross-team 404 on the conversation endpoints):** already covered — `test_sol.py::test_cross_tenant_isolation` plus SOL-01's `test_cross_tenant_message_post_is_denied`.

## Deviations / flags for humans

- **`routes/AppRoutes.tsx` (@shared)** received the two-line `#/orb` route (import + `<Route>`), applied by the orchestrator after H12 correctly blocked the subagent. Flagged for LANE B awareness; no other @shared renderer file touched.
- **Detach-state sync is renderer-initiated:** OS-closing the detached window leaves the main window's orb dimmed until clicked (idempotent recovery). On the QA checklist; a push-based sync can ride the T1 wire later if it matters.
- **Classify overrides affect only the preview** — the message POST body stays strict `{content, action_mode}`.
- The SOLX-04 lane's edit to `docs/api/API-implementation.md` (SSE `citations` doc line) was committed with SOLX-04; this commit carries no docs/api changes.
