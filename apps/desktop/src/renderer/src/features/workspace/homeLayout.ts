// SOLUSDEV-328 — how many columns Home's team overview gets, measured on the overview itself (never
// the window), so the SOL sidebar docking beside Home reflows it exactly like a narrower window
// (docs/wireflows/home.md "Fills the window").
import { useLayoutEffect, useState, type RefObject } from 'react'

/** stack: one scroll, team column under projects · split: projects │ team · wide: projects │
 *  current project │ team. */
export type HomeLayout = 'stack' | 'split' | 'wide'

/** Under this the team column cannot sit beside a readable projects table. */
export const HOME_SPLIT_MIN = 880
/** From here the current project earns its own column. */
export const HOME_WIDE_MIN = 1680

/** The layout for an overview this wide; unmeasured (0, NaN) is split, so nothing is hidden. */
export function homeLayoutFor(width: number): HomeLayout {
  if (!Number.isFinite(width) || width <= 0) return 'split'
  if (width >= HOME_WIDE_MIN) return 'wide'
  if (width >= HOME_SPLIT_MIN) return 'split'
  return 'stack'
}

/** The element's layout, kept current as it resizes. Split where nothing can measure (jsdom).
 *  Measured once before the first paint, so a wide or narrow Home never flashes split first. */
export function useHomeLayout(ref: RefObject<HTMLElement | null>): HomeLayout {
  const [layout, setLayout] = useState<HomeLayout>('split')
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    setLayout(homeLayoutFor(el.getBoundingClientRect().width))
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0
      setLayout(homeLayoutFor(width))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return layout
}
