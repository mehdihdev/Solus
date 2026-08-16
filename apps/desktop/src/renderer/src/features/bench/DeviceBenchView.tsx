// Device-keyed telemetry view (SOLUSDEV-72): serves sessions whose devices
// have NO graph entity yet — one panel per streaming device id, fed by ONE
// batched /bench/device-recent poll per cycle (per-device 1 Hz polling of a
// 10-joint sim was 600 req/min against a 120/min shared budget; batched 2.5 s
// is 24 flat). Reuses the Live Bench visual language without touching the
// shared LiveBenchWidget. Honest by construction: stream state comes from
// data timestamps, failures say so, empty says so, overflow says so.
import { useEffect, useState } from 'react'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { getBenchDeviceRecent, type BenchDeviceRecent } from '../../lib/api/resources'
import {
  chartSegments,
  latestOf,
  streamState,
  type StreamState
} from '../../widgets/livebench/telemetry'

export const POLL_MS = 2_500
/** Panel cap — also keeps the batch inside the route's 16-id limit. */
export const MAX_DEVICE_PANELS = 8
const RECENT_LIMIT = 60
const CHART_SIGNALS_MAX = 4

const STATE_LABEL: Record<StreamState, string> = {
  live: 'LIVE DATA',
  stale: 'STALE',
  'no-stream': 'NO STREAM'
}

interface BatchData {
  readonly byId: Readonly<Record<string, BenchDeviceRecent>>
  readonly fetchedAtMs: number
}

function DevicePanel({
  deviceId,
  recent,
  fetchedAtMs,
  failed
}: {
  deviceId: string
  recent: BenchDeviceRecent | undefined
  fetchedAtMs: number | null
  failed: boolean
}): React.JSX.Element {
  return (
    <Card pad={16} style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <Mono size={11} color="var(--tx)" style={{ flex: 1 }}>
          {deviceId}
        </Mono>
        {recent && fetchedAtMs !== null && (
          <Mono size={8.5} color="var(--mut)" style={{ letterSpacing: '0.06em' }}>
            {STATE_LABEL[streamState(latestOf(recent.signals), fetchedAtMs)]}
          </Mono>
        )}
      </div>
      <PanelBody deviceId={deviceId} recent={recent} failed={failed} />
    </Card>
  )
}

function PanelBody({
  deviceId,
  recent,
  failed
}: {
  deviceId: string
  recent: BenchDeviceRecent | undefined
  failed: boolean
}): React.JSX.Element {
  if (failed) {
    return (
      <p role="alert" style={{ color: 'var(--mut)', fontSize: 12 }}>
        Telemetry is unavailable for {deviceId}.
      </p>
    )
  }
  if (recent === undefined) {
    return (
      <p role="status" style={{ color: 'var(--mut)', fontSize: 12 }}>
        Connecting to the bench…
      </p>
    )
  }
  if (recent.signals.length === 0) {
    return (
      <p role="status" style={{ color: 'var(--mut)', fontSize: 12 }}>
        No recent values from {deviceId} — nothing to show yet.
      </p>
    )
  }
  return (
    <div>
      <ul style={{ margin: '8px 0', paddingLeft: 0, listStyle: 'none' }}>
        {recent.signals.map((series) => {
          const last = series.points[series.points.length - 1]
          return (
            <li key={series.signal} className="font-mono" style={{ fontSize: 12 }}>
              {series.signal}: {last ? last.value : '—'}
            </li>
          )
        })}
      </ul>
      {recent.signals.slice(0, CHART_SIGNALS_MAX).map((series) => (
        <svg
          key={series.signal}
          viewBox="0 0 240 48"
          role="img"
          aria-label={`${series.signal} rolling chart`}
          style={{ width: '100%', height: '3rem' }}
        >
          {chartSegments(series.points, 240, 48).map((seg) => (
            <polyline key={seg} points={seg} fill="none" stroke="currentColor" strokeWidth="1.5" />
          ))}
        </svg>
      ))}
    </div>
  )
}

export function DeviceBenchView({
  projectId,
  deviceIds
}: {
  projectId: string
  deviceIds: readonly string[]
}): React.JSX.Element {
  const visible = deviceIds.slice(0, MAX_DEVICE_PANELS)
  const overflow = deviceIds.length - visible.length
  const [data, setData] = useState<BatchData | null>(null)
  const [failed, setFailed] = useState(false)
  // Stable dependency for the id list — effects compare by value, not array.
  const visibleKey = visible.join('\n')

  useEffect(() => {
    const ids = visibleKey.split('\n').filter(Boolean)
    if (ids.length === 0) return
    let live = true
    async function poll(): Promise<void> {
      try {
        const devices = await getBenchDeviceRecent(projectId, ids, { limit: RECENT_LIMIT })
        if (!live) return
        setData({
          byId: Object.fromEntries(devices.map((d) => [d.device_id, d])),
          fetchedAtMs: Date.now()
        })
        setFailed(false)
      } catch {
        if (live) setFailed(true)
      }
    }
    void poll()
    const interval = setInterval(() => void poll(), POLL_MS)
    return () => {
      live = false
      clearInterval(interval)
    }
  }, [projectId, visibleKey])

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', padding: 20 }}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', marginBottom: 12 }}>
        Streaming devices from active bench sessions. Focus an entity in the Context Model for the
        entity-scoped view.
      </div>
      {visible.map((deviceId) => (
        <DevicePanel
          key={deviceId}
          deviceId={deviceId}
          recent={data?.byId[deviceId]}
          fetchedAtMs={data?.fetchedAtMs ?? null}
          failed={failed}
        />
      ))}
      {overflow > 0 && (
        <div style={{ fontSize: 12, color: 'var(--mut)' }}>+{overflow} more devices streaming</div>
      )}
    </div>
  )
}
