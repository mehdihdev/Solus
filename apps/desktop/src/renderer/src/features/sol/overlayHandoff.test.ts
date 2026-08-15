// SOLX-02: the ORB side of the CTR-06 handoff, tested against the contract's
// loopback ports + stub overlay — the sanctioned no-window test path. Pins the
// SOL-IPC-01 H2 obligation: the controller generates the handoffId and ignores
// every inbound message bound to any other handoff.
import { describe, it, expect, vi } from 'vitest'
import {
  createLoopbackPorts,
  createStubOverlay,
  type GuideStep,
  type ToolWindowRef
} from '@solus/shared-types'
import { createOverlayHandoff, orbPortFromBridge } from './overlayHandoff'

const STEP: GuideStep = {
  stepId: 'sketch-1',
  index: 1,
  total: 3,
  title: 'Open the sketch',
  instruction: 'Click the sketch button in the toolbar',
  control: null
}

const STEP_2: GuideStep = { ...STEP, stepId: 'sketch-2', index: 2 }

const TARGET: ToolWindowRef = {
  tool: 'onshape',
  windowTitle: 'Onshape — Rover MK2',
  displayId: null,
  bounds: { x: 0, y: 0, width: 1280, height: 800 }
}

describe('spawn → ready → advance → step_completed → dismiss', () => {
  it('runs the full happy path over the loopback stub', () => {
    const { orb, overlay } = createLoopbackPorts()
    const stub = createStubOverlay(overlay)
    const onStepCompleted = vi.fn()
    const onEnded = vi.fn()
    const handoff = createOverlayHandoff(orb, { onStepCompleted, onEnded })

    expect(handoff.phase()).toBe('idle')
    const id = handoff.start({ focus: null, step: STEP, target: TARGET })
    expect(id).toBeTruthy()
    // The stub answers ready synchronously over the loopback.
    expect(handoff.phase()).toBe('active')
    expect(stub.state).toBe('ready')
    expect(stub.lastStep?.stepId).toBe('sketch-1')

    handoff.advance(STEP_2)
    expect(stub.lastStep?.stepId).toBe('sketch-2')
    stub.completeStep()
    expect(onStepCompleted).toHaveBeenCalledWith('sketch-2')

    const moved: ToolWindowRef = { ...TARGET, bounds: { ...TARGET.bounds, x: 40 } }
    handoff.reposition(moved)
    expect(stub.lastTarget?.bounds.x).toBe(40)

    handoff.dismiss('completed')
    expect(stub.state).toBe('dismissed')
    expect(onEnded).toHaveBeenCalledWith('completed')
    expect(handoff.phase()).toBe('idle')
    expect(handoff.activeHandoffId()).toBeNull()
  })

  it('generates a fresh handoffId per start', () => {
    const { orb, overlay } = createLoopbackPorts()
    createStubOverlay(overlay)
    const handoff = createOverlayHandoff(orb, {})
    const first = handoff.start({ focus: null, step: STEP, target: TARGET })
    handoff.dismiss('user_dismissed')
    const second = handoff.start({ focus: null, step: STEP, target: TARGET })
    expect(second).not.toBe(first)
  })
})

describe('reclaim', () => {
  it('restores state to the orb: phase idle, last step/reason preserved', () => {
    const { orb, overlay } = createLoopbackPorts()
    const stub = createStubOverlay(overlay)
    const onReclaim = vi.fn()
    const handoff = createOverlayHandoff(orb, { onReclaim })
    handoff.start({ focus: null, step: STEP, target: TARGET })
    stub.reclaim('focus_changed')
    expect(handoff.phase()).toBe('idle')
    expect(onReclaim).toHaveBeenCalledWith({ focus: null, step: STEP, reason: 'focus_changed' })
    expect(handoff.lastReclaim()).toEqual({ focus: null, step: STEP, reason: 'focus_changed' })
  })
})

describe('handoff/tenant binding (SOL-IPC-01 H2)', () => {
  it('ignores every inbound message whose handoffId is not the active one', () => {
    const { orb, overlay } = createLoopbackPorts()
    const onStepCompleted = vi.fn()
    const onEnded = vi.fn()
    const onFailed = vi.fn()
    const handoff = createOverlayHandoff(orb, { onStepCompleted, onEnded, onFailed })
    handoff.start({ focus: null, step: STEP, target: TARGET })
    // A foreign (stale or forged) handoff speaks on the same channel.
    overlay.send({ type: 'step_completed', handoffId: 'foreign-1', stepId: 'sketch-1' })
    overlay.send({ type: 'dismissed', handoffId: 'foreign-1', reason: 'completed' })
    overlay.send({ type: 'failed', handoffId: 'foreign-1', reason: 'nope' })
    overlay.send({ type: 'ready', handoffId: 'foreign-1' })
    expect(onStepCompleted).not.toHaveBeenCalled()
    expect(onEnded).not.toHaveBeenCalled()
    expect(onFailed).not.toHaveBeenCalled()
    expect(handoff.phase()).toBe('spawning') // the foreign ready must not activate it
  })

  it('ignores stragglers after its own handoff ended', () => {
    const { orb, overlay } = createLoopbackPorts()
    const stub = createStubOverlay(overlay)
    const onStepCompleted = vi.fn()
    const handoff = createOverlayHandoff(orb, { onStepCompleted })
    const id = handoff.start({ focus: null, step: STEP, target: TARGET })
    handoff.dismiss('user_dismissed')
    expect(stub.state).toBe('dismissed')
    overlay.send({ type: 'step_completed', handoffId: id, stepId: 'sketch-1' })
    expect(onStepCompleted).not.toHaveBeenCalled()
  })
})

describe('failSpawn path', () => {
  it('reports the failure as untrusted display text and returns to idle', () => {
    const { orb, overlay } = createLoopbackPorts()
    createStubOverlay(overlay, { failSpawn: 'window not found <img onerror=x>' })
    const onFailed = vi.fn()
    const handoff = createOverlayHandoff(orb, { onFailed })
    handoff.start({ focus: null, step: STEP, target: TARGET })
    // Delivered verbatim as a string for TEXT rendering — never interpreted.
    expect(onFailed).toHaveBeenCalledWith('window not found <img onerror=x>')
    expect(handoff.phase()).toBe('idle')
    expect(handoff.activeHandoffId()).toBeNull()
  })
})

describe('orbPortFromBridge', () => {
  it('adapts the preload orbOverlay surface to an OrbPort', () => {
    const publishToOverlay = vi.fn()
    const unsubscribe = vi.fn()
    const onOverlayToOrb = vi.fn(() => unsubscribe)
    const port = orbPortFromBridge({ publishToOverlay, onOverlayToOrb })
    port.send({ type: 'dismiss', handoffId: 'h-1', reason: 'completed' })
    expect(publishToOverlay).toHaveBeenCalledWith({
      type: 'dismiss',
      handoffId: 'h-1',
      reason: 'completed'
    })
    const listener = vi.fn()
    const off = port.subscribe(listener)
    expect(onOverlayToOrb).toHaveBeenCalledWith(listener)
    off()
    expect(unsubscribe).toHaveBeenCalledTimes(1)
  })
})

describe('caller-bug guards', () => {
  it('advance/dismiss without an active handoff throw loudly', () => {
    const { orb } = createLoopbackPorts()
    const handoff = createOverlayHandoff(orb, {})
    expect(() => handoff.advance(STEP)).toThrow(/no active handoff/)
    expect(() => handoff.dismiss('completed')).toThrow(/no active handoff/)
  })

  it('start while a handoff is live throws instead of orphaning it', () => {
    const { orb, overlay } = createLoopbackPorts()
    createStubOverlay(overlay)
    const handoff = createOverlayHandoff(orb, {})
    handoff.start({ focus: null, step: STEP, target: TARGET })
    expect(() => handoff.start({ focus: null, step: STEP, target: TARGET })).toThrow(/active/)
  })

  it('dispose unsubscribes from the port', () => {
    const { orb, overlay } = createLoopbackPorts()
    const stub = createStubOverlay(overlay)
    const onReclaim = vi.fn()
    const handoff = createOverlayHandoff(orb, { onReclaim })
    handoff.start({ focus: null, step: STEP, target: TARGET })
    handoff.dispose()
    stub.reclaim('tool_closed')
    expect(onReclaim).not.toHaveBeenCalled()
  })
})
