// SOLUSDEV-328 — how many columns Home's views get, measured on the view itself (never the
// window), so the SOL sidebar docking beside Home reflows it exactly like a narrower window
// (docs/wireflows/home.md "Fills the window").
import { useLayoutEffect, useState, type RefObject } from 'react'

/** Team overview — stack: one scroll, team column under projects · split: projects │ team ·
 *  wide: projects │ current project │ team. */
export type HomeLayout = 'stack' | 'split' | 'wide'

/** Project page (design P2) — narrow: a project switcher in the header, activity below · list:
 *  projects │ project, activity below · full: projects │ project │ activity. */
export type ProjectPageLayout = 'narrow' | 'list' | 'full'

/** Under this the team column cannot sit beside a readable projects table. */
export const HOME_SPLIT_MIN = 880
/** From here the current project earns its own column. */
export const HOME_WIDE_MIN = 1680

/** Under this the projects list folds into the header's switcher. */
export const PROJECT_LIST_MIN = 900
/** From here the project's activity gets its own full-height column. */
export const PROJECT_FULL_MIN = 1380

function measured(width: number): boolean {
  return Number.isFinite(width) && width > 0
}

/** The overview layout for this width; unmeasured (0, NaN) is split, so nothing is hidden. */
export function homeLayoutFor(width: number): HomeLayout {
  if (!measured(width)) return 'split'
  if (width >= HOME_WIDE_MIN) return 'wide'
  if (width >= HOME_SPLIT_MIN) return 'split'
  return 'stack'
}

/** The project page layout for this width; unmeasured is list. */
export function projectPageLayoutFor(width: number): ProjectPageLayout {
  if (!measured(width)) return 'list'
  if (width >= PROJECT_FULL_MIN) return 'full'
  if (width >= PROJECT_LIST_MIN) return 'list'
  return 'narrow'
}

/** `layoutFor` of the element's width, kept current as it resizes; `layoutFor(0)` where nothing
 *  can measure (jsdom). Measured once before the first paint, so no wrong layout flashes first. */
function useWidthLayout<T>(ref: RefObject<HTMLElement | null>, layoutFor: (w: number) => T): T {
  const [layout, setLayout] = useState<T>(() => layoutFor(0))
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    setLayout(layoutFor(el.getBoundingClientRect().width))
    const observer = new ResizeObserver((entries) => {
      setLayout(layoutFor(entries[0]?.contentRect.width ?? 0))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref, layoutFor])
  return layout
}

export function useHomeLayout(ref: RefObject<HTMLElement | null>): HomeLayout {
  return useWidthLayout(ref, homeLayoutFor)
}

export function useProjectPageLayout(ref: RefObject<HTMLElement | null>): ProjectPageLayout {
  return useWidthLayout(ref, projectPageLayoutFor)
}
