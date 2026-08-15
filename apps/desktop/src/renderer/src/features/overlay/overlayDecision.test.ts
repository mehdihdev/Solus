// SOLX-03: the confidence gate. The ticket's acceptance is three clauses, and
// the third is the one that matters most — "never shows a confident wrong
// pointer". Pointing at the wrong control is strictly worse than not pointing:
// a user who is told nothing looks it up, a user who is told the wrong thing
// clicks it. Every branch below defends that asymmetry.
import { describe, it, expect } from 'vitest'
import { OVERLAY_MIN_CONFIDENCE, decideOverlayStep, type OverlayStepInput } from './overlayDecision'

const BOX = { x: 0.1, y: 0.2, w: 0.3, h: 0.05 }

function step(overrides: Partial<OverlayStepInput> = {}): OverlayStepInput {
  return { available: true, confidence: 0.9, stale: false, locator: BOX, ...overrides }
}

describe('decideOverlayStep', () => {
  it('annotates when the KB is confident and knows where the control is', () => {
    const decision = decideOverlayStep(step())
    expect(decision.kind).toBe('annotate')
    if (decision.kind === 'annotate') expect(decision.box).toEqual(BOX)
  })

  it('falls back when there is no locator — the common case, not an error', () => {
    // Vendor documentation carries no coordinates: TU-02 ingests locator: None,
    // so today almost every entry lands here. The panel still helps; a guessed
    // box would not.
    const decision = decideOverlayStep(step({ locator: null }))
    expect(decision.kind).toBe('fallback')
    if (decision.kind === 'fallback') expect(decision.reason).toBe('no_locator')
  })

  it('falls back below the confidence floor', () => {
    const decision = decideOverlayStep(step({ confidence: OVERLAY_MIN_CONFIDENCE - 0.01 }))
    expect(decision.kind).toBe('fallback')
    if (decision.kind === 'fallback') expect(decision.reason).toBe('low_confidence')
  })

  it('annotates exactly at the floor — the boundary is inclusive', () => {
    expect(decideOverlayStep(step({ confidence: OVERLAY_MIN_CONFIDENCE })).kind).toBe('annotate')
  })

  it('falls back when the entry is stale, however confident it once was', () => {
    // TU-07's point: stale-but-served-confident is the failure mode. A control
    // that moved in a later release is precisely a confident wrong pointer.
    const decision = decideOverlayStep(step({ stale: true, confidence: 1 }))
    expect(decision.kind).toBe('fallback')
    if (decision.kind === 'fallback') expect(decision.reason).toBe('stale')
  })

  it('falls back when the control is not in the KB at all', () => {
    const decision = decideOverlayStep(step({ available: false, locator: null, confidence: null }))
    expect(decision.kind).toBe('fallback')
    if (decision.kind === 'fallback') expect(decision.reason).toBe('unavailable')
  })

  it('falls back when confidence is unknown even though a box exists', () => {
    // A locator with no confidence is not evidence — it is an unscored guess.
    const decision = decideOverlayStep(step({ confidence: null }))
    expect(decision.kind).toBe('fallback')
    if (decision.kind === 'fallback') expect(decision.reason).toBe('low_confidence')
  })

  it('refuses a box outside the 0..1 window, rather than clamping it', () => {
    // Clamping would move the annotation somewhere plausible-looking; the whole
    // point is that a box we cannot trust is not drawn at all.
    for (const bad of [
      { x: -0.1, y: 0.2, w: 0.3, h: 0.05 },
      { x: 0.1, y: 0.2, w: 1.5, h: 0.05 },
      { x: 0.9, y: 0.2, w: 0.3, h: 0.05 } // x + w > 1: runs off the window
    ]) {
      const decision = decideOverlayStep(step({ locator: bad }))
      expect(decision.kind).toBe('fallback')
      if (decision.kind === 'fallback') expect(decision.reason).toBe('bad_locator')
    }
  })

  it('refuses a zero-area box', () => {
    const decision = decideOverlayStep(step({ locator: { x: 0.1, y: 0.2, w: 0, h: 0.05 } }))
    expect(decision.kind).toBe('fallback')
    if (decision.kind === 'fallback') expect(decision.reason).toBe('bad_locator')
  })

  it('keeps the floor at least as strict as the panel’s tentative line', () => {
    // The panel may render a tentative step with a caveat; the overlay cannot
    // caveat a circle drawn around a control. So the overlay's bar is never
    // lower than the line at which the panel starts hedging (TENTATIVE_BELOW).
    expect(OVERLAY_MIN_CONFIDENCE).toBeGreaterThanOrEqual(0.6)
  })
})
