// User settings store (ADR-016: SOL mode is a universal per-user setting,
// switchable at any time). Theme/accent mirror the prototype's tweaks; density
// was removed in SOLUSDEV-318 (no surface ever read it).
// Persisted locally; the real app will reconcile with GET/PATCH
// /api/v1/users/me/settings once that flow is wired.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ThemeId, AccentId } from '../theme/tokens.constants'

export type SolMode = 'Guide' | 'Expert'

export interface SettingsState {
  theme: ThemeId
  accent: AccentId
  solMode: SolMode
  setTheme: (theme: ThemeId) => void
  setAccent: (accent: AccentId) => void
  setSolMode: (mode: SolMode) => void
}

export const SETTINGS_STORAGE_KEY = 'solus_settings_v1'
/** v1 (SOLUSDEV-318): density dropped. v0 is every store written before it. */
const SETTINGS_STORAGE_VERSION = 1

/** A persisted value from any older version → the current shape: only the
 *  three known preferences survive (density and anything else is dropped, so
 *  an edited store can never replace an action). Unknown theme/accent ids
 *  still fall back to defaults in applyTheme. */
export function migrateSettings(persisted: unknown): Partial<SettingsState> {
  if (typeof persisted !== 'object' || persisted === null) return {}
  const p = persisted as Record<string, unknown>
  const out: Partial<SettingsState> = {}
  if (typeof p.theme === 'string') out.theme = p.theme as ThemeId
  if (typeof p.accent === 'string') out.accent = p.accent as AccentId
  if (p.solMode === 'Guide' || p.solMode === 'Expert') out.solMode = p.solMode
  return out
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: 'dark',
      accent: 'amber',
      solMode: 'Guide',
      setTheme: (theme) => set({ theme }),
      setAccent: (accent) => set({ accent }),
      setSolMode: (solMode) => set({ solMode })
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      version: SETTINGS_STORAGE_VERSION,
      migrate: (persisted) => migrateSettings(persisted) as SettingsState
    }
  )
)
