import { expect, it, vi } from 'vitest'
import { api } from '../../lib/api/client'
import { focusedTelemetry } from './focusedTelemetry'
vi.mock('../../lib/api/client', () => ({ api: { request: vi.fn() } }))
it('batches discovery without dropping a focused device beyond sixteen IDs', async () => {
  const ids = Array.from({ length: 18 }, (_, i) => `device-${i}`)
  vi.mocked(api.request).mockImplementation(async (path) => {
    if (path.includes('/telemetry-devices')) return { device_ids: ids }
    if (path.includes('/events')) return []
    const params = new URLSearchParams(path.split('?')[1])
    expect(params.getAll('device_id').length).toBeLessThanOrEqual(16)
    expect(params.get('focus_entity_id')).toBe('robot')
    return {
      devices: params.getAll('device_id').includes('device-17')
        ? [
            {
              device_id: 'device-17',
              resolved_entity_id: 'brain',
              signals: [{ signal: 'position', points: [] }]
            }
          ]
        : []
    }
  })
  const result = await focusedTelemetry('project', 'robot', new AbortController().signal)
  expect(result.recent.signals).toHaveLength(1)
  expect(result.recent.signals[0].signal).toBe('device-17 · position')
})
