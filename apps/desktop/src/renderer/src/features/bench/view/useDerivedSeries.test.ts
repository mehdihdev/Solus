import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { BenchViewDerived } from '@solus/shared-types'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { CONSTANT_TICK_MS, useDerivedSeries } from './useDerivedSeries'

const derived: BenchViewDerived[] = [
  {
    id: 'd1',
    name: 'Double',
    expression: 'sig("dev", "x") * 2',
    unit: null,
    node_count: 3,
    refs: [{ device_id: 'dev', signal: 'x' }],
    created_at: '',
    updated_at: ''
  }
]
const devices = (values: number[]): Record<string, BenchDeviceRecent> => ({
  dev: {
    device_id: 'dev',
    resolved_entity_id: null,
    signals: [
      {
        signal: 'x',
        points: values.map((value, i) => ({
          timestamp: new Date(Date.UTC(2026, 9, 31, 0, 0, i)).toISOString(),
          value
        }))
      }
    ]
  }
})

it('evaluates derived signals over the live devices and keeps history across feeds', () => {
  const { result, rerender } = renderHook(({ d }) => useDerivedSeries(derived, d), {
    initialProps: { d: devices([1, 2]) }
  })
  expect(result.current[0].points.map((p) => p.value)).toEqual([2, 4])
  rerender({ d: devices([1, 2, 3]) })
  expect(result.current[0].points.map((p) => p.value)).toEqual([2, 4, 6])
})

const constant: BenchViewDerived = {
  ...derived[0],
  id: 'c1',
  name: 'mehdi_test',
  expression: '10',
  node_count: 1,
  refs: []
}

it('ticks a constant derived signal on the bench clock even without new device data', () => {
  vi.useFakeTimers()
  vi.setSystemTime(Date.UTC(2026, 9, 31, 0, 0, 0))
  try {
    const empty = {}
    const { result } = renderHook(() => useDerivedSeries([constant], empty))
    expect(result.current[0].points.map((p) => p.value)).toEqual([10])
    for (let i = 0; i < 2; i++) {
      act(() => {
        vi.advanceTimersByTime(CONSTANT_TICK_MS)
      })
    }
    expect(result.current[0].points.map((p) => p.value)).toEqual([10, 10, 10])
    expect(result.current[0].points.at(-1)?.timestamp).toBe('2026-10-31T00:00:02.000Z')
  } finally {
    vi.useRealTimers()
  }
})

it('runs no clock when every derived signal references a signal', () => {
  vi.useFakeTimers()
  try {
    renderHook(() => useDerivedSeries(derived, {}))
    expect(vi.getTimerCount()).toBe(0)
  } finally {
    vi.useRealTimers()
  }
})
