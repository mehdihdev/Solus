// Live hints for the shared bench view (ADR-037; wireflow live-bench-view.md §3). Its own
// subscription to the project stream (as FindingsPane keeps one), reacting only to `ready`
// (refetch unconditionally) and `bench.view_changed` (refetch when newer). Frames carry no
// content; the REST read is the only source of the view.
import { useEffect } from 'react'
import { apiBaseUrl, apiToken } from '../../../lib/api/client'
import { streamProjectEvents, type ProjectEvent } from '../../../lib/api/projectEvents'
import { useAuthStore } from '../../../store/authStore'
import { runReconnectingStream, type EventVerdict } from '../../live/reconnect'
import { useBenchViewStore } from './useBenchView'

function route(projectId: string, event: ProjectEvent): EventVerdict {
  const store = useBenchViewStore.getState()
  if (event === 'ready') void store.noteReady(projectId)
  else if (typeof event === 'object' && event.type === 'bench.view_changed')
    void store.noteHint(projectId, event.version)
  // A revoke ends this stream; a refreshed token re-runs the effect.
  else if (typeof event === 'object' && event.type === 'access.revoked') return 'stop'
}

export function useBenchViewEvents(projectId: string | null): void {
  const token = useAuthStore((state) => state.accessToken)
  useEffect(() => {
    if (!projectId || !token) return
    const controller = new AbortController()
    void runReconnectingStream<ProjectEvent>({
      signal: controller.signal,
      open: (signal) =>
        streamProjectEvents({ projectId, baseUrl: apiBaseUrl, getToken: apiToken, signal }),
      isReady: (event) => event === 'ready',
      onEvent: (event) => (controller.signal.aborted ? 'stop' : route(projectId, event)),
      onPhase: () => undefined
    })
    return () => controller.abort()
  }, [projectId, token])
}
