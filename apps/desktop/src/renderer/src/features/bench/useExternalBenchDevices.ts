// Observed HTTP producers share the existing telemetry feed, without owning a port.
import { useEffect, useState } from 'react'
import { api } from '../../lib/api/client'
import { useAuthStore } from '../../store/authStore'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../graph/workspaceSession'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export function useExternalBenchDevices(projectId: string | null, enabled: boolean): string[] {
  const online = useWorkspaceFetchEnabled()
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const generation = useWorkspaceSessionGeneration()
  const scope = JSON.stringify([identity, projectId, generation])
  const on = online && enabled && projectId !== null
  const [result, setResult] = useState<{ scope: string; ids: string[] } | null>(null)
  useEffect(() => {
    if (!on || !projectId) return
    let live = true
    let inFlight = false
    const controller = new AbortController()
    const load = async (): Promise<void> => {
      if (inFlight) return
      inFlight = true
      try {
        const data = await api.request<{ device_ids: string[] }>(
          `/projects/${encodeURIComponent(projectId)}/bench/telemetry-devices`,
          { signal: controller.signal }
        )
        if (live && workspaceSessionGeneration() === generation) {
          setResult({ scope, ids: [...new Set(data.device_ids)].sort() })
        }
      } catch {
        // Discovery failure does not establish device removal. Scope checks hide
        // retained inventory immediately across account/project boundaries.
      } finally {
        inFlight = false
      }
    }
    void load()
    const timer = setInterval(() => void load(), 5000)
    return () => {
      live = false
      controller.abort()
      clearInterval(timer)
    }
  }, [projectId, on, scope, generation])
  return on && result?.scope === scope ? result.ids : []
}
