// The signed-in user's ACCOUNT-scoped OAuth grants (SOLUSDEV-241 / I1):
// what Home lists, what the Sources wizard reuses to skip a second sign-in.
// Degrades to `offline` (dev bypass / unreachable API) like every other
// workspace hook, so surfaces show honest empty states rather than a spinner
// that never resolves.
import { useCallback, useEffect, useState } from 'react'
import {
  adoptConnections,
  listConnections,
  listLegacyConnections,
  revokeConnection,
  type Connection,
  type LegacyConnection
} from '../../lib/api/resources'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

export type AccountConnectionsStatus = 'loading' | 'ready' | 'offline'

export interface AccountConnectionsData {
  status: AccountConnectionsStatus
  connections: Connection[]
  /** Project-scoped grants not yet at account scope (SOLUSDEV-242 / H2). */
  legacy: LegacyConnection[]
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
  const [legacy, setLegacy] = useState<LegacyConnection[]>([])
  // Derived, not set: with fetching disabled there is nothing to load, and
  // the surfaces read `offline` without an effect having to write it.
  const status: AccountConnectionsStatus = fetchEnabled ? loaded : 'offline'

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) return
    try {
      // SOLUSDEV-242 (H2): legacy project-scoped grants for an account the
      // user has already proved bind to it BEFORE the list is read, so Home
      // never shows "Not connected" for a working account. A failed claim is
      // not a failed listing; the unclaimed ones list separately.
      await adoptConnections().catch(() => undefined)
      const [listed, unclaimed] = await Promise.all([
        listConnections(),
        listLegacyConnections().catch(() => [] as LegacyConnection[])
      ])
      setConnections(listed)
      setLegacy(unclaimed)
      setLoaded('ready')
    } catch {
      setConnections([])
      setLegacy([])
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

  return { status, connections, legacy, refresh: load, revoke }
}
