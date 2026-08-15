# COWORK QA — the Guide overlay: TU-10 (SOLUSDEV-213) + SOLX-03 (SOLUSDEV-202)

End-to-end test plan for the guide overlay window and its confidence gate. Written for a tester with the running application and this file only.

## Read this first — what is and is not reachable from the UI

These two tickets build the overlay **window** and the decision that governs what it draws. Nothing in the shipped UI spawns an overlay yet: the affordance that starts a handoff ("show me in the tool") and the OS-level detection of the CAD tool's window bounds are in neither ticket's scope, and are flagged as open in both completion reports.

So sections 1–3 below are **fully testable today**. Section 4 is the overlay flow itself and is testable only via the developer console hook described there. Section 5 is regression. Please run all five and mark section 4's steps N/A only if the console is unavailable to you.

## Required setup

- [ ] Solus API running locally (`packages/api`) with a migrated database (`make db-up`, then the API).
- [ ] Desktop app running under Electron (`pnpm dev` in `apps/desktop`). A browser preview is fine for sections 1–3.
- [ ] A signed-in, onboarded user with at least one project.
- [ ] The KiCad tool knowledge ingested (the TU-02 ingestion), so guide steps resolve against a non-empty KB. Without it every step is `available: false`, which is a valid but less interesting test — do section 2 both ways.

---

## 1. The guide API returns geometry

1. [ ] Call `GET /api/v1/toolkb/guides/kicad.eeschema.first_schematic?version=9.0.4` with a valid bearer token.
       **Expected:** `200`, and **every** entry in `data.steps` has a `locator` key.
2. [ ] Inspect the `locator` values.
       **Expected:** each is either `null` **or** an object with exactly `x`, `y`, `w`, `h`, every value between 0 and 1 inclusive. No other keys. No pixel values, no image, no URL.
3. [ ] `null` on most or all steps is **correct, not a bug** — vendor documentation carries no coordinates. Record how many steps have one.
4. [ ] Call the same route with no `Authorization` header.
       **Expected:** `401`. Geometry is not public.
5. [ ] Call with `?version=not-a-version`.
       **Expected:** `422 invalid_version`.

## 2. The side panel is unchanged by all of this

The Guide panel (TU-09) must ignore geometry entirely.

1. [ ] Open the Guide panel and step through the KiCad walkthrough.
       **Expected:** identical to before — narration in your SOL mode, invocation shown as a shortcut or menu path, tentative badge on low-confidence steps.
2. [ ] With the KB **empty** (fresh database, no ingestion): every step still renders its authored narration with the honest "isn't in the knowledge base yet" note.
       **Expected:** no crash, no blank panel, and **no** step claiming a control it cannot resolve.
3. [ ] Switch SOL mode (Guide ↔ Expert) mid-walkthrough.
       **Expected:** narration switches with no network round-trip.

## 3. The overlay route exists and is inert on its own

1. [ ] In the running app, navigate to the hash route `#/overlay` directly.
       **Expected:** a completely blank surface. No error screen, no "not found" redirect, no console exception.
2. [ ] Same route in a plain browser preview (`pnpm build`, serve `out/renderer/`), where there is no Electron preload.
       **Expected:** still blank, still no exception. The overlay degrades to nothing rather than throwing.

## 4. The overlay itself (developer-console flow)

The overlay window subscribes to the CTR-06 wire. To drive it without the not-yet-built trigger, open the overlay window's devtools console and post messages on the bridge.

Setup: with the app running, open `#/overlay` and its console.

1. [ ] **It draws for a confident, located step.** Send a `spawn` whose `step.control.locator` is `{x:0.25,y:0.5,w:0.2,h:0.1}`.
       **Expected:** a bordered box appears at 25% across / 50% down the window, 20% wide and 10% tall, with the surround dimmed and a step panel in the bottom-left showing "Step 1 of N", the title, and the instruction.
2. [ ] **Click-through.** With the box on screen, click where the overlay is.
       **Expected:** the click reaches whatever is behind the overlay. The overlay never takes focus and never appears in the taskbar/dock switcher.
3. [ ] **Resize the window** while the box is shown.
       **Expected:** the box stays on the same proportional spot — it is positioned in percentages, not pixels.
4. [ ] **It draws NOTHING for a step with no locator.** Send a `spawn` whose `step.control.locator` is `null`.
       **Expected:** no box, and the surface clears. On the wire back to the orb you should see a `failed` message with `reason: "no_locator"`. **A guessed box here is a test failure of the most serious kind** — the whole ticket is "never a confident wrong pointer".
5. [ ] **It refuses a box that runs outside the window.** Send `{x:0.9,y:0.9,w:0.5,h:0.5}`.
       **Expected:** no box, `failed` with `reason: "bad_locator"`. Specifically it must **not** draw a shrunk-to-fit box — refusing and clamping look similar on screen but clamping points at the wrong thing.
6. [ ] **It refuses a zero-area box.** Send `{x:0.5,y:0.5,w:0,h:0}`. **Expected:** no box, `bad_locator`.
7. [ ] **Dismiss clears the surface.** With a box shown, send `dismiss`.
       **Expected:** the surface goes blank immediately. Then send an `advance` for the same handoff — **expected: nothing happens**, the handoff is over.
8. [ ] **Foreign handoffs are ignored (security).** With handoff `h1` live, send an `advance` naming handoff `h-other` with an obviously different title.
       **Expected:** the overlay does not change. A second `spawn` while `h1` is live must also be ignored — the first spawn wins.
9. [ ] **Hostile step text is text (security).** Send a step whose `title` is `<img src=x onerror="window.__pwned=1">`.
       **Expected:** those characters appear **literally** in the step panel. Then check `window.__pwned` in the console — **expected: `undefined`**. No image element, no script execution. Repeat with `<script>alert(1)</script>` and `"><iframe src="https://evil.example"></iframe>`.
10. [ ] **Malformed messages do not crash it.** Send a message with an unknown `type`, and one missing `handoffId`.
        **Expected:** the message is rejected by the wire's parser; the overlay keeps working and the window stays up.

## 5. Regression — nothing else moved

1. [ ] Sign in, onboard, open a project, navigate every screen (Home, Overview, Context Model, Live Bench, Team, SOL).
       **Expected:** unchanged.
2. [ ] The detached orb window (`#/orb`, SOLX-02) still detaches and re-attaches.
       **Expected:** unchanged — the overlay is a _second_ extra window and must not disturb the first.
3. [ ] Quit the app with the overlay route open.
       **Expected:** clean exit, no orphaned window, no hung process.

## Failure paths worth exercising

- [ ] API down while the Guide panel is open → honest error state, no fabricated guide.
- [ ] Overlay route opened with the API down → still blank, no exception (it never fetches).
- [ ] Two projects, two users: guide content is shared KB and cross-tenant **by design** (see `docs/api/toolkb.md`), but confirm no project-scoped data leaks into the overlay — it should show only what was sent on the wire.
