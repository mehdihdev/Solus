// SOLX-03: the overlay half of the CTR-06 handoff.
//
// SOL-IPC-01 shipped on the explicit condition that its CONSUMERS close H2: the
// wire authenticates the WINDOW and nothing more, so binding inbound messages to
// the active handoff is this module's job. The orb side already does its half
// (overlayHandoff.ts drops foreign ids); this is the half that was still owed.
//
// Foreign-handoff cases go through the raw port rather than `createStubOrb`,
// because the stub always stamps its own handoff — only a hand-built message can
// impersonate another one, which is exactly the attack H2 describes.
import { describe, it, expect, vi } from 'vitest'
import {
  createLoopbackPorts,
  createStubOrb,
  type GuideStep,
  type OverlayToOrb,
  type ToolWindowRef
} from '@solus/shared-types'
import { createOverlaySession, type OverlayView } from './overlaySession'

const TARGET: ToolWindowRef = {
  tool: 'kicad',
  windowTitle: 'KiCad Schematic Editor',
  displayId: null,
  bounds: { x: 0, y: 0, width: 1200, height: 800 }
}

const CONFIDENT_STEP: GuideStep = {
  stepId: 'place-symbol',
  index: 0,
  total: 3,
  title: 'Place a symbol',
  instruction: 'Press A to open the symbol chooser.',
  control: {
    tool: 'kicad',
    controlId: 'place-symbol',
    locator: { x: 0.1, y: 0.2, w: 0.2, h: 0.05 }
  }
}

/** A step the KB has no coordinates for — the COMMON case today, since vendor
 *  documentation carries no geometry (TU-02 ingests `locator: null`). */
const NO_LOCATOR_STEP: GuideStep = {
  ...CONFIDENT_STEP,
  stepId: 'wire',
  control: { tool: 'kicad', controlId: 'wire', locator: null }
}

function harness(confidence = 0.9) {
  const { orb, overlay } = createLoopbackPorts()
  const views: (OverlayView | null)[] = []
  const outbound: OverlayToOrb[] = []
  orb.subscribe((m) => outbound.push(m))
  const controller = createOverlaySession(overlay, {
    onView: (v) => views.push(v),
    confidenceFor: () => confidence
  })
  // The last view that was actually PAINTED. A fallback emits the view and then
  // a null (the panel takes the guide back), so `views.at(-1)` is the clear.
  const shown = (): OverlayView | null => views.filter((v) => v !== null).at(-1) ?? null
  return { orb, driver: createStubOrb(orb), views, shown, outbound, controller }
}

describe('overlay session — handoff binding (H2)', () => {
  it('adopts the handoff it was spawned with and reports ready', () => {
    const { driver, controller, outbound } = harness()
    driver.spawn({ handoffId: 'h1', focus: null, step: CONFIDENT_STEP, target: TARGET })
    expect(controller.activeHandoffId()).toBe('h1')
    expect(outbound.some((m) => m.type === 'ready')).toBe(true)
  })

  it('ignores an advance forged for a DIFFERENT handoff', () => {
    const { orb, driver, views, controller } = harness()
    driver.spawn({ handoffId: 'h1', focus: null, step: CONFIDENT_STEP, target: TARGET })
    const before = views.length
    orb.send({
      type: 'advance',
      handoffId: 'h-other',
      step: { ...CONFIDENT_STEP, title: 'Foreign' }
    })
    expect(views).toHaveLength(before)
    expect(controller.activeHandoffId()).toBe('h1')
  })

  it('ignores a reposition forged for a foreign handoff', () => {
    const { orb, driver, controller } = harness()
    driver.spawn({ handoffId: 'h1', focus: null, step: CONFIDENT_STEP, target: TARGET })
    orb.send({
      type: 'reposition',
      handoffId: 'nope',
      target: { ...TARGET, bounds: { x: 9, y: 9, width: 10, height: 10 } }
    })
    expect(controller.target()?.bounds).toEqual(TARGET.bounds)
  })

  it('releases the handoff on dismiss and then ignores its late messages', () => {
    const { driver, views, controller } = harness()
    driver.spawn({ handoffId: 'h1', focus: null, step: CONFIDENT_STEP, target: TARGET })
    driver.dismiss('user_dismissed')
    expect(controller.activeHandoffId()).toBeNull()
    // The window is hidden, not destroyed — so the surface must be cleared, or
    // the next spawn flashes the previous handoff's pointer first.
    expect(views.at(-1)).toBeNull()
    const after = views.length
    driver.advance(CONFIDENT_STEP)
    expect(views).toHaveLength(after)
  })
})

describe('overlay session — the confidence gate in flight (SOLX-03 acceptance)', () => {
  it('annotates a confident step that has a locator', () => {
    const { driver, views } = harness(0.9)
    driver.spawn({ handoffId: 'h1', focus: null, step: CONFIDENT_STEP, target: TARGET })
    expect(views.at(-1)?.decision.kind).toBe('annotate')
  })

  it('falls back — and says why — when the KB has no coordinates', () => {
    const { driver, shown } = harness(0.9)
    driver.spawn({ handoffId: 'h1', focus: null, step: NO_LOCATOR_STEP, target: TARGET })
    const view = shown()
    expect(view?.decision.kind).toBe('fallback')
    if (view?.decision.kind === 'fallback') expect(view.decision.reason).toBe('no_locator')
  })

  it('falls back when confidence is below the floor, however precise the box', () => {
    const { driver, shown } = harness(0.2)
    driver.spawn({ handoffId: 'h1', focus: null, step: CONFIDENT_STEP, target: TARGET })
    expect(shown()?.decision.kind).toBe('fallback')
  })

  it('tells the orb it failed when it cannot point, so the panel takes over', () => {
    // "Degrades to TU-09" is an acceptance clause; degrading SILENTLY would
    // leave the user staring at an empty transparent window.
    //
    // `failed`, not `reclaim`: CTR-06 types reclaim's reason as HandoffEndReason
    // (completed / user_dismissed / focus_changed / tool_closed), none of which
    // describes a KB with no coordinates. `failed.reason` is the free-form one.
    const { driver, outbound } = harness(0.9)
    driver.spawn({ handoffId: 'h1', focus: null, step: NO_LOCATOR_STEP, target: TARGET })
    const failure = outbound.find((m) => m.type === 'failed')
    expect(failure).toBeDefined()
    if (failure?.type === 'failed') expect(failure.reason).toBe('no_locator')
  })

  it('clears the surface when it hands the guide back', () => {
    const { driver, views, controller } = harness(0.9)
    driver.spawn({ handoffId: 'h1', focus: null, step: NO_LOCATOR_STEP, target: TARGET })
    expect(views.at(-1)).toBeNull()
    // `failed` is terminal on the orb side, so holding the handoff here would
    // leave the two ends disagreeing about who owns the guide.
    expect(controller.activeHandoffId()).toBeNull()
  })

  it('stays silent when it CAN point', () => {
    const { driver, outbound } = harness(0.9)
    driver.spawn({ handoffId: 'h1', focus: null, step: CONFIDENT_STEP, target: TARGET })
    expect(outbound.some((m) => m.type === 'failed')).toBe(false)
  })
})

describe('overlay session — untrusted step text (M7)', () => {
  it('carries step text through as DATA, verbatim, never as markup', () => {
    // GuideStep text is untrusted end to end (SOL-IPC-01 M7). The view hands the
    // renderer plain strings for a text node; nothing here builds HTML, and
    // nothing rewrites the content either — silently mangling it would hide that
    // a fork sent something hostile.
    const { driver, views } = harness(0.9)
    const nasty = '<img src=x onerror=alert(1)>'
    driver.spawn({
      handoffId: 'h1',
      focus: null,
      step: { ...CONFIDENT_STEP, title: nasty, instruction: nasty },
      target: TARGET
    })
    const view = views.at(-1)
    expect(view?.title).toBe(nasty)
    expect(typeof view?.title).toBe('string')
    expect(typeof view?.instruction).toBe('string')
  })
})

describe('overlay session — lifecycle', () => {
  it('stops listening after dispose', () => {
    const { orb, overlay } = createLoopbackPorts()
    const onView = vi.fn()
    const controller = createOverlaySession(overlay, { onView, confidenceFor: () => 0.9 })
    controller.dispose()
    createStubOrb(orb).spawn({ handoffId: 'h1', focus: null, step: CONFIDENT_STEP, target: TARGET })
    expect(onView).not.toHaveBeenCalled()
  })
})
