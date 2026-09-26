import { describe, expect, it } from 'vitest'
import { anomalyMarkers, decodeAnomalies } from './signalAnomalies'
const at = '2026-09-14T12:00:01Z'
const event = { kind: 'threshold_breach', device_id: 'd', signal: 'angle', at, value: 2 }
const points = [0, 1, 2].map((n) => ({
  timestamp: `2026-09-14T12:00:0${n}Z`,
  value: n,
  unit: 'rad'
}))
describe('evidence markers', () => {
  it('matches exact device and signal, clips timestamps, and deduplicates', () => {
    const events = decodeAnomalies([
      event,
      event,
      { ...event, device_id: 'other' },
      { ...event, signal: 'other' },
      { ...event, at: '2026-09-14T11:59:00Z' }
    ])
    expect(anomalyMarkers(events, 'd', 'angle', points)).toEqual([
      { kind: 'threshold_breach', at, x: 120 }
    ])
  })
  it('preserves time through unit conversions and gaps without inventing a value', () => {
    const events = decodeAnomalies([{ ...event, kind: 'stream_gap', value: null }])
    expect(
      anomalyMarkers(
        events,
        'd',
        'angle',
        points.map((p) => ({ ...p, value: (p.value * 180) / Math.PI, unit: 'deg' }))
      )[0].x
    ).toBe(120)
  })
  it('rejects malformed, oversized and non-finite responses', () => {
    for (const value of [
      {},
      Array(101).fill(event),
      [{ ...event, at: 'bad' }],
      [{ ...event, value: Infinity }],
      [{ ...event, kind: 'guess' }]
    ])
      expect(() => decodeAnomalies(value)).toThrow()
    expect(anomalyMarkers([event], 'd', 'angle', [])).toEqual([])
  })
})
