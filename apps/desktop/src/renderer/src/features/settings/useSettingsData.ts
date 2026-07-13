// Live settings data for the Settings screen: loads profile + settings +
// subscription in parallel, reconciles SOL mode into the app-wide store
// (ADR-016), and exposes optimistic mutations that revert and surface the API
// error envelope on failure. Degrades to `offline` (dev bypass / unreachable)
// so the demo rendering can take over — mirrors useMe / useTeamData.
import { useCallback, useEffect, useState } from 'react'
import {
  apiToSolMode,
  getMe,
  getSettings,
  getSubscription,
  updateConsent,
  updateProfile,
  updateSolMode,
  type Me,
  type Subscription,
  type UserSettings
} from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'

export type SettingsStatus = 'loading' | 'ready' | 'offline'
export type SettingsField = 'sol_mode' | 'consent' | 'name'
export type SettingsErrors = Record<SettingsField, string | null>

export interface SettingsActions {
  /** Persist SOL mode to the backend + app-wide store; reverts on failure. */
  setSolMode: (mode: SolMode) => Promise<boolean>
  /** Toggle data-collection consent (ADR-011); reverts on failure. */
  setConsent: (consent: boolean) => Promise<boolean>
  /** Save the display name; validates non-blank locally first. */
  updateName: (name: string) => Promise<boolean>
  refresh: () => Promise<void>
}

export interface SettingsData {
  status: SettingsStatus
  profile: Me | null
  consent: boolean
  subscription: Subscription | null
  errors: SettingsErrors
  actions: SettingsActions
}

const NO_ERRORS: SettingsErrors = { sol_mode: null, consent: null, name: null }

interface LoadResult {
  me: Me
  settings: UserSettings
  sub: Subscription | null
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

/** Profile + settings are required; a missing subscription (404) is tolerated. */
async function loadSettings(): Promise<LoadResult> {
  const [me, settings] = await Promise.all([getMe(), getSettings()])
  const sub = await getSubscription().catch(() => null)
  return { me, settings, sub }
}

export function useSettingsData(): SettingsData {
  const linked = useWorkspaceStore((s) => s.linked)
  const setStoreSolMode = useSettingsStore((s) => s.setSolMode)

  const [status, setStatus] = useState<SettingsStatus>(linked ? 'loading' : 'offline')
  const [profile, setProfile] = useState<Me | null>(null)
  const [consent, setConsentState] = useState<boolean>(true)
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [errors, setErrors] = useState<SettingsErrors>(NO_ERRORS)

  const apply = useCallback(
    (r: LoadResult): void => {
      setProfile(r.me)
      setConsentState(r.settings.data_collection_consent)
      setStoreSolMode(apiToSolMode(r.settings.sol_mode))
      setSubscription(r.sub)
    },
    [setStoreSolMode]
  )

  useEffect(() => {
    if (!linked) {
      setStatus('offline')
      return
    }
    let cancelled = false
    setStatus('loading')
    loadSettings()
      .then((r) => {
        if (cancelled) return
        apply(r)
        setStatus('ready')
      })
      .catch(() => {
        if (!cancelled) setStatus('offline')
      })
    return () => {
      cancelled = true
    }
  }, [linked, apply])

  const setError = useCallback((field: SettingsField, message: string | null): void => {
    setErrors((prev) => ({ ...prev, [field]: message }))
  }, [])

  const setSolMode = useCallback(
    async (mode: SolMode): Promise<boolean> => {
      const previous = useSettingsStore.getState().solMode
      setStoreSolMode(mode)
      setError('sol_mode', null)
      try {
        await updateSolMode(mode)
        return true
      } catch (error) {
        setStoreSolMode(previous)
        setError('sol_mode', errorMessage(error, 'Could not update SOL mode.'))
        return false
      }
    },
    [setStoreSolMode, setError]
  )

  const setConsent = useCallback(
    async (next: boolean): Promise<boolean> => {
      const previous = consent
      setConsentState(next)
      setError('consent', null)
      try {
        await updateConsent(next)
        return true
      } catch (error) {
        setConsentState(previous)
        setError('consent', errorMessage(error, 'Could not save your choice.'))
        return false
      }
    },
    [consent, setError]
  )

  const updateName = useCallback(
    async (name: string): Promise<boolean> => {
      const trimmed = name.trim()
      if (!trimmed) {
        setError('name', 'Name cannot be blank.')
        return false
      }
      setError('name', null)
      try {
        const me = await updateProfile({ name: trimmed })
        setProfile(me)
        return true
      } catch (error) {
        setError('name', errorMessage(error, 'Could not save your name.'))
        return false
      }
    },
    [setError]
  )

  const refresh = useCallback(async (): Promise<void> => {
    try {
      apply(await loadSettings())
    } catch {
      // Keep the prior snapshot; a transient refresh failure isn't fatal.
    }
  }, [apply])

  return {
    status,
    profile,
    consent,
    subscription,
    errors,
    actions: { setSolMode, setConsent, updateName, refresh }
  }
}
