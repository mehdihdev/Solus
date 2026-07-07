// Workspace shell interaction state (ported from the App state in
// TestDesign/app/shell-main.jsx): which alerts the user resolved, the bench
// anomaly, the magic-moment toast, and the SOL chat transcript. Pure derived
// helpers are exported for testing per the store convention.
import { create } from 'zustand'
import type { Alert } from './workspaceData.constants'

export type AnomalyState = 'none' | 'active' | 'resolved'

export interface ShellToast {
  kind?: 'ok' | 'warn'
  title: string
  body: string
  action?: string
  alertId?: string
}

export type ChatMessage =
  | { role: 'user'; text: string }
  | { role: 'sol'; scriptKey: string }
  // A followup answer, resolved from SOL_SCRIPTS[followupOf].followups[followupIndex].
  | { role: 'sol'; followupOf: string; followupIndex: number }

export type MainScreen = 'home' | 'graph' | 'bench' | 'sol' | 'team' | 'settings'

export interface ShellState {
  resolved: Record<string, boolean>
  anomaly: AnomalyState
  toast: ShellToast | null
  toastShown: boolean
  chat: ChatMessage[]
  lastMain: MainScreen

  resolveAlert: (id: string) => void
  setAnomaly: (anomaly: AnomalyState) => void
  setToast: (toast: ShellToast) => void
  clearToast: () => void
  markToastShown: () => void
  appendChat: (message: ChatMessage) => void
  setLastMain: (screen: MainScreen) => void
  reset: () => void
}

const INITIAL = {
  resolved: {} as Record<string, boolean>,
  anomaly: 'none' as AnomalyState,
  toast: null as ShellToast | null,
  toastShown: false,
  chat: [] as ChatMessage[],
  lastMain: 'graph' as MainScreen
}

export const useShellStore = create<ShellState>((set) => ({
  ...INITIAL,

  resolveAlert: (id) => set((s) => ({ resolved: { ...s.resolved, [id]: true } })),
  setAnomaly: (anomaly) => set({ anomaly }),
  setToast: (toast) => set({ toast }),
  clearToast: () => set({ toast: null }),
  markToastShown: () => set({ toastShown: true }),
  appendChat: (message) => set((s) => ({ chat: [...s.chat, message] })),
  setLastMain: (screen) => set({ lastMain: screen }),
  reset: () => set({ ...INITIAL, resolved: {}, chat: [] })
}))

/** Overlay user resolutions onto the static alert data. Pure + testable. */
export function alertsWithState(
  alerts: readonly Alert[],
  resolved: Record<string, boolean>
): Alert[] {
  return alerts.map((a) => (resolved[a.id] ? { ...a, state: 'resolved' as const } : a))
}

export function openAlertCount(alerts: readonly Alert[]): number {
  return alerts.filter((a) => a.state === 'open').length
}
