# COWORK QA — SOL-IPC-01 (SOLUSDEV-223): orb↔overlay IPC push wire

Self-sufficient test plan for Claude Cowork. You need: the Solus desktop app source checkout, `pnpm install` done, and a desktop session where you can run the app in dev mode (`pnpm -C apps/desktop dev`). No accounts, no connected sources, no backend required — this feature is pure IPC plumbing.

**What shipped:** the app's first main↔renderer _push_ channel (all prior IPC was request/response). The renderer surface is `window.solus.orbOverlay`; the main-process side is a module (`attachOrbOverlayWire`) that nothing attaches yet — the orb (SOLX-02) and the LANE D overlay attach it later. So end-to-end pushes have no visible UI today; what you verify is the surface, its validation behaviour, and that nothing regressed.

## Flow 1 — the renderer surface exists and is correctly shaped

1. Launch the app in dev (`pnpm -C apps/desktop dev`), open DevTools (F12) → Console.
2. Type `window.solus.orbOverlay` → **expected:** an object with exactly four functions: `publishToOverlay`, `onOverlayToOrb`, `publishToOrb`, `onOrbToOverlay`. ☐
3. Type `window.api` → **expected:** the legacy object (oauth/bridge/folder/billing). **It must NOT contain `orbOverlay`** — the vestigial surface is frozen. ☐
4. Type `window.solus.oauth && window.solus.folder && window.solus.billing && window.solus.bridge` → **expected:** truthy (the legacy surface still rides on `window.solus`). ☐

## Flow 2 — a malformed publish is rejected at the boundary

1. In the Console run:
   `window.solus.orbOverlay.publishToOverlay({ type: 'advance', handoffId: 'h-1', step: null })`
   **Expected:** a thrown `TypeError` mentioning `step` — the message never crosses the process boundary. ☐
2. Run `window.solus.orbOverlay.publishToOverlay({ type: 'exfiltrate', handoffId: 'h-1' })`
   **Expected:** thrown `TypeError` about an unknown message type. ☐
3. Run `window.solus.orbOverlay.publishToOrb({ type: 'ready' })`
   **Expected:** thrown `TypeError` about `handoffId` (missing). ☐

## Flow 3 — a valid publish crosses cleanly

1. Run:
   ```js
   window.solus.orbOverlay.publishToOverlay({
     type: "advance",
     handoffId: "h-1",
     step: {
       stepId: "s1",
       index: 1,
       total: 3,
       title: "T",
       instruction: "Do the thing",
       control: null,
     },
   });
   ```
   **Expected:** returns `undefined`, no error, no crash. (Nothing listens in main yet — silence is the correct result.) ☐
2. Run `const un = window.solus.orbOverlay.onOverlayToOrb(m => console.log('got', m)); typeof un`
   **Expected:** `'function'` (the unsubscribe). Calling `un()` throws nothing. ☐
3. App remains fully responsive afterwards. ☐

## Flow 4 — regression: the existing invoke channels still work

1. Sign-in flow still reaches the GitHub OAuth browser hand-off (or dev bypass boots to the workspace). ☐
2. Any folder pick/reveal flow in the app still opens the OS dialog / file manager. ☐
3. Quit the app → it exits cleanly (companion teardown unaffected). ☐

## Edge cases

- Reload the renderer (Ctrl+R) after subscribing in Flow 3.2 → no console errors on reload; subscribing again works. ☐
- Open DevTools on a fresh launch and check the Console for any `[orb-overlay]` error lines during normal use → **expected: none** (that prefix only appears when a malformed message was dropped). ☐

## Deferred (not testable until a consumer exists)

- Live main→renderer push delivery and listener removal on window close: becomes user-visible when SOLX-02 (persistent orb) and the LANE D overlay attach the wire to their windows. Covered today by the unit suites (`orbOverlayWire.test.ts`, `orbOverlayBridge.test.ts`). Re-test end-to-end in the SOLX-02 QA pass.

## Cross-feature interactions to verify

- None new. The wire adds two channels (`orb-overlay:to-overlay`, `orb-overlay:to-orb`) that no existing feature uses; the checks above prove the legacy surfaces are untouched.
