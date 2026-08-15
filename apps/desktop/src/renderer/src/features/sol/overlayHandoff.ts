// SOLX-02: the ORB side of the CTR-06 orb↔overlay handoff — a renderer-side
// controller over an OrbPort (publish OrbToOverlay / subscribe OverlayToOrb).
// In production the port wraps window.solus.orbOverlay via orbPortFromBridge;
// in tests it is the contract's loopback + stub overlay. No overlay window
// exists yet (LANE D builds it) — this seam is what it will meet.
//
// Handoff binding (SOL-IPC-01 review H2): the wire only authenticates the
// sending window; WHICH handoff is live is known only here. The controller
// generates the handoffId and drops every inbound message bound to any other
// id — stale, replayed, or forged traffic never reaches a callback.
//
// Untrusted display text: GuideStep strings and `failed.reason` originate
// outside this process. They are passed through as plain strings for TEXT
// rendering only (React text nodes) — never HTML, never prompt input without
// data-wrapping.
import type {
  Focus,
  GuideStep,
  HandoffEndReason,
  OrbPort,
  OrbToOverlay,
  OverlayToOrb,
  ToolWindowRef
} from '@solus/shared-types'

export type HandoffPhase = 'idle' | 'spawning' | 'active'

export interface ReclaimedState {
  focus: Focus | null
  step: GuideStep | null
  reason: HandoffEndReason
}

export interface OverlayHandoffCallbacks {
  /** The overlay confirmed a step; the orb decides what to advance to. */
  onStepCompleted?: (stepId: string) => void
  /** The overlay handed the session back — restore the orb UI from this state. */
  onReclaim?: (state: ReclaimedState) => void
  /** The handoff ended (dismissed either side). */
  onEnded?: (reason: HandoffEndReason) => void
  /** Spawn/session failure. `reason` is untrusted display TEXT — never HTML. */
  onFailed?: (reason: string) => void
}

export interface OverlayHandoff {
  phase(): HandoffPhase
  activeHandoffId(): string | null
  lastReclaim(): ReclaimedState | null
  /** Begin a handoff; returns the generated handoffId. Throws if one is live. */
  start(input: { focus: Focus | null; step: GuideStep; target: ToolWindowRef }): string
  advance(step: GuideStep): void
  reposition(target: ToolWindowRef): void
  dismiss(reason: HandoffEndReason): void
  /** Unsubscribe from the port; the controller goes permanently inert. */
  dispose(): void
}

function defaultGenerateId(): string {
  // Matches the contract's HANDOFF_ID_RE (short opaque correlation id).
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `h-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function createOverlayHandoff(
  port: OrbPort,
  callbacks: OverlayHandoffCallbacks,
  generateId: () => string = defaultGenerateId
): OverlayHandoff {
  let phase: HandoffPhase = 'idle'
  let activeId: string | null = null
  let reclaimed: ReclaimedState | null = null

  const end = (): void => {
    phase = 'idle'
    activeId = null
  }

  type TerminalMessage = Extract<OverlayToOrb, { type: 'reclaim' | 'dismissed' | 'failed' }>

  const deliverTerminal = (message: TerminalMessage): void => {
    end()
    if (message.type === 'reclaim') {
      reclaimed = { focus: message.focus, step: message.step, reason: message.reason }
      callbacks.onReclaim?.(reclaimed)
    } else if (message.type === 'dismissed') {
      callbacks.onEnded?.(message.reason)
    } else {
      callbacks.onFailed?.(message.reason)
    }
  }

  const deliver = (message: OverlayToOrb): void => {
    // H2 binding: only the live handoff's messages exist for this controller.
    if (activeId === null || message.handoffId !== activeId) return
    if (message.type === 'ready') {
      phase = 'active'
    } else if (message.type === 'step_completed') {
      callbacks.onStepCompleted?.(message.stepId)
    } else {
      deliverTerminal(message)
    }
  }

  const unsubscribe = port.subscribe(deliver)

  const sendActive = (message: OrbToOverlay): void => {
    if (activeId === null) throw new Error('overlay handoff: no active handoff')
    port.send(message)
  }

  return {
    phase: () => phase,
    activeHandoffId: () => activeId,
    lastReclaim: () => reclaimed,
    start(input) {
      if (activeId !== null) throw new Error('overlay handoff: a handoff is already active')
      const handoffId = generateId()
      // State first: the transport may deliver `ready`/`failed` synchronously.
      activeId = handoffId
      phase = 'spawning'
      port.send({ type: 'spawn', handoffId, ...input })
      return handoffId
    },
    advance(step) {
      sendActive({ type: 'advance', handoffId: activeId as string, step })
    },
    reposition(target) {
      sendActive({ type: 'reposition', handoffId: activeId as string, target })
    },
    dismiss(reason) {
      sendActive({ type: 'dismiss', handoffId: activeId as string, reason })
    },
    dispose() {
      end()
      unsubscribe()
    }
  }
}

/** Adapt the preload's window.solus.orbOverlay surface to an OrbPort. */
export function orbPortFromBridge(bridge: {
  publishToOverlay(message: OrbToOverlay): void
  onOverlayToOrb(handler: (message: OverlayToOrb) => void): () => void
}): OrbPort {
  return {
    send: (message) => bridge.publishToOverlay(message),
    subscribe: (listener) => bridge.onOverlayToOrb(listener)
  }
}
