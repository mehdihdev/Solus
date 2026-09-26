import { expect, it, vi } from 'vitest'
import { api } from '../../../lib/api/client'
import { createUnassignedPart } from './createUnassignedPart'
vi.mock('../../../lib/api/client', () => ({ api: { request: vi.fn() } }))
it('creates only a named classified part with a stable operation identity', async () => {
  vi.mocked(api.request).mockResolvedValue({ entity: { id: 'part' } })
  expect(await createUnassignedPart('project', 'Sensor', 'sensors', 'operation')).toEqual({
    id: 'part'
  })
  expect(api.request).toHaveBeenCalledWith('/projects/project/hardware/entities', {
    method: 'POST',
    idempotencyKey: 'operation',
    body: { kind: 'part', name: 'Sensor', category: 'sensors' }
  })
})
