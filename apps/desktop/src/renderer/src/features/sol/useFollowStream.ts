// Keep the SOL thread pinned to the bottom while a reply streams, until the PERSON scrolls up
// (scrollFollow.ts says why their input, not scroll events, decides).
import { useEffect, useRef, type RefObject } from 'react'
import { isUpwardKey, nextFollow } from './scrollFollow'

export interface FollowHandlers {
  onScroll: () => void
  onWheel: (event: React.WheelEvent) => void
  onKeyDown: (event: React.KeyboardEvent) => void
  onPointerDown: () => void
}

/** `rows` is the item count; `growth` how much the last row has grown (replyGrowth). A new row
 *  re-engages following even after the person scrolled up to read history. */
export function useFollowStream(
  listRef: RefObject<HTMLDivElement | null>,
  rows: number,
  growth: number
): FollowHandlers {
  const following = useRef(true)
  const dragging = useRef(false)
  const lastRows = useRef(0)
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    if (rows !== lastRows.current) {
      lastRows.current = rows
      following.current = true
    }
    if (following.current) el.scrollTop = el.scrollHeight
  }, [listRef, rows, growth])
  useEffect(() => {
    // Rows above re-measure after a send (content-visibility) with nothing else changing; while
    // following, re-pin whenever any row changes height.
    const el = listRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      if (following.current) el.scrollTop = el.scrollHeight
    })
    for (const row of Array.from(el.children)) observer.observe(row)
    return () => observer.disconnect()
  }, [listRef, rows])
  useEffect(() => {
    const release = (): void => {
      dragging.current = false
    }
    window.addEventListener('pointerup', release)
    return () => window.removeEventListener('pointerup', release)
  }, [])
  return {
    onScroll: () => {
      const el = listRef.current
      if (el) following.current = nextFollow(following.current, el, { dragging: dragging.current })
    },
    onWheel: (event) => {
      if (event.deltaY < 0) following.current = false
    },
    onKeyDown: (event) => {
      if (isUpwardKey(event.key)) following.current = false
    },
    // A press on the list itself (its scrollbar), not on a row inside it.
    onPointerDown: () => {
      dragging.current = true
    }
  }
}
