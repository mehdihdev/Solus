import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  startReactMeasureSweep,
  sweepReactMeasures,
  type MeasureTimeline
} from './reactMeasureSweep'

const entry = (name: string, detail?: unknown): PerformanceEntry =>
  ({ name, entryType: 'measure', detail }) as unknown as PerformanceEntry

function timeline(entries: PerformanceEntry[]): MeasureTimeline & { cleared: string[] } {
  const cleared: string[] = []
  return {
    cleared,
    getEntriesByType: () => entries,
    clearMeasures: (name?: string) => void cleared.push(name ?? '*')
  }
}

describe('React development measure sweep', () => {
  afterEach(() => vi.useRealTimers())

  it("clears React's component and scheduler measures once per distinct name", () => {
    const perf = timeline([
      entry('​SignalWidget', { devtools: { track: 'Components ⚛' } }),
      entry('​SignalWidget', { devtools: { track: 'Components ⚛' } }),
      entry('Render', { devtools: { track: 'Blocking', trackGroup: 'Scheduler ⚛' } }),
      entry('​SceneViewer')
    ])
    expect(sweepReactMeasures(perf)).toBe(3)
    expect(perf.cleared.sort()).toEqual(['Render', '​SceneViewer', '​SignalWidget'].sort())
  })

  it("never clears the app's own perf measures", () => {
    const perf = timeline([entry('hw:confirm_to_node:r1'), entry('hw:first_card', null)])
    expect(sweepReactMeasures(perf)).toBe(0)
    expect(perf.cleared).toEqual([])
  })

  it('sweeps on an interval until stopped', () => {
    vi.useFakeTimers()
    const perf = timeline([entry('​Button')])
    const stop = startReactMeasureSweep(perf, 1000)
    vi.advanceTimersByTime(3000)
    expect(perf.cleared).toHaveLength(3)
    stop()
    vi.advanceTimersByTime(3000)
    expect(perf.cleared).toHaveLength(3)
  })

  it('also sweeps from the timeline itself, since a covered window throttles its timers', () => {
    vi.useFakeTimers()
    const perf = timeline([entry('\u200bButton')])
    let deliver: (() => void) | null = null
    const observe = vi.fn()
    const disconnect = vi.fn()
    class Observer {
      constructor(callback: () => void) {
        deliver = callback
      }
      observe = observe
      disconnect = disconnect
    }
    const stop = startReactMeasureSweep(perf, 60_000, Observer as unknown as typeof PerformanceObserver)
    expect(observe).toHaveBeenCalledWith({ type: 'measure' })
    deliver!()
    expect(perf.cleared).toHaveLength(1)
    deliver!()
    expect(perf.cleared).toHaveLength(1) // at most one sweep per interval
    vi.advanceTimersByTime(60_000)
    deliver!()
    expect(perf.cleared.length).toBeGreaterThanOrEqual(2)
    stop()
    expect(disconnect).toHaveBeenCalled()
  })

  it('is a no-op without a Performance API', () => {
    expect(sweepReactMeasures(undefined)).toBe(0)
    expect(startReactMeasureSweep(undefined)).toBeTypeOf('function')
  })
})
