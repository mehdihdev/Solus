# Completion report — SOLUSDEV-202 (SOLX-03): the overlay confidence gate

**Lane:** C, built on the integration branch · **Branch:** `SOLUSDEV-69-integration-lane-orgy` · **Date:** 2026-08-14
**Sibling ticket:** SOLUSDEV-213 (SOLUS-TU-10) — the window host. See `COMPLETION_SOLUSDEV-213-tu10-guide-overlay.md`.

**Was blocked on SOL-IPC-01 (SOLUSDEV-223);** unblocked by the LANE C merge (`0d2ff57`).

## The decision this ticket exists to get right

A user shown nothing looks it up. A user shown the **wrong** control clicks it. The two failures are not symmetric, so every unknown resolves to "fall back", never to "probably here". The ticket states it as an acceptance clause: _never shows a confident wrong pointer_.

## What was built

`apps/desktop/src/renderer/src/features/overlay/`:

- **`overlayDecision.ts`** — the gate itself. Pure, side-effect free: `decideOverlayStep(input) → {kind:'annotate', box} | {kind:'fallback', reason}`. Refuses on: not in the KB (`unavailable`), no coordinates (`no_locator`), past re-verification (`stale`, TU-07), effective confidence below `OVERLAY_MIN_CONFIDENCE`, or a box that is out of the unit square / zero-area / partly outside the window (`bad_locator`). Out-of-range boxes are **refused, never clamped** — clamping relocates the annotation to somewhere plausible-looking, which is the confident-wrong-pointer failure wearing a different hat.
  `OVERLAY_MIN_CONFIDENCE = 0.6`, pinned to the panel's `TENTATIVE_BELOW` (`toolkb/guides.py`). The panel can render a low-confidence step with a visible "tentative" hedge and the user reads the hedge. A circle drawn around a control carries no hedge: it either points at the right thing or lies. So the overlay never draws anything the panel would have marked tentative.
- **`overlaySession.ts`** — the state machine over a CTR-06 `OverlayPort`. Adopts the handoff it was spawned with, turns each step into a view through the gate, and hands the guide back when it cannot point. DOM-free and Electron-free, so all of it is asserted on a machine with no CAD tool installed.
- **`GuideOverlay.tsx`** — the render site. A percentage-positioned pointer box (percentages, not pixels, so it stays on the control if the tool window resizes before the next `reposition`), a dimmed surround, and a `role="status"` step panel. `pointerEvents: 'none'` throughout.
- **`OverlayWindow.tsx`** — the composition root at `#/overlay`: preload bridge → port → session → painter. No auth guard, deliberately: it renders only what the orb hands it over the wire, never anything fetched with the user's session.

Backend, to make the gate possible at all: `ResolvedStep.locator` (`toolkb/guides.py`), `locator_of()` (`toolkb/schema.py`), and the field on `GET /api/v1/toolkb/guides/{id}` — documented in `docs/api/toolkb.md`. TU-09 stored the geometry and CTR-05 defined it, but the route dropped it ("zero overlay dependency").

## Acceptance → evidence

| Acceptance                                                        | Evidence                                                                                                                                                                                                                                                                  |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Never shows a confident wrong pointer                             | `overlayDecision.test.ts` — 10 tests, one per refusal path, including the refuse-don't-clamp case                                                                                                                                                                         |
| Annotates only a confident, located, fresh step                   | `decideOverlayStep` returns `annotate` on exactly that conjunction; asserted in flight in `overlaySession.test.ts`                                                                                                                                                        |
| Degrades to the TU-09 side panel                                  | A fallback sends `failed` to the orb (terminal on the orb side, so the panel takes the guide back) and clears the surface                                                                                                                                                 |
| Degradation is audible, not silent                                | `overlaySession.test.ts` — "tells the orb it failed…" asserts both the message and its reason                                                                                                                                                                             |
| **H2** (SOL-IPC-01): inbound messages bound to the active handoff | `mine(id)` guard; four tests forge `advance`/`reposition`/late messages for a foreign handoff via the raw port (the stub always stamps its own id, so only a hand-built message can impersonate)                                                                          |
| **M7** (SOL-IPC-01): untrusted step text rendered as text only    | `GuideOverlay.test.tsx` — four red-team payloads (`<img onerror>`, `<script>`, `<svg onload>`, `<iframe>`) asserted to render as literal characters with **no** elements created and no `window.__pwned`. This is the render-site test SOL-IPC-01 recorded as still owed. |
| The locator reaches the wire at all                               | `packages/api/tests/toolkb/router_test.py::test_get_guide_exposes_the_locator_the_overlay_needs`                                                                                                                                                                          |

**45 tests** across the five new files (10 decision · 12 session · 7 overlay · 5 window · 11 TU-10 host).

One more bound worth naming: CTR-06 caps an IPC string at 2000 characters, so the step panel is `maxHeight`-bounded with `overflow: hidden` — 2000 unbounded characters would grow the panel up the screen and blanket the tool the user is trying to look at. Asserted in `GuideOverlay.test.tsx`.

## Delegated judgement, and one contract gap worth a human decision

- **A fallback sends `failed`, not `reclaim`.** CTR-06 types `reclaim.reason` as `HandoffEndReason`, whose four values — `completed` / `user_dismissed` / `focus_changed` / `tool_closed` — are all about the **user** or the **tool**. None of them describes "the KB has no coordinates for this control", and sending one that does not fit would have the orb narrate something untrue to the user. `failed.reason` is the free-form field, is terminal on the orb side too, and is exactly the field SOL-IPC-01's M7 note already treats as untrusted display text.
  **The gap:** CTR-06 has no message for "this _step_ cannot be overlaid, but the handoff continues". Because `failed` is terminal, the first step without coordinates ends the overlay for the rest of the guide — and today that is almost every step, since vendor documentation carries no geometry. The overlay is therefore correct but rarely visible until TU-03's visual path populates locators. Adding a non-terminal `degraded` message is a **tier-2 contract change** and is a human call; I did not make it.
- **Confidence is not on the wire.** `spawn` carries no confidence and no guide id, so the overlay window cannot look one up. The orb is the side that resolved the guide and therefore the side that holds the KB number, so a locator it chose to send is one it vouched for — `OverlayWindow.tsx` supplies `ORB_VOUCHED` and the structural half of the gate still bites. That is one named constant, and it is the single line that changes if CTR-06 ever gains a confidence field.
- **The `stale` input is wired but unsupplied** in production for the same reason (`staleFor` defaults to `false`). The route now returns `stale` per step, so the orb-side driver can pass it through when it is built.

## ⚠ Harness: the H10 Stop gate can no longer pass on this branch

`.claude/hooks/stop_validation_gate.sh:41` runs the full suite as `twrap 600 … pytest -q` — a **600-second ceiling**. After the lane merges the suite takes **~631 s**, so the gate kills pytest at roughly 68 % and reports FAILED with no summary line and no named failures. The report in `.claude/state/last_validation.md` is a wall of green dots that simply stops.

This is a timeout, not a defect. Verified by running the suite in three slices, each under the ceiling:

| Slice                                                          | Result                               |
| -------------------------------------------------------------- | ------------------------------------ |
| `integrations reasoning livebench packages/companion`          | 933 passed, 3 skipped (22 s)         |
| `packages/api/tests` — first 79 files                          | 1021 passed (295 s)                  |
| `packages/api/tests` — remaining 79 + `contracts/` + `toolkb/` | 1479 passed, 4 skipped (314 s)       |
| **Total**                                                      | **3433 passed, 7 skipped, 0 failed** |

Baseline before these merges was 3264; +169 is LANE D's toolkb tests plus this ticket's route test. Re-run under the root `.env` exported (the env-sensitive subset — config, sharing, main, security, toolkb router): 63 passed, matching the clean-shell result.

**A human needs to raise that 600 to ~900**, or split the gate's pytest invocation. Agents may not edit `.claude/hooks/` (H1) and `SOLUS_DISABLED_HOOKS` is a human-only control, so this is flagged rather than fixed. Until it is raised, every session on this branch will end on a red gate that says nothing about the code.

## Open for a human

Same two as TU-10: no production caller spawns a handoff, and nothing detects the tool window's bounds. Both halves of the wire and both ends of the window now exist; the trigger and the OS-level window detection are not in either ticket's text.
