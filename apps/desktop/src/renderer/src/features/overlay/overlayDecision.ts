// SOLX-03: the confidence gate — the decision the Guide overlay exists to get
// right. Given a resolved guide step, decide whether SOL may point at a real
// control, or must degrade to the TU-09 side panel.
//
// The asymmetry that drives every branch: a user shown nothing looks it up; a
// user shown the WRONG control clicks it. So this gate is deliberately
// pessimistic — every unknown resolves to "fall back", never to "probably here".
// The ticket states it as an acceptance clause: *never shows a confident wrong
// pointer*.
//
// Pure and side-effect free so all of it is asserted without a window, a tool,
// or a display — which matters because the live-window half of TU-10 cannot be
// exercised on a machine with no CAD tool installed.
// The CTR-05/CTR-06 shape, not a local copy: this box travels from the KB row
// through `ControlPointer.locator` on the wire and must stay one type end to end.
import type { ScreenLocator } from '@solus/shared-types'

/**
 * Minimum effective confidence before the overlay will draw a pointer.
 *
 * Pinned at the panel's `TENTATIVE_BELOW` (0.6, toolkb/guides.py). The panel can
 * render a low-confidence step with a visible caveat — "tentative" — and the
 * user reads the hedge along with the text. A circle drawn around a control
 * carries no hedge: it either points at the right thing or lies. So the overlay
 * never draws anything the panel would have marked tentative.
 */
export const OVERLAY_MIN_CONFIDENCE = 0.6

export interface OverlayStepInput {
  /** Whether the control resolved to a KB entry at all. */
  available: boolean
  /** Effective (time-decayed) confidence, or null when unknown/unavailable. */
  confidence: number | null
  /** Whether the entry is past its re-verification window (TU-07). */
  stale: boolean
  /** Normalised 0..1 box within the tool window, or null when the KB has none. */
  locator: ScreenLocator | null
}

/** Why the overlay declined to point — carried to the orb so the fallback can
 *  say something true, and logged so "why no overlay?" is answerable. */
export type OverlayFallbackReason =
  | 'unavailable'
  | 'no_locator'
  | 'low_confidence'
  | 'stale'
  | 'bad_locator'

export type OverlayDecision =
  | { kind: 'annotate'; box: ScreenLocator }
  | { kind: 'fallback'; reason: OverlayFallbackReason }

/** A box must sit wholly inside the window to be drawable. Out-of-range values
 *  are REFUSED, never clamped: clamping relocates the annotation to somewhere
 *  plausible-looking, which is the confident-wrong-pointer failure wearing a
 *  different hat. */
function isDrawable(box: ScreenLocator): boolean {
  const inUnit = (v: number): boolean => Number.isFinite(v) && v >= 0 && v <= 1
  if (![box.x, box.y, box.w, box.h].every(inUnit)) return false
  if (box.w <= 0 || box.h <= 0) return false // zero area points at nothing
  return box.x + box.w <= 1 && box.y + box.h <= 1
}

/**
 * Decide whether to annotate this step or fall back to the side panel.
 *
 * Order matters only for the REASON reported, not the outcome — every failing
 * branch ends in the same place. It runs cheapest-and-most-fundamental first so
 * the reason names the real cause: "not in the KB" beats "no coordinates",
 * which beats "not confident enough".
 */
export function decideOverlayStep(step: OverlayStepInput): OverlayDecision {
  if (!step.available) return { kind: 'fallback', reason: 'unavailable' }
  if (step.locator === null) return { kind: 'fallback', reason: 'no_locator' }
  if (step.stale) return { kind: 'fallback', reason: 'stale' }
  // Null confidence is not "fine", it is unscored — a box nobody vouched for.
  if (step.confidence === null || step.confidence < OVERLAY_MIN_CONFIDENCE) {
    return { kind: 'fallback', reason: 'low_confidence' }
  }
  if (!isDrawable(step.locator)) return { kind: 'fallback', reason: 'bad_locator' }
  return { kind: 'annotate', box: step.locator }
}
