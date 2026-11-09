# Wireflow — first-run onboarding ("SOL walks you in")

**Ticket:** SOLUSDEV-323 · replaces the About → Connect → Build flow (FND-08, SOLUSDEV-152) ·
design canvas: "Solus Onboarding Redesign" (prototype + flow map/motion spec) ·
API: `onboarding_step` in `docs/api/API-implementation.md` (GET/PATCH `/users/me/settings`) ·
related: `sol-window.md` (§A summoning, §D screen setting), `settings.md` (Needs attention).

## Layout

One full window. Header (64 px, the window's drag region): on macOS the traffic lights alone at the
left, moved down to centre in this header while onboarding is open (no logo — SOL's orb is the brand,
with a quiet SOLUS under it) · **progress rail** (six segments, labels
`MEET · PROJECT · VOICE · ACCESS · CONNECT · BUILD`; the current segment is half filled, earlier ones
full) · the user's email · **Skip setup** (from step 2 on; finishes onboarding, same as completing).

Body: a 440 px **SOL column** on the left and the **stage** on the right.

- SOL column: the **orb** (persists across steps, never remounts) above SOL's lines for the step: a
  mono caption (`SOL · LISTENING`, …), a headline and one or two body lines. The lines enter with the
  standard rise (Motion).
- Stage: the step's controls, then a footer row with **Back** (from step 2) and the primary action.

Orb states: `big` (Meet) · `idle` · `listening` (Project while the description is non-empty; Connect
once a tool is connected) · `small` (Access onward) · `working` (Build while syncs are in flight).

## Steps

Saved step names (server): `meet → about → voice → access → connect → build → done`.
A reload or another machine resumes at the saved step; an unreachable API runs the flow locally.

1. **Meet** (`meet`). SOL: "Hi — I'm SOL." Stage: three cards — _Reads your whole robot_, _Sees what
   you're stuck on_, _Catches what breaks between worlds_ (cross-domain checks — the product core; the
   mouse-and-keyboard pitch joins when the ADR-041 drive bridge ships) — and **Let's set up**.
2. **Project** (`about`). SOL: "What are you building?" Stage:
   - the description textarea (`aria-label="Project description"`);
   - **Or start from** example chips that fill the textarea (examples, not template robots — nothing
     is created from them);
   - **Worlds I'm hearing**: four domain chips (Software, Electrical, Mechanical, Runtime) that light
     up as the text mentions them. A keyword heuristic, phrased as hearing — never "detected";
   - **Project name**: an editable field holding the name the project WILL get. It follows the
     description (`deriveProjectName`) until the user types in it; then their name sticks (trimmed,
     80 chars max; blank falls back to the description), with a **Use description** reset. Picking
     an example resets it to follow. If Connect already created the project, the build renames it
     (`PATCH /projects/{id}`, best-effort).
     Primary: **Continue** (or **Skip — name it later** while empty).
3. **Voice** (`voice`). SOL: "How should I talk to you?" Stage: two choice cards, **Guide** and
   **Expert** (radio semantics, the `sol_mode` setting, ADR-016), and a preview card answering one
   fixed question in the chosen voice; switching cross-fades the answer. Primary: **Use Guide/Expert**.
4. **Access** (`access`). SOL: "Want me to see what you see?" Every switch starts off.
   - **See your screen** — the `screenIntelligence` setting (sol-window §D). When on and the capture
     capability is not `available`: the platform message and **Open System Settings** (macOS opens
     main's own pane; never a renderer URL) · **Recheck**. When available: "Screen access granted".
   - **Use your mouse and keyboard** — shown only when the desktop build has the drive bridge
     (SOLUSDEV-319 / ADR-041); disabled until _See your screen_ is on; labelled BUILD MODE.
   - **Summon me from anywhere** — "Double-tap Ctrl in any app. Try it now." Two key caps. A real
     summon (main's `sol:summoned` push) presses the caps, opens the real SOL window and ticks the row
     ("That's it — I'm one double-tap away"). **Show me** opens the SOL window as a fallback. When the
     hotkeys are off or the hook is unavailable, the row shows the hotkey status message instead of
     the practice.
   - Outside the desktop app (browser preview) the step shows one line: these live in the desktop app.
     Footer: "Change any of this in Settings › SOL" · **Continue** (or **Not now — continue** while
     screen access is off).
5. **Connect** (`connect`). SOL: "Plug in your tools." The stage opens with a suggestion line from the Project
   step's worlds ("From what you told me, start with GitHub and KiCad."). Stage: the live catalog as tiles on an ellipse around a small orb (up to 8; further tiles
   in a grid below). Each tile: logo/monogram, name, live status (connect wizard state), and
   `SUGGESTED` when its domain was heard. Clicking opens the real connect wizard (or local-bridge
   guidance). A connected tile glows in its domain colour and a wire draws from the orb to it.
   Footer: `N CONNECTED · 2+ RECOMMENDED` / `— READY` · **Skip for now** (while < 2) · **Build my
   graph** (enabled at 2+). Connections never gate the workspace (FND-08).
6. **Build** (`build`). SOL: "Building your graph." Stage: the graph panel (nodes in the domain
   colours of the REAL sources, edges drawing in, capped for legibility) and one row per real source
   whose detail is the real sync state (shimmer while pending → the real entity/relation counts or
   the real error). Done: the summary line (real entity count), a _First thing to try_ card
   ("double-tap ctrl and ask …") and **Open workspace**. No sources: the graph panel reads "Your
   graph draws itself here as your sources sync." and the summary says no sources are syncing yet.
   Nothing is fabricated.
7. **Land.** Open workspace persists `done`, navigates home and shows the one-time SOL hint pill
   ("I'm here whenever — double-tap ctrl from any app", dismissable, auto-hides).

## Motion

- Enter: rise 14 px + 6 px blur → 0, 700 ms, `cubic-bezier(.2,.8,.2,1)`; stagger 80–120 ms
  (caption → headline → body → controls → footer).
- Spring `cubic-bezier(.34,1.56,.64,1)`, 350–500 ms: switches, chips, tiles, checks.
- Orb: ignites once on first mount; size changes ease over 900 ms; breathing 4.4 s idle, 1.3 s
  listening, 0.9 s working (halo 2.2 s).
- Connect wire: `scaleX` 0 → 1, 800 ms. Build: nodes every 180 ms, edges every 120 ms.
- Transform / opacity / filter only, CSS keyframes only (no scripted frames).
- `prefers-reduced-motion: reduce`: every animation and transition is instant; the orb is still.

## Failure paths

- API unreachable: flow runs locally; steps re-persist on the next successful write.
- Capture unavailable (Wayland, permission denied): the platform message, never a fake grant.
- Hotkeys unavailable: the summon row shows the hotkey status message and keeps **Show me**.
- Workspace unlinked at Connect: the wizard reports its honest, retryable error.
