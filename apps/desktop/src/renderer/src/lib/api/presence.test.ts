import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './client'
import { listPresenceProfiles, preparePresence } from './presence'
vi.mock('./client', () => ({ api: { request: vi.fn() } }))
const input = { profile_id: 'uno_avr', kind: 'heartbeat', channel: 'uno.alive' } as const
const plan = {
  plan_id: '00000000-0000-0000-0000-000000000001',
  source: 'void setup() {}',
  source_sha256: 'a'.repeat(64),
  binary_sha256: 'b'.repeat(64),
  profile: 'uno_avr',
  status: 'prepared',
  target: {
    binding: 'port-1',
    path: '/dev/ttyUSB0',
    vid: 6790,
    pid: 29987,
    serial: null,
    location: '1',
    manual_confirmation_required: true
  }
}
beforeEach(() => vi.mocked(api.request).mockReset())
it('decodes explicit supported profiles and exact prepared target', async () => {
  vi.mocked(api.request)
    .mockResolvedValueOnce([{ id: 'uno_avr', label: 'Arduino Uno', available: true, reason: null }])
    .mockResolvedValueOnce(plan)
  expect(await listPresenceProfiles('p')).toHaveLength(1)
  expect(await preparePresence('p', 'r', 'b', input)).toEqual(plan)
  expect(api.request).toHaveBeenLastCalledWith(
    '/projects/p/hardware/robots/r/brains/b/presence/prepare',
    { method: 'POST', body: input }
  )
})
it.each([
  { ...plan, source: {} },
  { ...plan, source: 'a'.repeat(100001) },
  { ...plan, profile: 'nano_avr' },
  { ...plan, plan_id: 'x' },
  { ...plan, target: { ...plan.target, manual_confirmation_required: false } },
  { ...plan, target: { ...plan.target, serial: {} } }
])('rejects malformed prepared data', async (value) => {
  vi.mocked(api.request).mockResolvedValue(value)
  await expect(preparePresence('p', 'r', 'b', input)).rejects.toThrow()
})
it.each([
  [{ id: 'uno_avr', label: {}, available: true, reason: null }],
  [{ id: 'uno_avr', label: 'Uno', available: 'yes', reason: null }],
  Array(3).fill({ id: 'uno_avr', label: 'Uno', available: true, reason: null })
])('rejects malformed profiles', async (value) => {
  vi.mocked(api.request).mockResolvedValue(value)
  await expect(listPresenceProfiles('p')).rejects.toThrow()
})
it('requires accepted proposal for topology preparation and forwards its ID', async () => {
  await expect(preparePresence('p', 'r', 'b', { ...input, kind: 'topology' })).rejects.toThrow(
    /Accept wiring/
  )
  expect(api.request).not.toHaveBeenCalled()
  vi.mocked(api.request).mockResolvedValue(plan)
  await preparePresence('p', 'r', 'b', {
    ...input,
    kind: 'topology',
    wiring_proposal_id: plan.plan_id
  })
  expect(api.request).toHaveBeenLastCalledWith(expect.any(String), {
    method: 'POST',
    body: { ...input, kind: 'topology', wiring_proposal_id: plan.plan_id }
  })
})
