// Workspace shell interaction state: the active toast and the last main
// screen (used to return from detail views). SOLUSDEV-152 removed the
// prototype alert-resolution / bench-anomaly / SOL-chat state together with
// the fabricated demo data.
import { create } from 'zustand'

export interface ShellToast {
  kind?: 'ok' | 'warn'
  title: string
  body: string
  action?: string
  alertId?: string
  /** SOLUSDEV-233: the action button navigates to this main screen (e.g. a
   *  backgrounded SOL reply's "View" jumps to the SOL page). */
  screen?: MainScreen
  /** SOLUSDEV-246 (STORE ST3): with `screen: 'store'`, the action opens this
   *  extension's detail page (the in-context suggestion after a source connects). */
  extensionSlug?: string
}

export type MainScreen =
  | 'home'
  | 'overview'
  | 'workspace'
  | 'sources'
  | 'bench'
  | 'sol'
  | 'team'
  | 'store'
  | 'billing'
  | 'settings'

/** Where the shell is: a main screen (a rail item), an alert detail, or an
 *  installed extension's page view (SOLUSDEV-235 / EXT-14). Detail routes are
 *  render state in WorkspaceShell, never persisted; `lastMain` is the way back. */
export type ShellRoute =
  | { name: MainScreen }
  | { name: 'alert'; alertId: string }
  | { name: 'ext-page'; slug: string }

/** Stable per-destination key: the screen-in transition replays per navigation,
 *  and two extension pages are two destinations. */
export function routeKey(route: ShellRoute): string {
  switch (route.name) {
    case 'alert':
      return `alert-${route.alertId}`
    case 'ext-page':
      return `ext-page-${route.slug}`
    default:
      return route.name
  }
}

export interface ShellState {
  toast: ShellToast | null
  lastMain: MainScreen

  setToast: (toast: ShellToast) => void
  clearToast: () => void
  setLastMain: (screen: MainScreen) => void
  reset: () => void
}

const INITIAL = {
  toast: null as ShellToast | null,
  lastMain: 'home' as MainScreen
}

export const useShellStore = create<ShellState>((set) => ({
  ...INITIAL,

  setToast: (toast) => set({ toast }),
  clearToast: () => set({ toast: null }),
  setLastMain: (screen) => set({ lastMain: screen }),
  reset: () => set({ ...INITIAL })
}))
