// SOLX-03: the overlay half of the CTR-06 handoff — the controller that turns
// orb messages into what the overlay should draw, and decides when it must not
// draw at all.
//
// Two obligations SOL-IPC-01 billed to whoever built this end:
//
//   H2 — the wire authenticates the WINDOW, not the handoff. Every inbound
//        message is therefore checked against the handoff this session actually
//        adopted; a message for any other one is dropped. The orb side already
//        does the mirror of this (features/sol/overlayHandoff.ts).
//   M7 — `GuideStep` text is untrusted (it can originate in a vendored fork's
//        knowledge). It leaves here as plain strings destined for a text node.
//        This module builds no markup and performs no interpolation, so there is
//        no site here for that content to become anything but text.
//
// Pure with respect to the DOM and Electron: it takes a CTR-06 port and emits
// view state, so the whole state machine is testable without a window — which
// is what makes SOLX-03 verifiable on a machine with no CAD tool installed.
import type { GuideStep, OverlayPort, ToolWindowRef } from '@solus/shared-types'
import {
  decideOverlayStep,
  type OverlayDecision,
  type OverlayFallbackReason
} from './overlayDecision'

// HAND_BACK — why a fallback sends `failed` and not `reclaim`.
//
// Degrading has to be AUDIBLE: a silent fallback leaves a transparent window
// over the user's tool showing nothing, with the panel unaware it should take
// over. But CTR-06 types `reclaim.reason` as HandoffEndReason, whose four values
// (completed / user_dismissed / focus_changed / tool_closed) are all about the
// USER or the TOOL. None describes "the KB has no coordinates for this control",
// and reporting one that does not fit would have the orb narrate something
// untrue. `failed.reason` is the free-form field for exactly this, and it is
// terminal on the orb side too (overlayHandoff.ts), so the panel picks the guide
// up — which is why the handoff is released here rather than held.

/** What the renderer needs to paint one step. Strings, a box, nothing else. */
export interface OverlayView {
  handoffId: string
  stepId: string
  index: number
  total: number
  /** UNTRUSTED text for a text node (M7). */
  title: string
  /** UNTRUSTED text for a text node (M7). */
  instruction: string
  decision: OverlayDecision
}

export interface OverlaySessionDeps {
  /** The current view, or null once there is nothing to draw. Null matters: the
   *  overlay window is HIDDEN on dismiss, not destroyed, so a view left standing
   *  reappears over the user's tool pointing at a finished step. */
  onView(view: OverlayView | null): void
  /**
   * Effective confidence for a step's control, from the KB.
   *
   * Injected rather than fetched here: the confidence that matters is the
   * time-decayed one the guide resolution already computed (toolkb/staleness.py),
   * and the overlay must not re-derive a second opinion about how sure it is.
   */
  confidenceFor(step: GuideStep): number | null
  /** Whether the KB entry is past re-verification (TU-07). Defaults to false. */
  staleFor?(step: GuideStep): boolean
}

export interface OverlaySession {
  activeHandoffId(): string | null
  target(): ToolWindowRef | null
  dispose(): void
}

export function createOverlaySession(port: OverlayPort, deps: OverlaySessionDeps): OverlaySession {
  let handoffId: string | null = null
  let target: ToolWindowRef | null = null

  /** H2: a message is ours only when it names the handoff we adopted. */
  const mine = (id: string): boolean => handoffId !== null && id === handoffId

  function present(step: GuideStep): void {
    if (handoffId === null) return
    const decision = decideOverlayStep({
      available: step.control !== null,
      confidence: deps.confidenceFor(step),
      stale: deps.staleFor?.(step) ?? false,
      locator: step.control?.locator ?? null
    })
    deps.onView({
      handoffId,
      stepId: step.stepId,
      index: step.index,
      total: step.total,
      title: step.title,
      instruction: step.instruction,
      decision
    })
    if (decision.kind === 'fallback') handBack(decision.reason)
  }

  /** See HAND_BACK above. Ends the handoff and clears the surface. */
  function handBack(reason: OverlayFallbackReason): void {
    if (handoffId === null) return
    port.send({ type: 'failed', handoffId, reason })
    handoffId = null
    target = null
    deps.onView(null)
  }

  const unsubscribe = port.subscribe((message) => {
    switch (message.type) {
      case 'spawn':
        // First spawn wins. A second one while a handoff is live is either a
        // race or an impersonation; either way the live handoff is not replaced.
        if (handoffId !== null) return
        handoffId = message.handoffId
        target = message.target
        port.send({ type: 'ready', handoffId })
        present(message.step)
        return
      case 'reposition':
        if (!mine(message.handoffId)) return
        target = message.target
        return
      case 'advance':
        if (!mine(message.handoffId)) return
        present(message.step)
        return
      case 'dismiss':
        if (!mine(message.handoffId)) return
        handoffId = null
        target = null
        deps.onView(null)
        return
    }
  })

  return {
    activeHandoffId: () => handoffId,
    target: () => target,
    dispose: () => {
      unsubscribe()
      handoffId = null
      target = null
    }
  }
}
