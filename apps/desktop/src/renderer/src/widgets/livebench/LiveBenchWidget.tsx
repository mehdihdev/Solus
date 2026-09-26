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
import { focusedTelemetry } from './focusedTelemetry'
import { useBenchRealtimeData, type BenchRealtimeData } from '../../features/bench/BenchRealtime'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../../features/graph/workspaceSession'
import {
  chartSegments,
  currentSeries,
  latestOf,
  streamState,
  type ObserverEventOut,
  type RecentValuesOut,
  type StreamState
} from './telemetry'

const POLL_MS = 2500
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

function useWidgetData(focus: WidgetProps['focus']): {
  displayData: BenchData | null
  state: WidgetRenderState
} {
  const realtime = useBenchRealtimeData(focus?.entity.projectId ?? '')
  const streaming = isFocusedStream(realtime, focus)
  const generation = useWorkspaceSessionGeneration()
  const [data, setData] = useState<BenchData | null>(null)
  const [failed, setFailed] = useState(false)
  const [lastFocusKey, setLastFocusKey] = useState<string>(`${generation}:${focusKeyOf(focus)}`)

  // Render-time adjustment (the documented "state depends on props" pattern):
  // a focus switch discards the previous part's data before the next paint,
  // without a cascading setState-in-effect.
  const focusKey = `${generation}:${focusKeyOf(focus)}`
  if (focusKey !== lastFocusKey) {
    setLastFocusKey(focusKey)
    setData(null)
    setFailed(false)
  }

  useEffect(() => {
    if (focus === null || streaming || realtime?.blocked) return
    const { projectId, entityId } = focus.entity
    let live = true
    let inFlight = false
    const controller = new AbortController()

    async function poll(): Promise<void> {
      if (inFlight) return
      inFlight = true
      try {
        const { recent, events } = await focusedTelemetry(projectId, entityId, controller.signal)
        if (!live || workspaceSessionGeneration() !== generation) return
        setData({ recent, events, fetchedAtMs: Date.now() })
        setFailed(false)
      } catch {
        if (!live || workspaceSessionGeneration() !== generation) return
        setFailed(true)
      } finally {
        inFlight = false
      }
    }

    void poll()
    const interval = setInterval(() => void poll(), POLL_MS)
    return () => {
      live = false
      controller.abort()
      clearInterval(interval)
    }
  }, [focus, generation, streaming, realtime?.blocked])

  const displayData = streaming ? streamData(realtime, focus) : data
  const state = widgetState(
    focus,
    Boolean(realtime?.blocked || (failed && !streaming)),
    displayData
  )
  return { displayData, state }
}
function isFocusedStream(realtime: BenchRealtimeData | null, focus: WidgetProps['focus']): boolean {
  return !!realtime?.ready && realtime.focusId === focus?.entity.entityId
}
function streamData(
  realtime: BenchRealtimeData | null,
  focus: WidgetProps['focus']
): BenchData | null {
  const streamed = realtime?.focused ?? null
  if (streamed === null) return null
  return {
    recent: {
      entity_id: focus?.entity.entityId ?? '',
      signals: streamed.flatMap((device) =>
        device.signals.map((series) => ({
          ...series,
          key: JSON.stringify([device.device_id, series.signal]),
          signal: `${device.device_id} · ${series.signal}`
        }))
      )
    },
    events: realtime?.events ?? [],
    fetchedAtMs: realtime?.clock ?? 0
  }
}
function widgetState(
  focus: WidgetProps['focus'],
  failed: boolean,
  data: BenchData | null
): WidgetRenderState {
  if (focus === null) return 'empty'
  if (failed) return 'error'
  return data === null ? 'loading' : 'ready'
}
export function LiveBenchWidget({ focus, onStateChange }: WidgetProps): React.JSX.Element {
  const { displayData, state } = useWidgetData(focus)

  useEffect(() => {
    // Block body on purpose: the callback's return value must never become a
    // React cleanup function (a `push` returning a number crashes the unmount).
    onStateChange?.(state)
  }, [state, onStateChange])

  if (focus === null) {
    return (
      <Note role="status">
        Connected hardware appears automatically. Select a part to narrow its signals.
      </Note>
    )
  }
  if (state === 'error') {
    return <Note role="alert">Bench telemetry is unavailable for this part.</Note>
  }
  if (displayData === null) {
    return <Note role="status">Connecting to the bench…</Note>
  }
  if (displayData.recent.signals.length === 0) {
    return (
      <Note role="status">
        No telemetry yet for {focus.label ?? 'this part'} in this selection.
      </Note>
    )
  }
  return <BenchReadyView data={displayData} />
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
  const signals = currentSeries(data.recent.signals, data.fetchedAtMs)
  const connection = streamState(latestOf(signals), data.fetchedAtMs)
  const charted = signals.slice(0, CHART_SIGNALS_MAX)
  const keys = new Set(signals.map((series) => series.key))
  const events = data.events.filter((event) =>
    keys.has(JSON.stringify([event.device_id, event.signal]))
  )

  return (
    <div data-testid="livebench-widget">
      <p className="font-mono" data-testid="stream-state" style={{ color: 'var(--mut)' }}>
        {STATE_LABEL[connection]}
      </p>
      <ul data-testid="signal-tiles">
        {signals.map((series) => {
          const last = series.points[series.points.length - 1]
          return (
            <li key={series.key ?? series.signal} className="font-mono">
              {series.signal}: {last ? last.value : '—'}
            </li>
          )
        })}
      </ul>
      {charted.map((series) => (
        <svg
          key={series.key ?? series.signal}
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
      {events.length > 0 && (
        <ul data-testid="anomaly-markers">
          {events.map((event, i) => (
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
