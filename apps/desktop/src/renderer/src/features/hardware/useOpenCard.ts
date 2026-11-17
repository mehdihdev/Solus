// SOLUSDEV-326 P3: the slot's read of the caller's open card. No live event carries cards, so it
// reads on mount, on window focus, on demand and every 5 s while the document is visible.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { OpenCard } from '@solus/shared-types'
import { fetchOpenCards } from './cardsApi'

const POLL_MS = 5000
/** setTimeout's ceiling; a later expiry is simply checked again then. */
const MAX_TIMER_MS = 2 ** 31 - 1

// ponytail: the reader's clock against the server's expires_at. A skewed clock shows the expired
// card early or late; the server is still the one that refuses a late decision.
const isPast = (open: OpenCard, now: number): boolean => Date.parse(open.expires_at) <= now

export interface OpenCardRead {
  open: OpenCard | null
  /** The shown card is past its expires_at: it can no longer be decided. */
  expired: boolean
  reload: () => void
  /** A decision is in flight: keep the shown card whatever a read says. */
  hold: () => void
  /** The decision is over: drop the card (or keep it, when nothing was decided) and read again. */
  release: (keep: boolean) => void
}

export function useOpenCard(projectId: string): OpenCardRead {
  const [shown, setShown] = useState<{ projectId: string; open: OpenCard | null }>({
    projectId,
    open: null
  })
  const [now, setNow] = useState(() => Date.now())
  const read = useRef(0)
  const held = useRef(false)
  const open = shown.projectId === projectId ? shown.open : null

  const reload = useCallback(() => {
    const mine = ++read.current
    fetchOpenCards(projectId)
      .then(({ card }) => {
        if (mine !== read.current || held.current) return
        const at = Date.now()
        setNow(at)
        // The server lists unexpired cards only. One that expired while it was on show stays, as
        // the "This card expired" problem, until the person answers it or a new card is open.
        setShown((was) => {
          const kept = was.projectId === projectId && was.open && isPast(was.open, at)
          return { projectId, open: card ?? (kept ? was.open : null) }
        })
      })
      // ponytail: a failed read keeps what is shown; the next poll or focus reads again.
      .catch(() => undefined)
  }, [projectId])

  useEffect(() => {
    reload()
    const poll = setInterval(() => {
      if (document.visibilityState === 'visible') reload()
    }, POLL_MS)
    window.addEventListener('focus', reload)
    return () => {
      read.current += 1
      clearInterval(poll)
      window.removeEventListener('focus', reload)
    }
  }, [reload])

  useEffect(() => {
    if (!open) return
    const wait = Date.parse(open.expires_at) - Date.now()
    if (!(wait > 0)) return
    const timer = setTimeout(() => setNow(Date.now()), Math.min(wait, MAX_TIMER_MS))
    return () => clearTimeout(timer)
  }, [open])

  const hold = useCallback(() => {
    held.current = true
  }, [])
  const release = useCallback(
    (keep: boolean) => {
      held.current = false
      if (!keep) setShown({ projectId, open: null })
      reload()
    },
    [projectId, reload]
  )
  return { open, expired: open !== null && isPast(open, now), reload, hold, release }
}
