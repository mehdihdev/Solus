// The one decision a card can be making: busy while it is recorded, and why it failed when it
// did (split from ConfirmationCard.tsx so the SOLUSDEV-326 ChatCard shares it).
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ConfirmationDecision } from './ConfirmationCard'

type OnDecide = (decision: ConfirmationDecision) => Promise<void>

/** The host's latest onDecide behind a stable identity, so a host that passes
 *  a fresh closure each render does not re-register the keyboard approver. */
function useLatestDecide(onDecide: OnDecide): OnDecide {
  const latest = useRef(onDecide)
  useEffect(() => {
    latest.current = onDecide
  }, [onDecide])
  return useCallback((decision: ConfirmationDecision) => latest.current(decision), [])
}

export function useConfirmationDecision(hostDecide: OnDecide): {
  busy: ConfirmationDecision | null
  failed: { message: string; terminal: boolean } | null
  decide: (decision: ConfirmationDecision) => Promise<void>
} {
  const onDecide = useLatestDecide(hostDecide)
  const [busy, setBusy] = useState<ConfirmationDecision | null>(null)
  const [failed, setFailed] = useState<{ message: string; terminal: boolean } | null>(null)
  // A second gesture before React re-renders (a double click, a held
  // Cmd/Ctrl+Enter) must not send a second decision.
  const inFlight = useRef(false)

  // useCallback so react-hooks can see this is an event handler rather than
  // effect-adjacent state writing.
  const decide = useCallback(
    async (decision: ConfirmationDecision): Promise<void> => {
      if (inFlight.current) return
      inFlight.current = true
      setBusy(decision)
      setFailed(null)
      try {
        await onDecide(decision)
        // Success: the host removes this card. Nothing to render here, and a
        // local "applied" state would claim an outcome we cannot see.
      } catch (error) {
        // A failed decision must never look like a successful one. Show the
        // server's own reason — "expired", "already decided", "what this would
        // do has changed" are all different, and a generic apology hides which.
        //
        // TWO kinds, and conflating them is its own bug: a TRANSPORT failure
        // leaves the action genuinely parked and retryable, while a
        // ConfirmationRefused means the server decided and refused. Those rows
        // are TERMINAL — the confirmation can never be approved again — so
        // saying "still waiting" and leaving Approve live only earns "This
        // action was already …" on the next click.
        setFailed({
          message: error instanceof Error ? error.message : 'That didn’t go through.',
          // Checked by NAME, not `instanceof`: this error crosses a module
          // boundary, and a bundled or mocked second copy of the class would
          // make an identity check silently false — the failure mode being
          // fixed here, reintroduced one level down.
          terminal: error instanceof Error && error.name === 'ConfirmationRefused'
        })
      } finally {
        inFlight.current = false
        setBusy(null)
      }
    },
    [onDecide]
  )

  return { busy, failed, decide }
}
