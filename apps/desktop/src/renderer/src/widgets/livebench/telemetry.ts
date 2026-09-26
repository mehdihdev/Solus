// LB-05: pure helpers for the Live Bench widget — kept out of the component file
// so react-refresh sees a components-only module, and so they unit-test directly.

export interface RecentSampleOut {
  readonly timestamp: string
  readonly value: number
}

export interface SignalSeriesOut {
  /** Stable pair identity when a focused robot spans multiple devices. */
  readonly key?: string
  readonly signal: string
  readonly points: readonly RecentSampleOut[]
}

export interface RecentValuesOut {
  readonly entity_id: string
  readonly signals: readonly SignalSeriesOut[]
}

export interface ObserverEventOut {
  readonly kind: string
  readonly device_id: string
  readonly signal: string
  readonly at: string
  readonly value: number | null
}

export type StreamState = 'live' | 'stale' | 'no-stream'

const LIVE_MS = 3_000
const STALE_MS = 15_000

/** Honest connection state: a pure function of the newest sample's age. */
export function streamState(latestIso: string | null, nowMs: number): StreamState {
  if (latestIso === null) return 'no-stream'
  const age = nowMs - Date.parse(latestIso)
  if (!Number.isFinite(age) || age < 0) return 'no-stream'
  if (age <= LIVE_MS) return 'live'
  if (age <= STALE_MS) return 'stale'
  return 'no-stream'
}

/** The newest sample timestamp across all series, or null when nothing streamed. */
export function latestOf(series: readonly SignalSeriesOut[]): string | null {
  let latest: string | null = null
  for (const s of series) {
    const last = s.points[s.points.length - 1]
    if (last && (latest === null || last.timestamp > latest)) latest = last.timestamp
  }
  return latest
}

/** Polyline segments for one series, broken where the stream gapped (>3× median dt). */
export function chartSegments(
  points: readonly RecentSampleOut[],
  width: number,
  height: number,
  domain?: { tMin: number; tMax: number; vMin: number; vMax: number }
): string[] {
  if (points.length < 2) return []
  const times = points.map((p) => Date.parse(p.timestamp))
  const values = points.map((p) => p.value)
  const { tMin, tMax, vMin, vMax } = domain ?? {
    tMin: times[0],
    tMax: times[times.length - 1],
    vMin: Math.min(...values),
    vMax: Math.max(...values)
  }
  const tSpan = Math.max(tMax - tMin, 1)
  const vSpan = Math.max(vMax - vMin, 1e-9)
  const deltas = times.slice(1).map((t, i) => t - times[i])
  const sorted = [...deltas].sort((a, b) => a - b)
  const gapAfter = 3 * Math.max(sorted[Math.floor(sorted.length / 2)], 1)

  const segments: string[] = []
  let current: string[] = []
  times.forEach((time, i) => {
    const x = (((time - tMin) / tSpan) * width).toFixed(1)
    const y = (height - ((values[i] - vMin) / vSpan) * height).toFixed(1)
    if (i > 0 && time - times[i - 1] > gapAfter) {
      if (current.length > 1) segments.push(current.join(' '))
      current = []
    }
    current.push(`${x},${y}`)
  })
  if (current.length > 1) segments.push(current.join(' '))
  return segments
}

/** Match the main signal pane's eight-second window. Retain a wholly stale feed
 * so its timestamps still explain STALE/NO STREAM rather than inventing emptiness. */
export function currentSeries(
  series: readonly SignalSeriesOut[],
  nowMs: number
): readonly SignalSeriesOut[] {
  const past = series.flatMap((one) => {
    const points = one.points.filter((point) => {
      const age = nowMs - Date.parse(point.timestamp)
      return Number.isFinite(age) && age >= 0
    })
    return points.length ? [{ ...one, points }] : []
  })
  const current = past.flatMap((one) => {
    const points = one.points.filter((point) => {
      const age = nowMs - Date.parse(point.timestamp)
      return age >= 0 && age <= 8000
    })
    return points.length ? [{ ...one, points }] : []
  })
  return current.length ? current : past
}
