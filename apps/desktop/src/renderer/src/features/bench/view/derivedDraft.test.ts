import { describe, expect, it } from 'vitest'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import {
  derivedCardSeries,
  insertAt,
  missingRefs,
  referenceText,
  splitAtError,
  streamingSignals
} from './derivedDraft'

const device = (device_id: string, signals: string[]): BenchDeviceRecent => ({
  device_id,
  resolved_entity_id: null,
  signals: signals.map((signal) => ({
    signal,
    points: [{ timestamp: '2026-10-31T00:00:00Z', value: 1 }]
  }))
})

describe('splitAtError', () => {
  it('marks the span by code point', () => {
    expect(splitAtError('1 + nope(1)', { position: 4, length: 4, message: '' })).toEqual({
      before: '1 + ',
      marked: 'nope',
      after: '(1)'
    })
  })
  it('marks a visible cell for an error at the end', () => {
    expect(splitAtError('1 +', { position: 3, length: 0, message: '' }).marked).toBe(' ')
  })
})

describe('streamingSignals', () => {
  it('lists referenceable signals sorted, skipping quotes and backslashes', () => {
    const devices = { b: device('b', ['y', 'x']), a: device('a', ['q"uote', 'z']) }
    expect(streamingSignals(devices)).toEqual([
      { deviceId: 'a', signal: 'z' },
      { deviceId: 'b', signal: 'x' },
      { deviceId: 'b', signal: 'y' }
    ])
  })
})

describe('missingRefs and insertAt', () => {
  it('finds references with no streaming data', () => {
    const devices = { a: device('a', ['x']) }
    expect(
      missingRefs(
        [
          { deviceId: 'a', signal: 'x' },
          { deviceId: 'a', signal: 'y' },
          { deviceId: 'toString', signal: 'x' }
        ],
        devices
      )
    ).toEqual([
      { deviceId: 'a', signal: 'y' },
      { deviceId: 'toString', signal: 'x' }
    ])
  })
  it('inserts a quoted reference at the caret', () => {
    expect(insertAt('1 + ', 4, referenceText({ deviceId: 'a/b', signal: 'c' }))).toEqual({
      text: '1 + sig("a/b", "c")',
      caret: 19
    })
    expect(insertAt('x', null, 'y').text).toBe('xy')
  })
})

describe('derivedCardSeries', () => {
  it('puts the derived unit on every point and keeps NaN gaps', () => {
    const series = derivedCardSeries(
      {
        id: 'd',
        name: 'n',
        unit: 'deg',
        error: null,
        points: [{ timestamp: 't', value: Number.NaN }]
      },
      'n'
    )
    expect(series.signal).toBe('n')
    expect(series.points[0].unit).toBe('deg')
    expect(Number.isNaN(series.points[0].value)).toBe(true)
    expect(derivedCardSeries(undefined, 'x').points).toEqual([])
  })
})
