import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from './workspaceSession'
import { useEffect, useRef, useState } from 'react'
import { apiBaseUrl } from '../../lib/api/client'
import { ApiError } from '../../lib/api/envelope.types'
import { streamProjectEvents, type ProjectEvent } from '../../lib/api/projectEvents'
import { useAuthStore } from '../../store/authStore'

/** Listen only to Solus's existing committed-graph event stream. Reconnects
 * refresh graph data to recover missed hints, never provider data. */
export function useWorkspaceEvents(
  projectId: string | null,
  onChanged: () => void,
  onReady?: () => void
): string | null {
  const generation = useWorkspaceSessionGeneration()
  const token = useAuthStore((state) => state.accessToken)
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const [error, setError] = useState<string | null>(null)
  const connected = useRef<string | null>(null)
  useEffect(() => {
    setError(null)
    if (!projectId || !token) return
    const key = `${identity}:${projectId}`
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const current = (): boolean => {
      const auth = useAuthStore.getState()
      return (
        workspaceSessionGeneration() === generation &&
        !controller.signal.aborted &&
        `${auth.status}:${auth.user?.email ?? ''}` === identity
      )
    }
    const receive = (event: ProjectEvent): void => {
      setError(null)
      if (event === 'ready' && connected.current !== key) onReady?.()
      if (event === 'graph.changed' || connected.current === key) onChanged()
      connected.current = key
    }
    const listen = async (): Promise<void> => {
      try {
        for await (const event of streamProjectEvents({
          projectId,
          baseUrl: apiBaseUrl,
          getToken: () => token,
          signal: controller.signal
        })) {
          if (!current()) return
          receive(event)
        }
      } catch (cause) {
        if (!current()) return
        if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
          setError('Live updates unavailable. Check project access.')
          return
        }
      }
      if (current()) {
        setError('Live updates disconnected. Reconnecting…')
        timer = setTimeout(() => {
          void listen()
        }, 5_000)
      }
    }
    void listen()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [projectId, identity, token, onChanged, onReady, generation])
  return error
}
