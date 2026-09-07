// SOLUSDEV-244 / HOME H3: the renderer's copy of ~/.solus/preferences.json —
// the user's engineering conventions (ADR-034 amendment 2026-09-06). The main
// process OWNS the file; this store is hydrated from it once, saves through it
// with optimistic revert, and hands the document to every SOL turn. Nothing
// here is server state: the API sees the document only as a per-turn request
// field and keeps no copy.
import {
  emptyEngineeringPreferences,
  isEmptyPreferences,
  parseEngineeringPreferences,
  type EngineeringPreferences
} from '@solus/shared-types'
import { create } from 'zustand'
import { getDesktopPreferencesBridge } from '../../lib/desktopBridge'
import { useAuthStore } from '../../store/authStore'

export type PreferencesStatus = 'idle' | 'loading' | 'ready' | 'unavailable'

interface PreferencesState {
  preferences: EngineeringPreferences
  status: PreferencesStatus
  /** A newer Solus wrote the file: shown, never overwritten by this one. */
  readOnly: boolean
  /** Hydrate from the main process. Idempotent — one read per app lifetime. */
  load: () => Promise<void>
  /** Clean, persist, and adopt `next`. False (and state reverted) on refusal. */
  save: (next: EngineeringPreferences) => Promise<boolean>
  reset: () => void
}

let loading: Promise<void> | null = null

export const usePreferencesStore = create<PreferencesState>()((set, get) => ({
  preferences: emptyEngineeringPreferences(),
  status: 'idle',
  readOnly: false,

  load: () => {
    if (get().status === 'ready' || get().status === 'unavailable') return Promise.resolve()
    if (loading) return loading
    loading = (async () => {
      const bridge = getDesktopPreferencesBridge()
      if (!bridge) {
        set({ status: 'unavailable' })
        return
      }
      set({ status: 'loading' })
      try {
        const result = await bridge.read()
        if (!result) {
          set({ status: 'unavailable' })
          return
        }
        set({ preferences: result.preferences, readOnly: result.readOnly, status: 'ready' })
      } catch {
        set({ status: 'unavailable' })
      }
    })().finally(() => {
      loading = null
    })
    return loading
  },

  save: async (next) => {
    const bridge = getDesktopPreferencesBridge()
    const { readOnly, preferences: previous } = get()
    if (!bridge || readOnly) return false
    // The same strict parser the main process runs: caps applied, control
    // characters dropped, so what is shown is exactly what is stored.
    const cleaned = parseEngineeringPreferences({ ...next, schema_version: 1 })
    if (!cleaned.ok) return false
    set({ preferences: cleaned.preferences })
    try {
      const { ok } = await bridge.write(cleaned.preferences)
      if (!ok) set({ preferences: previous })
      return ok
    } catch {
      set({ preferences: previous })
      return false
    }
  },

  reset: () => {
    loading = null
    set({ preferences: emptyEngineeringPreferences(), status: 'idle', readOnly: false })
  }
}))

/** The document to attach to a SOL turn, or null when there is nothing to say
 *  (empty document, or not running under the desktop app). Loads on demand so a
 *  turn sent before Home was ever opened still carries the conventions. */
export async function preferencesForTurn(): Promise<EngineeringPreferences | null> {
  await usePreferencesStore.getState().load()
  const { status, preferences } = usePreferencesStore.getState()
  if (status !== 'ready' || isEmptyPreferences(preferences)) return null
  return preferences
}

// SEC review H1 (H3): the document is machine-local and shared by every
// account that signs in here, so the STORE must not carry one account's copy
// into the next account's turns — any identity change (sign-out or an in-place
// session swap) drops it; the next turn re-reads the file under the new
// identity. Same lane-owned subscription the SOL chat store uses.
useAuthStore.subscribe((state, prev) => {
  if (prev.status !== 'authenticated') return
  const signedOut = state.status === 'unauthenticated'
  const identitySwapped = state.status === 'authenticated' && state.user?.email !== prev.user?.email
  if (signedOut || identitySwapped) usePreferencesStore.getState().reset()
})
