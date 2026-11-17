// SOLUSDEV-327 — the sidebar's motion phase, its fit (dock vs overlay) and its drag resize.
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  SIDEBAR_CLOSE_MS,
  SIDEBAR_DOCK_MIN_WINDOW,
  SIDEBAR_RESIZE_STEP,
  motionMs
} from './sidebarMotion.constants'
import { useSolSidebarStore } from './solSidebarStore'

/** `entering` renders at width 0 for one frame so the open transition has a start; `leaving`,
 *  `expanding` and `popping` keep the panel mounted while their motion plays. */
export type SidebarPhase = 'closed' | 'entering' | 'open' | 'leaving' | 'expanding' | 'popping'

export interface SidebarPresence {
  phase: SidebarPhase
  /** Play `phase` for `ms`, then run `done` (expand to the page, pop out to the pill). */
  exit: (phase: 'expanding' | 'popping', ms: number, done: () => void) => void
}

/**
 * Drive the phase from the stored open flag. A screen change (`key`) snaps to that screen's
 * remembered state with no motion — the screen itself plays its own entrance.
 */
export function useSidebarPresence(open: boolean, key: string): SidebarPresence {
  const [state, setState] = useState<{ key: string; phase: SidebarPhase }>({
    key,
    phase: open ? 'open' : 'closed'
  })
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // The screen right now: an exit's continuation (navigate, open the pill) runs only if the
  // person is still on the screen that started it.
  const currentKey = useRef(key)
  useEffect(() => {
    currentKey.current = key
  }, [key])
  const clear = (): void => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }
  const keyChanged = state.key !== key
  if (keyChanged) setState({ key, phase: open ? 'open' : 'closed' })
  const phase = keyChanged ? (open ? 'open' : 'closed') : state.phase

  useEffect(() => {
    if (keyChanged) return
    if (open && (phase === 'closed' || phase === 'leaving')) {
      clear()
      setState({ key, phase: 'entering' })
    } else if (!open && (phase === 'open' || phase === 'entering')) {
      setState({ key, phase: 'leaving' })
      timer.current = setTimeout(
        () =>
          setState((s) => (s.key === key && s.phase === 'leaving' ? { key, phase: 'closed' } : s)),
        motionMs(SIDEBAR_CLOSE_MS)
      )
    }
  }, [open, phase, key, keyChanged])

  // Two frames at width 0, then the transition runs to the open width.
  useEffect(() => {
    if (phase !== 'entering') return undefined
    let inner = 0
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() =>
        setState((s) => (s.key === key && s.phase === 'entering' ? { key, phase: 'open' } : s))
      )
    })
    return () => {
      cancelAnimationFrame(outer)
      cancelAnimationFrame(inner)
    }
  }, [phase, key])

  useEffect(() => clear, [])

  const exit = useCallback<SidebarPresence['exit']>(
    (next, ms, done) => {
      clear()
      setState({ key, phase: next })
      timer.current = setTimeout(() => {
        setState((s) => (s.key === key ? { key, phase: 'closed' } : s))
        if (currentKey.current === key) done()
      }, motionMs(ms))
    },
    [key]
  )
  return { phase, exit }
}

export type SidebarFit = 'dock' | 'overlay'

/** Dock beside the screen on wide windows; overlay its right edge below 1100px. Never on
 *  Hardware (SOLUSDEV-326): an overlay would cover the card's buttons at the page's right edge. */
export function useWindowFit(screen?: string): SidebarFit {
  const read = (): boolean =>
    typeof window !== 'undefined' && window.innerWidth < SIDEBAR_DOCK_MIN_WINDOW
  const [narrow, setNarrow] = useState(read)
  useEffect(() => {
    const onResize = (): void => setNarrow(read())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return narrow && screen !== 'hardware' ? 'overlay' : 'dock'
}

const END_EVENTS = ['pointerup', 'pointercancel', 'blur'] as const

export interface SidebarResize {
  width: number
  onPointerDown: (event: React.PointerEvent<HTMLElement>) => void
  onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void
}

/** The left-edge handle: dragging left widens; ←/→ step 16px. The store clamps. */
export function useSidebarResize(): SidebarResize {
  const width = useSolSidebarStore((s) => s.width)
  // A drag's teardown, so an unmount (⌘J, Escape mid-drag) or a cancelled pointer never leaves
  // listeners or the app-wide resize cursor behind.
  const endDrag = useRef<(() => void) | null>(null)
  useEffect(() => () => endDrag.current?.(), [])
  const onPointerDown = (event: React.PointerEvent<HTMLElement>): void => {
    event.preventDefault()
    endDrag.current?.()
    const startX = event.clientX
    const startWidth = useSolSidebarStore.getState().width
    const onMove = (move: PointerEvent): void =>
      useSolSidebarStore.getState().setWidth(startWidth + (startX - move.clientX))
    const end = (): void => {
      window.removeEventListener('pointermove', onMove)
      for (const type of END_EVENTS) window.removeEventListener(type, end)
      document.body.classList.remove('sol-sb-resizing')
      endDrag.current = null
    }
    window.addEventListener('pointermove', onMove)
    for (const type of END_EVENTS) window.addEventListener(type, end)
    document.body.classList.add('sol-sb-resizing')
    endDrag.current = end
  }
  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>): void => {
    const step =
      event.key === 'ArrowLeft'
        ? SIDEBAR_RESIZE_STEP
        : event.key === 'ArrowRight'
          ? -SIDEBAR_RESIZE_STEP
          : 0
    if (!step) return
    event.preventDefault()
    const store = useSolSidebarStore.getState()
    store.setWidth(store.width + step)
  }
  return { width, onPointerDown, onKeyDown }
}
