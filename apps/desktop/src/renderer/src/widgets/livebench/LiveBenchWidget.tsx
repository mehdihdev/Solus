// SOLUSDEV-66 (LB-05) — the Live Bench widget: live signal tiles, rolling charts,
// observer-event markers, honest stream state. Scoped to the FOCUSED part (never a
// global dashboard): `focus.entity` names the project and entity whose telemetry
// this shows, polled from the bench routes via the typed API client.
//
// Remount-safe by construction (CTR-01's real lifecycle obligation): all polling
// lives in one effect whose cleanup cancels the interval and in-flight state, so
// the canvas can unmount/remount on any layout change without a leak or a double
// poll. Stream state is derived from data timestamps, never asserted — this
// surface must not claim REAL/STREAMING for data it cannot vouch for
// (SOLUSDEV-152's rule).
import { useEffect, useState } from 'react'
import type { WidgetProps, WidgetRenderState } from '@solus/shared-types'
import { api } from '../../lib/api/client'
import {
  chartSegments,
  latestOf,
  streamState,
  type ObserverEventOut,
  type RecentValuesOut,
  type StreamState
} from './telemetry'

const POLL_MS = 1000
const CHART_SIGNALS_MAX = 4

const STATE_LABEL: Record<StreamState, string> = {
  live: 'LIVE DATA',
  stale: 'STALE',
  'no-stream': 'NO STREAM'
}

interface BenchData {
  readonly recent: RecentValuesOut
  readonly events: readonly ObserverEventOut[]
  readonly fetchedAtMs: number
}

function focusKeyOf(focus: WidgetProps['focus']): string | null {
  return focus ? `${focus.entity.projectId}/${focus.entity.entityId}` : null
}

export function LiveBenchWidget({ focus, onStateChange }: WidgetProps): React.JSX.Element {
  const [data, setData] = useState<BenchData | null>(null)
  const [failed, setFailed] = useState(false)
  const [lastFocusKey, setLastFocusKey] = useState<string | null>(focusKeyOf(focus))

  // Render-time adjustment (the documented "state depends on props" pattern):
  // a focus switch discards the previous part's data before the next paint,
  // without a cascading setState-in-effect.
  const focusKey = focusKeyOf(focus)
  if (focusKey !== lastFocusKey) {
    setLastFocusKey(focusKey)
    setData(null)
    setFailed(false)
  }

  useEffect(() => {
    if (focus === null) return
    const { projectId, entityId } = focus.entity
    let live = true

    async function poll(): Promise<void> {
      try {
        const [recent, events] = await Promise.all([
          api.request<RecentValuesOut>(`/projects/${projectId}/bench/recent/${entityId}`),
          api.request<ObserverEventOut[]>(`/projects/${projectId}/bench/events?limit=50`)
        ])
        if (!live) return
        setData({ recent, events, fetchedAtMs: Date.now() })
        setFailed(false)
      } catch {
        if (!live) return
        setFailed(true)
      }
    }

    void poll()
    const interval = setInterval(() => void poll(), POLL_MS)
    return () => {
      live = false
      clearInterval(interval)
    }
  }, [focus])

  const state: WidgetRenderState =
    focus === null ? 'empty' : failed ? 'error' : data === null ? 'loading' : 'ready'

  useEffect(() => {
    // Block body on purpose: the callback's return value must never become a
    // React cleanup function (a `push` returning a number crashes the unmount).
    onStateChange?.(state)
  }, [state, onStateChange])

  if (focus === null) {
    return <Note role="status">Focus a part to watch its telemetry.</Note>
  }
  if (state === 'error') {
    return <Note role="alert">Bench telemetry is unavailable for this part.</Note>
  }
  if (data === null) {
    return <Note role="status">Connecting to the bench…</Note>
  }
  if (data.recent.signals.length === 0) {
    return (
      <Note role="status">
        No telemetry yet for {focus.label ?? 'this part'} — nothing is streaming.
      </Note>
    )
  }
  return <BenchReadyView data={data} />
}

function Note({
  role,
  children
}: {
  role: 'status' | 'alert'
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <p role={role} style={{ color: 'var(--mut)' }}>
      {children}
    </p>
  )
}

function BenchReadyView({ data }: { data: BenchData }): React.JSX.Element {
  const connection = streamState(latestOf(data.recent.signals), data.fetchedAtMs)
  const charted = data.recent.signals.slice(0, CHART_SIGNALS_MAX)

  return (
    <div data-testid="livebench-widget">
      <p className="font-mono" data-testid="stream-state" style={{ color: 'var(--mut)' }}>
        {STATE_LABEL[connection]}
      </p>
      <ul data-testid="signal-tiles">
        {data.recent.signals.map((series) => {
          const last = series.points[series.points.length - 1]
          return (
            <li key={series.signal} className="font-mono">
              {series.signal}: {last ? last.value : '—'}
            </li>
          )
        })}
      </ul>
      {charted.map((series) => (
        <svg
          key={series.signal}
          data-testid={`chart-${series.signal}`}
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
      {data.events.length > 0 && (
        <ul data-testid="anomaly-markers">
          {data.events.map((event, i) => (
            <li key={`${event.at}-${i}`} role="note" style={{ color: 'var(--mut)' }}>
              ⚠ {event.kind}: {event.signal} on {event.device_id}
              {event.value !== null ? ` = ${event.value}` : ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
