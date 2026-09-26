// LB-05: pure telemetry helpers — stream state, gap-aware chart segments.
import { describe, expect, it } from 'vitest'
import { chartSegments, currentSeries, latestOf, streamState } from './telemetry'

describe('streamState', () => {
  const now = Date.parse('2026-01-01T00:00:10Z')

  it('is live within 3s, stale within 15s, no-stream beyond', () => {
    expect(streamState('2026-01-01T00:00:09Z', now)).toBe('live')
    expect(streamState('2026-01-01T00:00:00Z', now)).toBe('stale')
    expect(streamState('2025-12-31T23:59:00Z', now)).toBe('no-stream')
    expect(streamState(null, now)).toBe('no-stream')
  })
})

describe('latestOf', () => {
  it('finds the newest sample across series and is null for silence', () => {
    expect(latestOf([])).toBeNull()
    const series = [
      { signal: 'a', points: [{ timestamp: '2026-01-01T00:00:01Z', value: 1 }] },
      { signal: 'b', points: [{ timestamp: '2026-01-01T00:00:05Z', value: 2 }] }
    ]
    expect(latestOf(series)).toBe('2026-01-01T00:00:05Z')
  })
})

describe('chartSegments', () => {
  const at = (sec: number, value: number): { timestamp: string; value: number } => ({
    timestamp: new Date(Date.parse('2026-01-01T00:00:00Z') + sec * 1000).toISOString(),
    value
  })

  it('produces one segment for a steady stream', () => {
    expect(chartSegments([at(0, 1), at(1, 2), at(2, 3)], 240, 48)).toHaveLength(1)
  })

  it('breaks the line across a stream gap', () => {
    const segments = chartSegments([at(0, 1), at(1, 2), at(2, 3), at(30, 4), at(31, 5)], 240, 48)
    expect(segments).toHaveLength(2)
  })

  it('handles short series without crashing', () => {
    expect(chartSegments([], 240, 48)).toEqual([])
    expect(chartSegments([at(0, 1)], 240, 48)).toEqual([])
  })
})

describe('currentSeries', () => {
  it('uses the inclusive eight-second window and excludes future/invalid points when current data exists', () => {
    const now = Date.parse('2026-09-16T00:00:10Z')
    const points = [0, 7999, 8000, 8001, -1].map((age) => ({
      timestamp: new Date(now - age).toISOString(),
      value: age
    }))
    points.push({ timestamp: 'invalid', value: 0 })
    const original = [{ signal: 'position', key: 'device-key', points }]
    const filtered = currentSeries(original, now)
    expect(filtered[0].points.map((p) => p.value)).toEqual([0, 7999, 8000])
    expect(filtered[0].key).toBe('device-key')
    expect(original[0].points).toHaveLength(6)
  })
  it('preserves an expired feed and the empty state', () => {
    const series = [{ signal: 'old', points: [{ timestamp: '2026-01-01T00:00:00Z', value: 1 }] }]
    expect(currentSeries(series, Date.parse('2026-09-16T00:00:10Z'))).toEqual(series)
    expect(currentSeries([], Date.now())).toEqual([])
  })
})

it('never calls a future or malformed timestamp live', () => {
  const now = Date.parse('2026-09-16T00:00:10Z')
  expect(streamState(new Date(now + 1).toISOString(), now)).toBe('no-stream')
  expect(streamState('invalid', now)).toBe('no-stream')
})

it('drops invalid and future-only feeds while retaining valid past stale samples', () => {
  const now = Date.parse('2026-09-16T00:00:10Z')
  const invalid = { timestamp: 'invalid', value: 1 }
  const future = { timestamp: new Date(now + 1).toISOString(), value: 2 }
  const stale = { timestamp: new Date(now - 10_000).toISOString(), value: 3 }
  expect(currentSeries([{ signal: 'bad', points: [invalid, future] }], now)).toEqual([])
  expect(currentSeries([{ signal: 'mixed', points: [invalid, stale, future] }], now)).toEqual([
    { signal: 'mixed', points: [stale] }
  ])
})
