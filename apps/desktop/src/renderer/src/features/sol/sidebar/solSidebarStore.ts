// SOLUSDEV-327 — the SOL sidebar's open state per screen and its width (sol-sidebar.md §2–3).
// UI preference only, on this machine: localStorage via zustand persist (best effort).
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ShellRoute } from '../../workspace/shellStore'

export const SIDEBAR_DEFAULT_WIDTH = 360
export const SIDEBAR_MIN_WIDTH = 320
export const SIDEBAR_MAX_WIDTH = 480
/** The SOL page already is SOL: the sidebar never opens there. */
const NEVER_OPEN = 'sol'

export interface SolSidebarState {
  openByScreen: Readonly<Record<string, boolean>>
  width: number
  setOpen: (key: string, open: boolean) => void
  toggle: (key: string) => void
  setWidth: (width: number) => void
  reset: () => void
}

/** The per-screen key: a main screen's name; detail routes share one key per kind. */
export function sidebarKey(route: ShellRoute): string {
  return route.name
}

export function clampSidebarWidth(width: number): number {
  if (!Number.isFinite(width)) return SIDEBAR_DEFAULT_WIDTH
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, Math.round(width)))
}

export function selectSidebarOpen(state: SolSidebarState, key: string): boolean {
  return key !== NEVER_OPEN && state.openByScreen[key] === true
}

const INITIAL = { openByScreen: {}, width: SIDEBAR_DEFAULT_WIDTH }

export const useSolSidebarStore = create<SolSidebarState>()(
  persist(
    (set) => ({
      ...INITIAL,
      setOpen: (key, open) =>
        set((s) => (key === NEVER_OPEN ? s : { openByScreen: { ...s.openByScreen, [key]: open } })),
      toggle: (key) =>
        set((s) =>
          key === NEVER_OPEN
            ? s
            : { openByScreen: { ...s.openByScreen, [key]: s.openByScreen[key] !== true } }
        ),
      setWidth: (width) => set({ width: clampSidebarWidth(width) }),
      reset: () => set({ ...INITIAL })
    }),
    {
      name: 'solus.sol-sidebar',
      partialize: (s) => ({ openByScreen: s.openByScreen, width: s.width }),
      merge: (persisted, current) => {
        const saved = (persisted ?? {}) as Partial<SolSidebarState>
        return {
          ...current,
          openByScreen: isOpenMap(saved.openByScreen) ? saved.openByScreen : {},
          width: clampSidebarWidth(saved.width ?? SIDEBAR_DEFAULT_WIDTH)
        }
      }
    }
  )
)

/** localStorage is untrusted: keep only string → boolean entries. */
function isOpenMap(value: unknown): value is Record<string, boolean> {
  return (
    typeof value === 'object' &&
    value !== null &&
    Object.values(value).every((open) => typeof open === 'boolean')
  )
}
