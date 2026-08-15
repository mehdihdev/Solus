// LB-05: pure telemetry helpers — stream state, gap-aware chart segments.
import { describe, expect, it } from 'vitest'
import { chartSegments, latestOf, streamState } from './telemetry'

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
