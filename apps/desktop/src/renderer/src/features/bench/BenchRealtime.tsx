import { createContext, useContext, useEffect, useState } from 'react'
import { apiBaseUrl } from '../../lib/api/client'
import {
  getBenchDeviceRecent,
  type BenchDeviceRecent,
  type BenchSession
} from '../../lib/api/resources'
import { useAuthStore } from '../../store/authStore'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../graph/workspaceSession'
import type { ObserverEventOut } from '../../widgets/livebench/telemetry'
import { connectBenchStream } from './benchStream'
import { getSignalAnomalies } from './signalAnomalies'

export interface BenchRealtimeData {
  project: string | null
  ready: boolean
  blocked: boolean
  clock: number
  devices: BenchDeviceRecent[]
  receivedAt: number
  focusId?: string
  focused: BenchDeviceRecent[] | null
  events: ObserverEventOut[]
  eventsFailed: boolean
}
export const BenchRealtimeContext = createContext<BenchRealtimeData | null>(null)
export function useBenchRealtimeData(project: string): BenchRealtimeData | null {
  const value = useContext(BenchRealtimeContext)
  return value?.project === project ? value : null
}
interface Snapshot {
  blocked?: boolean
  devices: BenchDeviceRecent[]
  at: number
  ready: boolean
}
export function useBenchRealtime(
  project: string | null,
  sessions: BenchSession[] | null,
  focusId?: string
): BenchRealtimeData {
  const generation = useWorkspaceSessionGeneration()
  const [clock, setClock] = useState(Date.now)
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const token = useAuthStore((state) => state.accessToken)
  const identity = useAuthStore((state) => `${state.status}:${state.user?.email ?? ''}`)
  const sessionKey = [
    ...new Set((sessions ?? []).filter((s) => s.status !== 'ended').map((s) => s.id))
  ]
    .sort()
    .join('\n')
  const scope = JSON.stringify([project, identity, generation, token, sessionKey])
  const [state, setState] = useState<{ scope: string; snapshots: Record<string, Snapshot> } | null>(
    null
  )
  useEffect(() => {
    if (!project || !token || !sessionKey) return
    let active = true
    const current = (): boolean =>
      active &&
      workspaceSessionGeneration() === generation &&
      useAuthStore.getState().accessToken === token
    const stops = sessionKey.split('\n').map((session) =>
      connectBenchStream({
        baseUrl: apiBaseUrl,
        project,
        session,
        token,
        receive: (devices) => {
          if (current())
            setState((previous) => ({
              scope,
              snapshots: {
                ...(previous?.scope === scope ? previous.snapshots : {}),
                [session]: { devices, at: Date.now(), ready: true }
              }
            }))
        },
        unavailable: (blocked = false) => {
          if (current())
            setState((previous) => ({
              scope,
              snapshots: {
                ...(previous?.scope === scope ? previous.snapshots : {}),
                [session]: {
                  ...retainedSnapshot(
                    blocked,
                    previous?.scope === scope ? previous.snapshots[session] : undefined
                  ),
                  ready: false,
                  blocked
                }
              }
            }))
        }
      })
    )
    return () => {
      active = false
      stops.forEach((stop) => stop())
    }
  }, [project, token, sessionKey, scope, generation])
  const snapshots = state?.scope === scope ? state.snapshots : {}
  const ready = !!sessionKey && sessionKey.split('\n').every((id) => snapshots[id]?.ready)
  const byDevice = new Map<string, BenchDeviceRecent>()
  Object.values(snapshots)
    .sort((a, b) => a.at - b.at)
    .forEach((snapshot) =>
      snapshot.devices.forEach((device) => byDevice.set(device.device_id, device))
    )
  const devices = [...byDevice.values()]
  const receivedAt = Math.max(0, ...Object.values(snapshots).map((s) => s.at))
  const signature = JSON.stringify(devices.map((d) => [d.device_id, d.resolved_entity_id]).sort())
  const allowed = useFocusedDevices(project, scope, signature, focusId, generation)
  const evidence = useRealtimeEvidence(project, scope, ready, generation)
  return {
    project,
    ready: ready && (!focusId || allowed !== null),
    blocked: Object.values(snapshots).some((s) => s.blocked),
    clock: Math.max(clock, receivedAt),
    devices,
    receivedAt,
    focusId,
    focused: !focusId
      ? devices
      : allowed === null
        ? null
        : devices.filter((d) => allowed.includes(d.device_id)),
    ...evidence
  }
}
function useFocusedDevices(
  project: string | null,
  scope: string,
  signature: string,
  focusId: string | undefined,
  generation: number
): string[] | null {
  const key = JSON.stringify([scope, signature, focusId])
  const [state, setState] = useState<{ key: string; ids: string[] } | null>(null)
  useEffect(() => {
    if (!project || !focusId) return
    let active = true
    const ids = (JSON.parse(signature) as [string, string | null][]).map(([id]) => id)
    const load = async (): Promise<void> => {
      try {
        const authorized: string[] = []
        for (let offset = 0; offset < ids.length; offset += 16) {
          const rows = await getBenchDeviceRecent(project, ids.slice(offset, offset + 16), {
            focusEntityId: focusId,
            limit: 1
          })
          if (!active || generation !== workspaceSessionGeneration()) return
          authorized.push(...rows.map((d) => d.device_id))
        }
        if (active && generation === workspaceSessionGeneration())
          setState({ key, ids: authorized })
      } catch {
        /* Fail closed until a new focus or topology projection succeeds. */
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [project, key, signature, focusId, generation])
  return state?.key === key ? state.ids : null
}
function useRealtimeEvidence(
  project: string | null,
  scope: string,
  ready: boolean,
  generation: number
): { events: ObserverEventOut[]; eventsFailed: boolean } {
  const [state, setState] = useState<{ scope: string; events: ObserverEventOut[] | null } | null>(
    null
  )
  useEffect(() => {
    if (!project || !ready) return
    let active = true,
      busy = false
    const poll = async (): Promise<void> => {
      if (busy) return
      busy = true
      const events = await getSignalAnomalies(project).catch(() => null)
      if (active && generation === workspaceSessionGeneration()) setState({ scope, events })
      busy = false
    }
    void poll()
    const timer = setInterval(() => void poll(), 5000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [project, ready, scope, generation])
  return {
    events: state?.scope === scope ? (state.events ?? []) : [],
    eventsFailed: state?.scope !== scope || state.events === null
  }
}

function retainedSnapshot(
  blocked: boolean,
  previous: Snapshot | undefined
): Pick<Snapshot, 'devices' | 'at'> {
  return { devices: blocked ? [] : (previous?.devices ?? []), at: previous?.at ?? 0 }
}
