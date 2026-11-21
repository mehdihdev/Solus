// SOLUSDEV-327 — SOL sidebar motion timings (sol-sidebar.md §5). The CSS in solSidebar.css uses
// the same numbers; JS waits on them before unmounting, navigating or opening the pill.
export const SIDEBAR_OPEN_MS = 340
export const SIDEBAR_CLOSE_MS = 220
export const SIDEBAR_EXPAND_MS = 420
export const SIDEBAR_POP_MS = 260
/** The chat switcher's list leaves in 130ms (it drops in over 200ms; solSidebar.css). */
export const SWITCHER_CLOSE_MS = 130
/** Below this window width the sidebar overlays the screen instead of docking. */
export const SIDEBAR_DOCK_MIN_WINDOW = 1100
/** Keyboard resize step on the left-edge handle. */
export const SIDEBAR_RESIZE_STEP = 16

/** Under the OS reduced-motion setting (or where it cannot be read) every wait is zero. */
export function motionMs(ms: number): number {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 0
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : ms
}
