// User settings store (ADR-016: SOL mode is a universal per-user setting,
// switchable at any time). Theme/accent/density mirror the prototype's tweaks.
// Persisted locally; the real app will reconcile with GET/PATCH
// /api/v1/users/me/settings once that flow is wired.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ThemeId, AccentId, DensityId } from '../theme/tokens.constants'

export type SolMode = 'Guide' | 'Expert'

export interface SettingsState {
  theme: ThemeId
  accent: AccentId
  density: DensityId
  solMode: SolMode
  setTheme: (theme: ThemeId) => void
  setAccent: (accent: AccentId) => void
  setDensity: (density: DensityId) => void
  setSolMode: (mode: SolMode) => void
}

export const SETTINGS_STORAGE_KEY = 'solus_settings_v1'

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: 'dark',
      accent: 'amber',
      density: 'regular',
      solMode: 'Guide',
      setTheme: (theme) => set({ theme }),
      setAccent: (accent) => set({ accent }),
      setDensity: (density) => set({ density }),
      setSolMode: (solMode) => set({ solMode })
    }),
    { name: SETTINGS_STORAGE_KEY }
  )
)
