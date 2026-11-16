// SOLUSDEV-327 — the SOL sidebar's open state and width (sol-sidebar.md §2–3). ONE open flag:
// the sidebar follows the person across screens (only the SOL page never shows it). UI
// preference only, on this machine: localStorage via zustand persist (best effort).
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ShellRoute } from '../../workspace/shellStore'

export const SIDEBAR_DEFAULT_WIDTH = 360
export const SIDEBAR_MIN_WIDTH = 320
export const SIDEBAR_MAX_WIDTH = 480
/** The SOL page already is SOL: the sidebar is never shown there. */
const HIDDEN_ON = 'sol'

export interface SolSidebarState {
  open: boolean
  width: number
  setOpen: (open: boolean) => void
  toggle: () => void
  setWidth: (width: number) => void
  reset: () => void
}

/** The screen name the sidebar reports and copies itself from; detail routes by their kind. */
export function sidebarKey(route: ShellRoute): string {
  return route.name
}

export function clampSidebarWidth(width: number): number {
  if (!Number.isFinite(width)) return SIDEBAR_DEFAULT_WIDTH
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, Math.round(width)))
}

/** Whether the sidebar shows on `screen`. */
export function selectSidebarOpen(state: SolSidebarState, screen: string): boolean {
  return screen !== HIDDEN_ON && state.open
}

const INITIAL = { open: false, width: SIDEBAR_DEFAULT_WIDTH }

export const useSolSidebarStore = create<SolSidebarState>()(
  persist(
    (set) => ({
      ...INITIAL,
      setOpen: (open) => set({ open }),
      toggle: () => set((s) => ({ open: !s.open })),
      setWidth: (width) => set({ width: clampSidebarWidth(width) }),
      reset: () => set({ ...INITIAL })
    }),
    {
      name: 'solus.sol-sidebar',
      // v1: one open flag (v0 kept one per screen — dropped, the sidebar starts closed).
      version: 1,
      migrate: (persisted) => persisted,
      partialize: (s) => ({ open: s.open, width: s.width }),
      // localStorage is untrusted: only a real boolean and a finite, clamped width survive.
      merge: (persisted, current) => {
        const saved = (persisted ?? {}) as Partial<Record<keyof SolSidebarState, unknown>>
        return {
          ...current,
          open: saved.open === true,
          width:
            typeof saved.width === 'number' ? clampSidebarWidth(saved.width) : SIDEBAR_DEFAULT_WIDTH
        }
      }
    }
  )
)
