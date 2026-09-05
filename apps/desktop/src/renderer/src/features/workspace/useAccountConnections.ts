// The signed-in user's ACCOUNT-scoped OAuth grants (SOLUSDEV-241 / I1):
// what Home lists, what the Sources wizard reuses to skip a second sign-in.
// Degrades to `offline` (dev bypass / unreachable API) like every other
// workspace hook, so surfaces show honest empty states rather than a spinner
// that never resolves.
import { useCallback, useEffect, useState } from 'react'
import {
  adoptConnections,
  listConnections,
  revokeConnection,
  type Connection
} from '../../lib/api/resources'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

export type AccountConnectionsStatus = 'loading' | 'ready' | 'offline'

export interface AccountConnectionsData {
  status: AccountConnectionsStatus
  connections: Connection[]
  refresh: () => Promise<void>
  /** Revoke a grant. Resolves false on failure so the caller can say so. */
  revoke: (connectionId: string) => Promise<boolean>
}

/** The linked, usable account for a provider, if the user has one. */
export function linkedAccountFor(
  connections: readonly Connection[],
  provider: string
): Connection | null {
  return connections.find((c) => c.provider === provider && c.status === 'connected') ?? null
}

export function useAccountConnections(): AccountConnectionsData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [loaded, setLoaded] = useState<AccountConnectionsStatus>('loading')
  const [connections, setConnections] = useState<Connection[]>([])
  // Derived, not set: with fetching disabled there is nothing to load, and
  // the surfaces read `offline` without an effect having to write it.
  const status: AccountConnectionsStatus = fetchEnabled ? loaded : 'offline'

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) return
    try {
      // SOLUSDEV-242 (H2): a project-scoped grant from before I1 becomes the
      // account it always was, without a sign-in — before the list is read,
      // so Home never shows a stale "Not connected" for a working account. A
      // failed adoption is not a failed listing.
      await adoptConnections().catch(() => undefined)
      const listed = await listConnections()
      setConnections(listed)
      setLoaded('ready')
    } catch {
      setConnections([])
      setLoaded('offline')
    }
  }, [fetchEnabled])

  useEffect(() => {
    // Deferred a tick: the first read lands after mount, never inside it.
    let active = true
    void Promise.resolve().then(() => {
      if (active) void load()
    })
    return () => {
      active = false
    }
  }, [load])

  const revoke = useCallback(
    async (connectionId: string): Promise<boolean> => {
      try {
        await revokeConnection(connectionId)
        await load().catch(() => undefined)
        return true
      } catch {
        return false
      }
    },
    [load]
  )

  return { status, connections, refresh: load, revoke }
}
