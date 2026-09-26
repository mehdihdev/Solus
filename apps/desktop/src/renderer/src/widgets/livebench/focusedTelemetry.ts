import { api } from '../../lib/api/client'
import type { BenchDeviceRecent } from '../../lib/api/resources'
import type { ObserverEventOut, RecentValuesOut } from './telemetry'

/** Device discovery includes local sessions and external producers. Focus filtering
 * belongs to the API's authorized topology projection, never a client heuristic. */
export async function focusedTelemetry(
  projectId: string,
  entityId: string,
  signal: AbortSignal
): Promise<{
  recent: RecentValuesOut
  events: ObserverEventOut[]
}> {
  const base = `/projects/${projectId}/bench`
  const [observed, events] = await Promise.all([
    api.request<{ device_ids: string[] }>(`${base}/telemetry-devices`, { signal }),
    api.request<ObserverEventOut[]>(`${base}/events?limit=50`, { signal })
  ])
  signal.throwIfAborted()
  const ids = [...new Set(observed.device_ids)]
  if (ids.length === 0) {
    const recent = await api.request<RecentValuesOut>(`${base}/recent/${entityId}`, { signal })
    // An exact-entity series alone cannot establish an event's device identity.
    return { recent, events: [] }
  }
  const devices: BenchDeviceRecent[] = []
  for (let offset = 0; offset < ids.length; offset += 16) {
    signal.throwIfAborted()
    const params = new URLSearchParams({ focus_entity_id: entityId, limit: '60' })
    for (const id of ids.slice(offset, offset + 16)) params.append('device_id', id)
    const batch = await api.request<{ devices: BenchDeviceRecent[] }>(
      `${base}/device-recent?${params}`,
      { signal }
    )
    devices.push(...batch.devices)
  }
  const keys = new Set(
    devices.flatMap((device) =>
      device.signals.map((series) => JSON.stringify([device.device_id, series.signal]))
    )
  )
  return {
    recent: {
      entity_id: entityId,
      signals: devices.flatMap((device) =>
        device.signals.map((series) => ({
          ...series,
          key: JSON.stringify([device.device_id, series.signal]),
          signal: `${device.device_id} · ${series.signal}`
        }))
      )
    },
    events: events.filter((event) => keys.has(JSON.stringify([event.device_id, event.signal])))
  }
}
