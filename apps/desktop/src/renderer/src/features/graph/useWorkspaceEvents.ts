import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from './workspaceSession'
import { useEffect, useState } from 'react'
import { apiBaseUrl } from '../../lib/api/client'
import type { DetectedDeviceOut } from '../../lib/api/hardware'
import { streamProjectEvents, type ProjectEvent } from '../../lib/api/projectEvents'
import { useAuthStore } from '../../store/authStore'
import { liveKeys, useLiveRevisionStore } from '../../store/liveRevisionStore'
import { runReconnectingStream } from '../live/reconnect'
import { markSafely } from '../../lib/perf/marks'

const UNAVAILABLE = 'Live updates unavailable. Check project access.'
const RECONNECTING = 'Live updates disconnected. Reconnecting…'

type HintEvent = Exclude<ProjectEvent, string | { type: 'hardware.devices_changed' }>

/** Project frames that only invalidate Solus REST data: bump the named key. */
function applyLiveHint(projectId: string, event: HintEvent): void {
  const live = useLiveRevisionStore.getState()
  switch (event.type) {
    case 'layout.changed':
      live.recordLayoutVersion(projectId, event.version)
      live.bump([liveKeys.projectLayout(projectId)])
      return
    case 'sources.changed':
      live.bump([liveKeys.projectSources(projectId)])
      return
    case 'project.updated':
      live.bump([liveKeys.projectDetail(projectId)])
      return
    case 'job.updated':
      live.bump([liveKeys.projectJobs(projectId)])
      return
    case 'access.revoked':
      return
  }
}

/** Listen only to Solus's existing committed-graph event stream. `ready` (first
 * connect and every reconnect) runs the cheap validation in onReady; only
 * `graph.changed` runs onChanged. Layout/sources/project/job frames bump live
 * revisions that the REST hooks refetch on (ADR-037). Never provider data. */
export function useWorkspaceEvents(
  projectId: string | null,
  onChanged: () => void,
  onReady?: () => void,
  onDevices?: (devices: DetectedDeviceOut[]) => void
): string | null {
  const generation = useWorkspaceSessionGeneration()
  const token = useAuthStore((state) => state.accessToken)
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  // The message belongs to the scope that raised it, so changing project, user
  // or token reads as "no error" without resetting state inside the effect.
  const scope = `${projectId ?? ''}|${identity}|${token ?? ''}|${generation}`
  const [raised, setRaised] = useState<{ scope: string; message: string | null }>({
    scope,
    message: null
  })
  useEffect(() => {
    if (!projectId || !token) return
    const setError = (message: string | null): void =>
      setRaised((previous) =>
        previous.scope === scope && previous.message === message ? previous : { scope, message }
      )
    const controller = new AbortController()
    const current = (): boolean => {
      const auth = useAuthStore.getState()
      return (
        workspaceSessionGeneration() === generation &&
        !controller.signal.aborted &&
        `${auth.status}:${auth.user?.email ?? ''}` === identity
      )
    }
    const receive = (event: ProjectEvent): 'stop' | void => {
      if (!current()) return 'stop'
      if (typeof event === 'object' && event.type === 'access.revoked') {
        setError(UNAVAILABLE)
        return 'stop'
      }
      setError(null)
      if (event === 'ready') onReady?.()
      else if (event === 'graph.changed') onChanged()
      else if (event.type === 'hardware.devices_changed') {
        markSafely('hw:frame_received')
        onDevices?.(event.devices)
      } else applyLiveHint(projectId, event)
    }
    void runReconnectingStream<ProjectEvent>({
      signal: controller.signal,
      open: (signal) =>
        streamProjectEvents({ projectId, baseUrl: apiBaseUrl, getToken: () => token, signal }),
      isReady: (event) => event === 'ready',
      onEvent: receive,
      onPhase: (phase) => {
        if (!current()) return
        if (phase === 'reconnecting') setError(RECONNECTING)
        else if (phase === 'connecting') setError(null)
      }
    }).then((outcome) => {
      if (outcome !== 'aborted' && current()) setError(UNAVAILABLE)
    })
    return () => controller.abort()
  }, [projectId, identity, token, onChanged, onReady, onDevices, generation, scope])
  return raised.scope === scope ? raised.message : null
}
