// Current-user identity for the shell chrome, Home, and Settings. Loads the
// real profile (name/email/teams) when the workspace is linked to the API,
// and falls back to the auth-store email otherwise (dev bypass / offline).
import { useEffect, useState } from 'react'
import { getMe, type Me } from '../../lib/api/resources'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

export type IdentityStatus = 'loading' | 'ready' | 'offline'

export interface Identity {
  status: IdentityStatus
  me: Me | null
  name: string | null
  email: string
}

/** Derive a human display name from a profile, falling back to the email local part. */
export function displayName(name: string | null, email: string): string {
  if (name && name.trim()) return name.trim()
  if (email) return email.split('@')[0].replace(/[._-]/g, ' ')
  return 'You'
}

export function useMe(): Identity {
  // An authenticated session always loads the real profile; `linked` alone only
  // unlocks the fetch for non-authenticated (dev-bypass) sessions. A signed-in
  // user who skipped onboarding must still get their real name/teams, not just
  // the auth-email fallback (SOLUSDEV-152 — matches Home/Team/notifications).
  const fetchEnabled = useWorkspaceFetchEnabled()
  const authEmail = useAuthStore((s) => s.user?.email ?? '')
  const [me, setMe] = useState<Me | null>(null)
  const [status, setStatus] = useState<IdentityStatus>(fetchEnabled ? 'loading' : 'offline')

  useEffect(() => {
    if (!fetchEnabled) {
      setStatus('offline')
      return
    }
    let cancelled = false
    getMe()
      .then((profile) => {
        if (cancelled) return
        setMe(profile)
        setStatus('ready')
      })
      .catch(() => {
        if (!cancelled) setStatus('offline')
      })
    return () => {
      cancelled = true
    }
  }, [fetchEnabled])

  return { status, me, name: me?.name ?? null, email: me?.email ?? authEmail }
}
