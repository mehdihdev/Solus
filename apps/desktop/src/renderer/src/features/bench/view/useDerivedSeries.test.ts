import { renderHook } from '@testing-library/react'
import { expect, it } from 'vitest'
import type { BenchViewDerived } from '@solus/shared-types'
import type { BenchDeviceRecent } from '../../../lib/api/resources'
import { useDerivedSeries } from './useDerivedSeries'

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
