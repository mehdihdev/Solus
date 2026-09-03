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
}

export type MainScreen =
  | 'home'
  | 'overview'
  | 'graph'
  | 'sources'
  | 'bench'
  | 'sol'
  | 'team'
  | 'store'
  | 'billing'
  | 'settings'

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
