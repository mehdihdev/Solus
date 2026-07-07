// Current-user identity for the shell chrome, Home, and Settings. Loads the
// real profile (name/email/teams) when the workspace is linked to the API,
// and falls back to the auth-store email otherwise (dev bypass / offline).
import { useEffect, useState } from 'react'
import { getMe, type Me } from '../../lib/api/resources'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

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
  const linked = useWorkspaceStore((s) => s.linked)
  const authEmail = useAuthStore((s) => s.user?.email ?? '')
  const [me, setMe] = useState<Me | null>(null)
  const [status, setStatus] = useState<IdentityStatus>(linked ? 'loading' : 'offline')

  useEffect(() => {
    if (!linked) {
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
  }, [linked])

  return { status, me, name: me?.name ?? null, email: me?.email ?? authEmail }
}
