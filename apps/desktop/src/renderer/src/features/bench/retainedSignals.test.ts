import { expect, it } from 'vitest'
import { retainedDevices } from './retainedSignals'
import type { BenchDeviceRecent } from '../../lib/api/resources'
it('retains one missing joint while other joints update and bounds name churn', () => {
  const now = Date.now()
  const device: BenchDeviceRecent = {
    device_id: 'arm',
    resolved_entity_id: 'robot',
    signals: [{ signal: 'missing', points: [{ timestamp: new Date(now).toISOString(), value: 1 }] }]
  }
  let previous = retainedDevices([device], {}, now)
  for (let i = 0; i < 300; i++) {
    previous = retainedDevices(
      [
        {
          ...device,
          signals: [
            {
              signal: `new-${i}`,
              points: [{ timestamp: new Date(now + i).toISOString(), value: i }]
            }
          ]
        }
      ],
      previous,
      now + i
    )
  }
  expect(previous.arm.signals).toHaveLength(256)
  expect(previous.arm.signals[0].signal).toBe('missing')
  expect(retainedDevices([], previous, now)).toEqual({})
})
it('does not resurrect old calibration names on initial admission', () => {
  const now = Date.now()
  const result = retainedDevices(
    [
      {
        device_id: 'arm',
        resolved_entity_id: 'robot',
        signals: [
          {
            signal: 'old',
            points: [{ timestamp: new Date(now - 600_000).toISOString(), value: 1 }]
          },
          { signal: 'current', points: [{ timestamp: new Date(now).toISOString(), value: 2 }] }
        ]
      }
    ],
    {},
    now
  )
  expect(result.arm.signals.map((s) => s.signal)).toEqual(['current'])
})
