// SOLUSDEV-319: a pending command card takes over the Ember Pill.
//
// While a command waits for approval, the pill's usual surfaces (panel, strip,
// composer) collapse away and go inert, and the card rises out of where the bar
// was to hold the whole pill. When it is decided, the card shrinks away as an
// inert ghost while the usual surfaces unroll back (ConfirmationCard.css /
// main.css `.sol-pill-takeover`). Only command cards take over: they are the ones
// that run something. The NEWEST one takes over, the same card Cmd/Ctrl+Enter
// would approve (commandHotkey.ts); an older one follows once it is decided.
//
// Focus goes to the card itself, never to Run: an Enter still held from sending
// the message must not approve, and Cmd/Ctrl+Enter keeps its arming delay.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { CommandCard } from './CommandApprovalCard'
import { ConfirmationCard, type ConfirmationDecision } from './ConfirmationCard'
import { commandHeader } from './commandCard'
import type { ChatItem } from './solChatStore'

/** How long the decided card takes to shrink away (matches the CSS). */
export const TAKEOVER_LEAVE_MS = 320

/** The newest pending command card in the transcript, or null. */
export function newestPendingCommand(items: readonly ChatItem[]): PendingConfirmation | null {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const confirmations = items[i].confirmations ?? []
    for (let j = confirmations.length - 1; j >= 0; j -= 1) {
      if (commandHeader(confirmations[j]) !== null) return confirmations[j]
    }
  }
  return null
}

/** The card that just left, kept TAKEOVER_LEAVE_MS so it can shrink away. */
function useLeavingCard(pending: PendingConfirmation | null): PendingConfirmation | null {
  const [leaving, setLeaving] = useState<PendingConfirmation | null>(null)
  const [last, setLast] = useState<PendingConfirmation | null>(pending)
  if (pending !== last) {
    // Derived during render (React's "storing information from previous renders").
    setLast(pending)
    setLeaving(pending === null ? last : null)
  }
  useEffect(() => {
    if (leaving === null) return
    const timer = setTimeout(() => setLeaving(null), TAKEOVER_LEAVE_MS)
    return () => clearTimeout(timer)
  }, [leaving])
  return leaving
}

/** A frozen picture of the decided card: no handlers, no keyboard approver. */
function LeavingCard({ pending }: { pending: PendingConfirmation }): React.JSX.Element | null {
  const header = commandHeader(pending)
  if (header === null) return null
  const noop = (): void => undefined
  return (
    <CommandCard
      pending={pending}
      header={header}
      variant="pill"
      busy
      closed={false}
      shortcut={null}
      onApprove={noop}
      onReject={noop}
      preview={null}
      details={null}
      failure={null}
    />
  )
}

export interface PillTakeoverProps {
  readonly pending: PendingConfirmation | null
  readonly onDecide: (confirmationId: string, decision: ConfirmationDecision) => Promise<void>
}

export function PillTakeover({ pending, onDecide }: PillTakeoverProps): React.JSX.Element | null {
  const leaving = useLeavingCard(pending)
  const ref = useRef<HTMLDivElement>(null)
  const id = pending?.confirmationId ?? null
  const decide = useCallback(
    (decision: ConfirmationDecision) => (id === null ? Promise.resolve() : onDecide(id, decision)),
    [onDecide, id]
  )
  useLayoutEffect(() => {
    if (id !== null) ref.current?.focus({ preventScroll: true })
  }, [id])

  if (pending !== null) {
    return (
      <div ref={ref} className="sol-pill-takeover" tabIndex={-1}>
        <div className="sol-pill-takeover-inner">
          <ConfirmationCard
            key={pending.confirmationId}
            pending={pending}
            onDecide={decide}
            variant="pill"
          />
        </div>
      </div>
    )
  }
  if (leaving === null) return null
  return (
    <div className="sol-pill-takeover" data-leaving="true" aria-hidden="true" inert>
      <div className="sol-pill-takeover-inner">
        <LeavingCard pending={leaving} />
      </div>
    </div>
  )
}

/** Focus returns to the composer when a takeover ends. */
export function useTakeoverFocusReturn(
  active: boolean,
  stackRef: React.RefObject<HTMLElement | null>
): void {
  const wasActive = useRef(active)
  useEffect(() => {
    if (wasActive.current && !active) {
      stackRef.current?.querySelector<HTMLElement>('.sol-pill-normal .sol-pill-input')?.focus()
    }
    wasActive.current = active
  }, [active, stackRef])
}
