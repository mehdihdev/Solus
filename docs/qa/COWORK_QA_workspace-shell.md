# COWORK QA — Workspace Shell / Home (TestDesign port)

The post-onboarding home is now the full prototype workspace: rail, topbar,
notifications, Context Model graph, Live Bench, SOL chat, Team, Settings, and
the cross-domain Alert view. Graph/bench/team content is the prototype's
strider dataset by design (real connectors replace it per feature area);
Settings and the topbar project name are wired to real state.

## Setup

- [ ] `pnpm dev:api` + `pnpm dev:desktop`, signed in and onboarded (see
      COWORK_QA_onboarding-state-machine.md). No connections required.

## Flow 1 — Shell chrome

1. Land on `/`. **Expected:** icon rail (orb, Context Model, Live Bench, SOL,
   Team, Settings), topbar `«project» / Context Model`, ⌘K search box, bell
   with a red **2** badge. Topbar shows YOUR project name if onboarding linked
   one; `strider-qd12` otherwise.
2. Rail navigation flips screens and the topbar title; active item is
   accent-highlighted.
3. Bell → notifications popover: three alerts (2 open, 1 resolved/dimmed),
   each with `domain → domain` chips. Clicking one opens the Alert view.
4. ~5 s after first landing on the graph: the **“SOL caught a cross-domain
   break”** toast appears once (never again after dismissal/View). "View
   alert" opens alert a1.
5. Sign out (topbar) → landing page; sign back in → straight to the shell.

## Flow 2 — Context Model (graph)

6. Graph renders four domain hulls (SW/EE/ME/RT), ~23 nodes, edges; hot
   cross-domain edges highlighted; nodes with alert badges (U4, motor_driver.c,
   knee gearbox).
7. Click a node → right inspector: type, subtitle, properties, connections;
   alert chip on badged nodes opens the alert. Domain chips filter; pan/zoom
   works.

## Flow 3 — Alert view

8. Open alert a1. **Expected:** severity badge, EE→SW path, the U4 change
   (before/after table), three firmware files with hot-line code blocks, the
   Why section (switches copy with SOL Guide/Expert mode), the prepared diff,
   **Apply fix** (`staged progress → resolved`), **Create issue** → ok-toast
   “Issue #144 created in strider-fw”.
9. After resolving: bell badge drops to 1; the popover row shows resolved.
   Back returns to the previous main screen.

## Flow 4 — Live Bench

10. Bench shows system channels (VBAT, I_total, can0, ctrl loop, IMU) and 12
    joint torque sparklines, ticking live; play/pause works.
11. (Anomaly path) When the anomaly is active, the τ_FL_knee 4.2 Hz overlay
    shows with an “ask SOL” affordance → SOL screen with the scripted
    diagnosis.

## Flow 5 — SOL

12. SOL screen: orb header, Guide/Expert toggle (persists to settings),
    suggestion chips, free-text input. Ask the oscillation question (chip or
    typed “why is the knee oscillating?”). **Expected:** thinking shimmer →
    diagnosis card (likely/root cause, EVIDENCE FROM THE GRAPH with domain
    chips, suggested fix) + mode-appropriate prose.
13. **Apply & flash to robot** → compile/flash/verify steps → “alert resolved”;
    alert a1 resolves everywhere (bell badge, graph badge). **Review diff**
    opens alert a1.
14. Followup chips append Q/A; Expert mode re-renders terse text.
15. ✦ tour chip → guided tour: spotlight on the bell → notification → alert
    apply-fix (or bench when already resolved); “Do it for me” clicks through;
    End tour exits.
16. Mini orb (bottom-right) appears on every screen except SOL/tour; clicking
    it opens SOL.

## Flow 6 — Team & Settings

17. Team: 4-member roster (roles, domains, last-active, YOU badge), activity
    feed; AFFECTS rows open their alert; invite modal validates email and
    shows a pending row.
18. Settings: theme preset / accent / density / SOL mode — **all real**:
    changes re-skin the app immediately and persist across reload. Connected
    integrations reflect what was connected during onboarding.

## Edge cases

- [ ] Zero-connection onboarding → shell still fully works (mock data).
- [ ] Resolved alert (a3) renders its resolved banner; a1 post-resolve shows
      the session-resolved state.
- [ ] Reload mid-session: chat resets (by design — chat is session state);
      theme/mode persist.

## Sign-off

- [ ] Flows 1–6 pass. Edge cases behave as described.
