import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from './workspaceSession'
import { useEffect, useState } from 'react'
import { apiBaseUrl } from '../../lib/api/client'
import { ApiError } from '../../lib/api/envelope.types'
import type { DetectedDeviceOut } from '../../lib/api/hardware'
import { streamProjectEvents, type ProjectEvent } from '../../lib/api/projectEvents'
import { useAuthStore } from '../../store/authStore'
import { markSafely } from '../../lib/perf/marks'

/** Listen only to Solus's existing committed-graph event stream. `ready` (first
 * connect and every reconnect) runs the cheap validation in onReady; only
 * `graph.changed` runs onChanged. Never provider data. */
export function useWorkspaceEvents(
  projectId: string | null,
  onChanged: () => void,
  onReady?: () => void,
  onDevices?: (devices: DetectedDeviceOut[]) => void
): string | null {
  const generation = useWorkspaceSessionGeneration()
  const token = useAuthStore((state) => state.accessToken)
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setError(null)
    if (!projectId || !token) return
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
      if (typeof event === 'object') {
        markSafely('hw:frame_received')
        onDevices?.(event.devices)
      } else if (event === 'ready') onReady?.()
      else onChanged()
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
  }, [projectId, identity, token, onChanged, onReady, onDevices, generation])
  return error
}
