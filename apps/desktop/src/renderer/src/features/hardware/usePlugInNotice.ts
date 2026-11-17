// SOLUSDEV-326 P3: the open Hardware page tells SOL what is plugged in and unclaimed
// (`MessageCreate.notice`, docs/contracts/action-gate.md §Cards 4). Each offer (present, bound to
// nothing, not waved off, its inspection settled) is announced once per app session, 2 s after
// the page first sees it: one that was there before Solus started, one the shell's toast stood in
// for while the page was closed (useDeviceStream), or one plugged in while the page is open. The
// store remembers which were announced (`announced`) until the device stops being an offer, and
// which are owed a notice regardless (`unannounced`): "+ Add hardware" owes the current offers
// again. The chat queues a notice behind a live turn and swallows the server's quiet refusals
// (announced twice, device gone).
import { useEffect, useRef } from 'react'
import { announced, isOffer, useDeviceStore } from './deviceStore'

/** How long an offer must hold before SOL hears of it: a flapping port is one arrival. */
export const NOTICE_DELAY_MS = 2000

type Timer = ReturnType<typeof setTimeout>

function offers(projectId: string): Set<string> | null {
  const store = useDeviceStore.getState()
  if (store.projectId !== projectId) return null
  return new Set(store.devices.filter(isOffer).map((row) => row.device_ref as string))
}

export function usePlugInNotice(
  projectId: string | null,
  sendNotice: (deviceRef: string) => Promise<boolean>
): void {
  const send = useRef(sendNotice)
  useEffect(() => {
    send.current = sendNotice
  }, [sendNotice])

  useEffect(() => {
    if (!projectId) return
    // The notices inside their 2 s.
    const waiting = new Map<string, Timer>()
    const announce = (ref: string): void => {
      waiting.delete(ref)
      if (!offers(projectId)?.has(ref)) return
      // ponytail: a notice that fails is not retried; "+ Add hardware" or a replug offers it again.
      send.current(ref).catch(() => undefined)
    }
    const read = (): void => {
      const now = offers(projectId)
      if (!now) return
      for (const [ref, timer] of waiting) {
        if (now.has(ref)) continue
        clearTimeout(timer)
        waiting.delete(ref)
      }
      // Taken once: `settle` runs this reader again, by then with nothing owed.
      const owed = useDeviceStore.getState().unannounced
      if (owed.length) useDeviceStore.getState().settle()
      for (const ref of now) {
        if (waiting.has(ref) || (announced.has(ref) && !owed.includes(ref))) continue
        announced.add(ref)
        waiting.set(
          ref,
          setTimeout(() => announce(ref), NOTICE_DELAY_MS)
        )
      }
    }
    read()
    const stop = useDeviceStore.subscribe(read)
    return () => {
      stop()
      // A notice still waiting is owed again: the page that reopens (or StrictMode's second
      // mount) sends it.
      for (const timer of waiting.values()) clearTimeout(timer)
      if (waiting.size) useDeviceStore.getState().owe([...waiting.keys()])
    }
  }, [projectId])
}
