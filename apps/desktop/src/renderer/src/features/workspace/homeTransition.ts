// SOLUSDEV-328: the team overview ↔ project page switch morphs instead of cutting. The View
// Transitions API snapshots Home before and after the switch: the named parts (home.css) move as
// one — the rail folds to its initials strip, the overview's projects column becomes the project
// page's list — and the pane slides in the direction of travel. Off under reduced motion.
import { flushSync } from 'react-dom'
import type { HomePaneView } from './HomeAccountNav'
import './home.css'

/** Into the project page, or back out of it. */
export type HomeNavDirection = 'in' | 'out'

export function homeNavDirection(from: HomePaneView, to: HomePaneView): HomeNavDirection | null {
  if (from === to) return null
  if (to === 'project' && from === 'team') return 'in'
  if (from === 'project' && to === 'team') return 'out'
  return null
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

/** True while a team ↔ project morph is running — content mounting now enters through it. */
export function isHomeMorphing(): boolean {
  return document.documentElement.dataset.homeNav !== undefined
}

/** Runs `update` (a React state change) inside a view transition when there is one to run. */
export function withHomeTransition(direction: HomeNavDirection | null, update: () => void): void {
  // Typed as always there, but absent outside Chromium (jsdom, older engines).
  const canTransition = typeof document.startViewTransition === 'function'
  if (!direction || !canTransition || prefersReducedMotion()) {
    update()
    return
  }
  const root = document.documentElement
  root.dataset.homeNav = direction
  const clear = (): void => {
    delete root.dataset.homeNav
  }
  try {
    document.startViewTransition(() => flushSync(update)).finished.then(clear, clear)
  } catch {
    clear()
    update()
  }
}
