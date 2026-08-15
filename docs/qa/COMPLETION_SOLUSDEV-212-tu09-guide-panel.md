# Completion report — SOLUSDEV-212 (SOLUS-TU-09): Guide side-panel (first usable Guide)

**Lane:** D (SOLUSDEV-215) · **Branch:** `SOLUSDEV-215-lane-toolkb` · **Date:** 2026-08-08
**Commits:** `28640fc` (backend), `d655f12` (frontend)
**⭐ The first genuinely usable Guide — narrated task walkthrough from KB ladder steps 1-2, zero overlay.**

## What was built

**Backend** (`packages/api/src/solus_api/toolkb/`, lane-owned):

- `guides.py` — a guide is an authored walkthrough (ordered control references + per-mode
  narration) **resolved against the live KB** at read time: each step picks up the current
  label/description/invocation/confidence from `tool_knowledge`, so the Guide compounds as the KB
  thickens. A control absent from the KB or version-mismatched → step marked `available: false`
  (never faked; the authored narration still renders). A step below `TENTATIVE_BELOW` (0.6) →
  `tentative: true`.
- `guides/kicad_first_schematic.json` — a real "wire up your first schematic" KiCad walkthrough
  over six controls that TU-02 actually ingests (place symbol → power → wire → net label →
  junction → ERC).
- Routes on the toolkb router: `GET /api/v1/toolkb/guides?tool=&version=` (list) and
  `GET /api/v1/toolkb/guides/{id}?version=` (resolved; both narrations returned so the panel
  switches SOL mode with no round-trip; unknown id → 404).

**Frontend** (`apps/desktop/src/renderer/src/features/guide/`, lane-owned):

- `guideApi.ts` — typed client over the shared `api` client (importing @shared is not editing it);
  the resolved-guide shape is local (it is not raw CTR-05, so it does not belong in shared-types).
- `useGuide.ts` — status union `idle|loading|ready|error`; **degrades to `error` on any fetch
  failure, never a fabricated guide**; aborts on unmount.
- `GuidePanel.tsx` — the side panel: title/summary + ordered steps, each showing the live KB
  label, per-mode narration (ADR-016 guide/expert, read from `useSettingsStore`), the invocation
  (shortcut `<kbd>` or menu path), and a **net-new tentative/confidence badge** (no shared badge
  primitive exists and `components/ui/` is @shared, so it lives inside the feature). A step the KB
  doesn't cover renders its narration with an honest "isn't in the knowledge base yet" note and no
  control pointer — **never a confident wrong instruction**. Loading → spinner; error → honest
  empty state.

## Acceptance (met, with one deferral)

- SOL walks a user through a real KiCad task via the side panel, **sourced from the KB**; **no
  overlay dependency**; **steps carry confidence** and render tentative below threshold. ✅
- Graceful degradation is built in — the exact property SOLX-03 will fall back to. ✅
- **Deferred: the live mount.** LANE D owns no path that can register a visible panel — there is
  no `widgets/guide/` CODEOWNERS line, no canvas renders widget manifests yet, and
  `WorkspaceShell.tsx`/`shellStore.ts` are LANE B (`@lane-workspace`). The panel is fully built and
  tested in isolation, ready to wire the moment the mount exists. **This needs a LANE 0 action**
  (see below). Flagged at Phase 0 §3.5; not a defect in this ticket's owned scope.

## Governing docs

`docs/api/toolkb.md` (extended with the `/guides` routes) · ADR-016 (SOL modes, universal setting)
· CTR-05 (steps resolve against the guarded KB) · CODEOWNERS (lane ownership). No wireflow exists
for this lane (Phase 0 flag) — panel built from the ticket text + existing feature/side-panel
patterns (`features/graph/GraphInspector.tsx`), noted as delegated judgment.

## Tests

Backend: `tests/toolkb/test_guides.py` (seed well-formedness, tool+version filtering, live-KB
resolution, unavailable-never-faked, tentative threshold, unknown-id) + router tests (auth,
resolution, empty-KB degradation, 404). Frontend: `guideApi.test.ts` (params, encoding, abort
signal), `useGuide.test.ts` (idle/loading/ready/error), `GuidePanel.test.tsx` (ordered steps,
Expert-mode narration, tentative marking, KB-absent degradation, loading, error). Backend full
toolkb suite 117+ passed, mypy clean; frontend 12 tests, renderer typecheck clean (the pre-existing
`widgets/_reference/` `@solus/shared-types` errors were a missing workspace symlink, resolved by
`pnpm install --filter @solus/desktop`).

## Flag for LANE 0 (blocks visibility only, not the build)

**Mount request:** add a `/apps/desktop/src/renderer/src/widgets/guide/ @lane-toolkb` line to
CODEOWNERS, after which `widgets/guide/widget.manifest.ts` re-exports `GuidePanel` from
`features/guide/` and manifest discovery picks it up with zero shared-file edits. Note the widget
canvas that renders manifests does not exist yet either (a separate LANE B / framework item), so
even the manifest won't make the panel live until that lands. Until then the panel is
build-complete and unit-verified but not user-visible.
