// React 19.2 development builds record a PerformanceMeasure for every component
// render and scheduler phase (the "Components ⚛" / "Scheduler ⚛" DevTools tracks)
// and never clear them. Live Bench re-renders many times a second, so the
// timeline grew by millions of entries until the renderer ran out of allocator
// space and crashed (white window). Sweep only React's entries; the app's own
// perf marks (marks.ts, `hw:*`) stay readable.
const REACT_NAME_PREFIX = '\u200b'
const REACT_TRACK_GROUP = 'Scheduler ⚛'
const REACT_COMPONENTS_TRACK = 'Components ⚛'
export const REACT_MEASURE_SWEEP_MS = 5000

export type MeasureTimeline = Pick<Performance, 'getEntriesByType' | 'clearMeasures'>

function isReactMeasure(entry: PerformanceEntry): boolean {
  if (entry.name.startsWith(REACT_NAME_PREFIX)) return true
  const devtools = (entry as PerformanceMeasure).detail?.devtools as
    | { track?: unknown; trackGroup?: unknown }
    | undefined
  return devtools?.trackGroup === REACT_TRACK_GROUP || devtools?.track === REACT_COMPONENTS_TRACK
}

/** Clears React's measures, once per distinct name; returns how many names. */
export function sweepReactMeasures(
  perf: MeasureTimeline | undefined = globalThis.performance
): number {
  if (!perf) return 0
  const names = new Set<string>()
  for (const entry of perf.getEntriesByType('measure')) {
    if (isReactMeasure(entry)) names.add(entry.name)
  }
  names.forEach((name) => perf.clearMeasures(name))
  return names.size
}

/** Sweeps every `everyMs`, and also as React's entries arrive: a covered or
 *  background window throttles timers to about once a minute while telemetry
 *  keeps it rendering, and timeline observer callbacks are not timer tasks. */
export function startReactMeasureSweep(
  perf: MeasureTimeline | undefined = globalThis.performance,
  everyMs = REACT_MEASURE_SWEEP_MS,
  Observer: typeof PerformanceObserver | undefined = globalThis.PerformanceObserver
): () => void {
  if (!perf) return () => {}
  let last = -Infinity
  const sweepIfDue = (): void => {
    const now = Date.now()
    if (now - last < everyMs) return
    last = now
    sweepReactMeasures(perf)
  }
  const timer = setInterval(sweepIfDue, everyMs)
  let observer: PerformanceObserver | null = null
  try {
    observer = Observer ? new Observer(sweepIfDue) : null
    observer?.observe({ type: 'measure' })
  } catch {
    observer = null // no timeline observer: the timer alone still sweeps
  }
  return () => {
    clearInterval(timer)
    observer?.disconnect()
  }
}
