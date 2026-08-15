// SOLX-03: the surface loaded at #/overlay by main/overlay/overlayWindow.ts —
// the composition root that joins the preload's CTR-06 port to the confidence
// gate and the painter.
//
// Deliberately has no auth guard, unlike OrbWindow: this window renders only
// what the orb hands it over the wire, never anything fetched with the user's
// session. That is also why it needs no store.
import { useEffect, useState } from 'react'
import type { OrbToOverlay, OverlayPort, OverlayToOrb } from '@solus/shared-types'
import { GuideOverlay } from './GuideOverlay'
import { createOverlaySession, type OverlayView } from './overlaySession'

/**
 * Confidence for a step whose locator arrived on the wire.
 *
 * CTR-06 is frozen and carries no confidence field, and `spawn` carries no guide
 * id either — so this window cannot look one up. The orb is the side that
 * resolved the guide and therefore the side that HAS the KB's number; a locator
 * it chose to send is one it vouched for, and the overlay does not manufacture a
 * second opinion about how sure it is (see overlaySession's `confidenceFor`).
 *
 * The structural half of the gate still bites — an out-of-window or zero-area
 * box is refused here no matter who vouched for it.
 *
 * ponytail: one constant, not a fetch. If CTR-06 ever gains a confidence field,
 * this is the single line that changes.
 */
const ORB_VOUCHED = 1

/** Mirror of `orbPortFromBridge` (features/sol/overlayHandoff.ts) for this end. */
function overlayPortFromBridge(bridge: {
  publishToOrb(message: OverlayToOrb): void
  onOrbToOverlay(handler: (message: OrbToOverlay) => void): () => void
}): OverlayPort {
  return {
    send: (message) => bridge.publishToOrb(message),
    subscribe: (listener) => bridge.onOrbToOverlay(listener)
  }
}

function getOverlayBridge(): Parameters<typeof overlayPortFromBridge>[0] | null {
  const w = window as unknown as {
    solus?: { orbOverlay?: Parameters<typeof overlayPortFromBridge>[0] }
  }
  return w.solus?.orbOverlay ?? null
}

export function OverlayWindow(): React.JSX.Element | null {
  const [view, setView] = useState<OverlayView | null>(null)

  useEffect(() => {
    const bridge = getOverlayBridge()
    // No preload (static renderer preview) — there is no handoff to render, and
    // an overlay that throws here would take the window down over a dev build.
    if (bridge === null) return
    const session = createOverlaySession(overlayPortFromBridge(bridge), {
      onView: setView,
      confidenceFor: () => ORB_VOUCHED
    })
    return () => session.dispose()
  }, [])

  return <GuideOverlay view={view} />
}
