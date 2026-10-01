// The user's live channel (ADR-037), mounted ONCE in WorkspaceShell. Frames are
// hints: each one bumps the live revisions it names and the REST hooks refetch.
// Refreshes are quiet by decision — no toast, no new UI. A fresh `ready` (first
// connect, every reconnect, a changed team set) revalidates everything
// account-scoped, because frames may have been missed while disconnected.
import { useEffect } from 'react'
import { streamAccountEvents, type AccountEvent } from '../../lib/api/accountEvents'
import { useAuthStore } from '../../store/authStore'
import { liveKeys, useLiveRevisionStore } from '../../store/liveRevisionStore'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'
import { keysForAccountEvent } from './accountEventKeys'
import { runReconnectingStream } from './reconnect'

function applyAccountEvent(event: AccountEvent): void {
  const store = useLiveRevisionStore.getState()
  store.bump(keysForAccountEvent(event))
  if (event.type === 'ready') store.bumpWhere(liveKeys.isTeamKey)
}

export function useAccountEvents(): void {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const token = useAuthStore((state) => state.accessToken)
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  useEffect(() => {
    if (!fetchEnabled || !token) return
    const controller = new AbortController()
    const { setAccountStream } = useLiveRevisionStore.getState()
    const current = (): boolean => {
      const auth = useAuthStore.getState()
      return (
        !controller.signal.aborted &&
        auth.accessToken === token &&
        `${auth.status}:${auth.user?.email ?? ''}` === identity
      )
    }
    void runReconnectingStream<AccountEvent>({
      signal: controller.signal,
      open: (signal) => streamAccountEvents(signal),
      isReady: (event) => event.type === 'ready',
      onEvent: (event) => {
        if (current()) applyAccountEvent(event)
      },
      onPhase: (phase) => {
        if (current()) setAccountStream(phase)
      }
    }).then((outcome) => {
      if (outcome !== 'aborted' && current()) setAccountStream('stopped')
    })
    return () => {
      controller.abort()
      setAccountStream('idle')
    }
  }, [fetchEnabled, token, identity])
}
