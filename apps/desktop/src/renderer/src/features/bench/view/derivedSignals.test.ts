import { describe, expect, it } from 'vitest'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { DerivedSignalStream, previewDerivedSignal, type DerivedDefinition } from './derivedSignals'

const T0 = Date.parse('2026-10-31T12:00:00.000Z')
const iso = (seconds: number): string => new Date(T0 + seconds * 1000).toISOString()

function device(id: string, signals: Record<string, [number, number][]>): BenchDeviceRecent {
  return {
    device_id: id,
    resolved_entity_id: null,
    signals: Object.entries(signals).map(([signal, points]) => ({
      signal,
      points: points.map(([t, value]) => ({ timestamp: iso(t), value }))
    }))
  }
}

const devices = (...list: BenchDeviceRecent[]): Record<string, BenchDeviceRecent> =>
  Object.fromEntries(list.map((d) => [d.device_id, d]))

const def = (expression: string, id = 'd1'): DerivedDefinition => ({
  id,
  name: 'Lift error',
  expression,
  unit: 'deg'
})

const values = (points: readonly { value: number }[]): number[] => points.map((p) => p.value)

describe('DerivedSignalStream', () => {
  it('evaluates over retained device series and keeps identity fields', () => {
    const stream = new DerivedSignalStream()
    const [series] = stream.update(
      [def('sig("usb:5A7A/3", "goal") - sig("usb:5A7A/3", "pos")')],
      devices(
        device('usb:5A7A/3', {
          goal: [
            [0, 10],
            [0.5, 12]
          ],
          pos: [
            [0, 4],
            [0.5, 5]
          ]
        })
      )
    )
    expect(series).toMatchObject({ id: 'd1', name: 'Lift error', unit: 'deg', error: null })
    expect(series.points).toEqual([
      { timestamp: iso(0), value: 6 },
      { timestamp: iso(0.5), value: 7 }
    ])
  })

  it('streams: overlapping polls add only new samples and filter state carries over', () => {
    const stream = new DerivedSignalStream()
    const definitions = [def('deriv(sig("arm", "x"))')]
    stream.update(
      definitions,
      devices(
        device('arm', {
          x: [
            [0, 0],
            [0.5, 1]
          ]
        })
      )
    )
    const [series] = stream.update(
      definitions,
      devices(
        device('arm', {
          x: [
            [0.5, 1],
            [1, 3]
          ]
        })
      )
    )
    expect(values(series.points)).toEqual([Number.NaN, 2, 4])
  })

  it('waits for a lagging secondary, then releases after the 1 s hold horizon', () => {
    const stream = new DerivedSignalStream()
    const definitions = [def('sig("a", "p") + sig("b", "s")')]
    let [series] = stream.update(
      definitions,
      devices(
        device('a', {
          p: [
            [0, 1],
            [0.5, 1],
            [1, 1]
          ]
        }),
        device('b', { s: [[0, 10]] })
      )
    )
    expect(values(series.points)).toEqual([11])
    ;[series] = stream.update(
      definitions,
      devices(
        device('a', {
          p: [
            [1, 1],
            [2.5, 1]
          ]
        }),
        device('b', { s: [[0.5, 20]] })
      )
    )
    // b's newest is 0.5; primary newest 2.5 minus hold 1.0 = 1.5 releases t <= 1.5.
    expect(values(series.points)).toEqual([11, 21, 21])
  })

  it('reports a parse error without evaluating and recovers when the expression changes', () => {
    const stream = new DerivedSignalStream()
    const data = devices(device('arm', { x: [[0, 2]] }))
    const [bad] = stream.update([def('foo(sig("arm","x"))')], data)
    expect(bad.error?.code).toBe('unknown_function')
    expect(bad.points).toEqual([])
    const [good] = stream.update([def('sig("arm","x") * 3')], data)
    expect(good.error).toBeNull()
    expect(values(good.points)).toEqual([6])
  })

  it('resets state when an expression is edited and drops removed definitions', () => {
    const stream = new DerivedSignalStream()
    const data = devices(device('arm', { x: [[0, 2]] }))
    stream.update([def('sig("arm","x")'), def('sig("arm","x") + 1', 'd2')], data)
    const result = stream.update([def('sig("arm","x") * 10')], data)
    expect(result).toHaveLength(1)
    expect(values(result[0].points)).toEqual([20])
    expect(stream.size()).toBe(1)
  })

  it('bounds the output history', () => {
    const stream = new DerivedSignalStream(5)
    const points: [number, number][] = Array.from({ length: 20 }, (_, i) => [i * 0.1, i])
    const [series] = stream.update([def('sig("arm","x")')], devices(device('arm', { x: points })))
    expect(values(series.points)).toEqual([15, 16, 17, 18, 19])
  })

  it('treats injection-looking ids as plain keys and missing devices as no data', () => {
    const stream = new DerivedSignalStream()
    const [series] = stream.update(
      [def('sig("__proto__", "constructor") + 1'), def('sig("ghost", "x")', 'd2')],
      devices(device('__proto__', { constructor: [[0, 1]] as [number, number][] }))
    )
    expect(values(series.points)).toEqual([2])
    expect(stream.update([def('sig("ghost", "x")', 'd2')], {})[0].points).toEqual([])
  })

  it('skips unparseable timestamps', () => {
    const stream = new DerivedSignalStream()
    const data = devices({
      device_id: 'arm',
      resolved_entity_id: null,
      signals: [
        {
          signal: 'x',
          points: [
            { timestamp: 'not-a-date', value: 9 },
            { timestamp: iso(0), value: 1 }
          ]
        }
      ]
    })
    expect(values(stream.update([def('sig("arm","x")')], data)[0].points)).toEqual([1])
  })
})

describe('previewDerivedSignal', () => {
  it('evaluates a draft expression over the retained data', () => {
    const data = devices(
      device('arm', {
        x: [
          [0, 1],
          [1, 3]
        ]
      })
    )
    const preview = previewDerivedSignal('ma(sig("arm","x"), 5)', data)
    expect(preview.error).toBeNull()
    expect(values(preview.points)).toEqual([1, 2])
  })

  it('returns the parse error for a bad draft', () => {
    const preview = previewDerivedSignal('sig("arm","x") +', {})
    expect(preview.error?.code).toBe('syntax')
    expect(preview.points).toEqual([])
  })
})
