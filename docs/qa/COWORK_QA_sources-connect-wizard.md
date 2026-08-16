# Cowork QA — Sources Connect Wizard (SOLUSDEV-165)

End-to-end test plan for the redesigned connect experience: catalog tiles now
open a guided **connect wizard** (Solus↔tool link animation, dynamic step
rail, one action per step) on BOTH the per-project Sources page and onboarding
step 1. This file is self-sufficient: you need the running Solus desktop app
and nothing else.

## Required setup

- [ ] Solus desktop app running (Electron build — OAuth needs the desktop
      bridge; the web renderer cannot complete OAuth and must error honestly).
- [ ] Backend API reachable and signed in (Supabase auth configured).
- [ ] A project exists and is open (e.g. "Elegoo Robot Test").
- [ ] A GitHub account with at least one repository (for the OAuth path).
- [ ] A KiCad XML netlist export file on disk (any `.xml` netlist; also
      prepare an empty `.xml` and, if practical, a >8 MB file for failure
      paths).
- [ ] Optional: integration logo files present under
      `apps/desktop/src/renderer/src/assets/integrations/` (github.svg,
      kicad.svg, …). If absent, tiles/wizard show two-letter marks — that is
      the designed fallback, not a bug.

## Flow 1 — Sources page: OAuth connect (GitHub)

1. Navigate to the project's **Sources** page. Expected: "CONNECTED SOURCES"
   list and a "CONNECT A TOOL" tile grid (GitHub, KiCad, and any other live
   connectors).
2. Click the **GitHub** tile. Expected: a centered modal (~520 px) opens with
   a pop-in animation: an "S" box and the GitHub logo (or "GH" mark) joined by
   six dots; a step rail reading **Sign in → Pick repositories → Build
   graph** with "Sign in" highlighted; instruction text; a **Connect GitHub**
   button.
3. Check SOL mode behavior (Settings → SOL mode): in **Guide** mode the
   instruction explains (mentions the browser and that Solus never sees your
   password); in **Expert** mode it is one short sentence. Mark pass if they
   differ accordingly.
4. Click **Connect GitHub**. Expected: the dots animate (travelling pulse),
   the browser opens GitHub's authorize page, the wizard shows the live label
   ("Authorizing with GitHub…").
5. Approve in the browser. Expected: wizard advances — "Linking your GitHub
   account…" still under Sign in, then the rail highlights **Pick
   repositories** and a picker lists your repositories (single-select
   dropdown).
6. Pick a repository. Expected: rail highlights **Build graph**, live label
   "Indexing \<repo\>…", spinner.
7. Wait for completion. Expected: dots turn green, headline "GitHub
   connected", real result string ("Connected — N entities indexed"), a
   **Done** button.
8. Click **Done**. Expected: modal closes; the source appears under CONNECTED
   SOURCES with account login, sync time, and entity count; the GitHub tile
   footer shows the connected state.

## Flow 2 — Sources page: committed-export connect (KiCad)

1. Click the **KiCad** tile. Expected: wizard opens with rail **Choose export
   → Build graph** — no sign-in step.
2. Click **Choose export file** and pick the netlist `.xml`. Expected: rail
   moves to Build graph, live labels ("Reading \<file\>…", "Parsing netlist &
   building the graph…"), then the done state with a real entity count.
3. Click **Done**. Expected: source listed under CONNECTED SOURCES.

## Flow 3 — Cancel mid-flight (the cancel contract)

1. Click GitHub → **Connect GitHub**; when the browser opens, do NOT approve.
2. Close the wizard with **X** (also try clicking the dim backdrop in a second
   run). Expected: modal closes immediately; the GitHub tile returns to "Not
   connected / Connect" (no stuck busy state).
3. Now approve or cancel in the browser anyway. Expected: no zombie source
   row appears under CONNECTED SOURCES after a refresh/sync — a half-made
   source is deleted in the background. EDGE: if the handshake actually
   completed before your close, the source is KEPT and listed (work is not
   thrown away) — either outcome is a pass; a lingering broken/pending source
   is a fail.
4. Repeat: start GitHub connect, reach the repository picker, close the
   wizard. Expected: tile resets to "Connect"; no dangling source in the list.

## Flow 4 — Error and retry

1. Cancel GitHub's browser page (deny authorization). Expected: wizard shows
   "Couldn't connect GitHub" with the honest reason ("GitHub sign-in was
   cancelled.") in error color, and a **Retry** button.
2. Click **Retry** and complete the flow. Expected: normal happy path.
3. Close the wizard while it shows an error instead. Expected: the tile
   footer shows the error and the indicator reads **Retry**; clicking the
   tile reopens the wizard on the error state.
4. Pick an EMPTY `.xml` for KiCad. Expected: honest error "The selected file
   is empty." (and ">8 MB" file → "too large" message), retryable.

## Flow 5 — Onboarding parity

1. Sign up / start onboarding, reach step 2 "Connect your tools".
2. Click a tile. Expected: the SAME wizard opens (identical layout and
   animation as the Sources page).
3. Connect two sources (GitHub + KiCad). Expected: "2 OF n CONNECTED — READY"
   and **Build context model** enables; "Skip for now" disappears.
4. With nothing connected, **Skip for now** must still proceed (connections
   never gate the workspace).

## Flow 6 — Offline / no-bridge honesty

1. In a web/dev renderer without the Electron bridge, click GitHub →
   **Connect GitHub**. Expected: honest error "GitHub connect needs the
   desktop app." — never a fake success.
2. With the backend unreachable (or workspace unlinked during onboarding),
   begin any connect. Expected: "Solus API unreachable — retry once you are
   back online."
3. Sources page with API unreachable: the connected list degrades to the
   offline notice; the catalog still renders (curated fallback pair).

## Flow 7 — Accessibility & motion

- [ ] The wizard is `role="dialog"` with label "Connect \<name\>"; the current
      rail step exposes `aria-current="step"`; X is labeled "Close".
- [ ] Enable OS "reduce motion": pop-in, dot pulse, and mark breathing are
      disabled; states still readable by color/checks.
- [ ] Any field named like a credential (e.g. a future connector's
      `license_key`) renders as a masked password input in the details form.

## Cross-feature interactions

- [ ] After connecting on the Sources page, the graph screen shows the new
      entities (source became a domain).
- [ ] Disconnect (Sources page row) still works and keeps synced entities;
      reconnecting via the wizard works afterwards.
- [ ] "repositories"/"documents" choose-selection button on a connected source
      row still opens the edit-selection modal (unchanged feature).
- [ ] Theme switch re-skins the wizard (tokens only — no hardcoded colors).

## Pass/fail checklist

| #   | Flow                                | Pass | Fail | Notes |
| --- | ----------------------------------- | ---- | ---- | ----- |
| 1   | OAuth happy path (Sources page)     |      |      |       |
| 2   | Committed-export happy path         |      |      |       |
| 3   | Cancel mid-flight, no zombie source |      |      |       |
| 4   | Error + retry, honest copy          |      |      |       |
| 5   | Onboarding parity                   |      |      |       |
| 6   | Offline / no-bridge honesty         |      |      |       |
| 7   | Accessibility & reduced motion      |      |      |       |
