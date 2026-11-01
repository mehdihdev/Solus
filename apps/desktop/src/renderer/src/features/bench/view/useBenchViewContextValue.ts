// Wires the shared bench view for the Live Bench screen: loads it (on mount, `ready` and newer
// hints), resolves this user's role on the project's team, and indexes the live devices that
// plot groups and derived signals read.
import { useMemo, useState } from 'react'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { useMe } from '../../workspace/useMe'
import { canEditBenchView, type BenchViewContextValue } from './BenchViewContext'
import { useBenchView } from './useBenchView'
import { useBenchViewEvents } from './useBenchViewEvents'

export function useBenchViewContextValue(
  projectId: string | null,
  teamId: string | null,
  devices: readonly BenchDeviceRecent[],
  receivedAt: number
): BenchViewContextValue | null {
  const entry = useBenchView(projectId)
  useBenchViewEvents(projectId)
  const { me } = useMe()
  const canEdit = teamId ? canEditBenchView(me, teamId) : false
  const byId = useIndexedDevices(devices, `${projectId ?? ''}:${receivedAt}`)
  const view = entry?.view ?? null
  return useMemo(
    () => (projectId ? { projectId, view, canEdit, devices: byId } : null),
    [projectId, view, canEdit, byId]
  )
}

type DeviceIndex = Readonly<Record<string, BenchDeviceRecent>>

/** Re-index only when a new frame arrived: the caller rebuilds the device list every render,
 *  and a stable index keeps the derived evaluation from re-running on each clock tick. */
function useIndexedDevices(devices: readonly BenchDeviceRecent[], frameKey: string): DeviceIndex {
  const build = (): { key: string; index: DeviceIndex } => ({
    key: frameKey,
    index: Object.fromEntries(devices.map((device) => [device.device_id, device]))
  })
  const [cache, setCache] = useState(build)
  if (cache.key !== frameKey) {
    const next = build()
    setCache(next)
    return next.index
  }
  return cache.index
}
