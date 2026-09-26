import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './client'
import { acceptWiring, proposeWiring } from './presenceWiring'
vi.mock('./client', () => ({ api: { request: vi.fn() } }))
const id = '00000000-0000-0000-0000-000000000001'
const input = {
  profile_id: 'uno_avr',
  mode: 'typed',
  wiring: [{ channel: 'light', pin: 'A0', kind: 'analog_input' }]
} as const
const proposal = {
  proposal_id: id,
  digest: 'a'.repeat(64),
  ...input,
  status: 'proposed',
  observations: [{ detail: 'Declared pin only', confidence: null }],
  unresolved: ['I2C identity unknown']
}
beforeEach(() => vi.mocked(api.request).mockReset())
it('validates proposal then accepts only its exact digest', async () => {
  vi.mocked(api.request)
    .mockResolvedValueOnce(proposal)
    .mockResolvedValueOnce({ proposal_id: id, digest: proposal.digest, status: 'accepted' })
  expect(await proposeWiring('p', 'r', 'b', input)).toEqual(proposal)
  await expect(acceptWiring('p', 'r', 'b', proposal)).resolves.toEqual({
    proposal_id: id,
    digest: proposal.digest,
    status: 'accepted'
  })
  expect(api.request).toHaveBeenLastCalledWith(
    `/projects/p/hardware/robots/r/brains/b/presence/wiring/${id}/accept`,
    { method: 'POST', body: { digest: proposal.digest } }
  )
})
it.each([
  { ...proposal, digest: 'x' },
  { ...proposal, profile_id: 'nano_avr' },
  { ...proposal, mode: 'probe' },
  { ...proposal, wiring: [{ channel: 'x', pin: 'A0', kind: 'servo' }] },
  { ...proposal, observations: [{ detail: 'x', confidence: 2 }] },
  { ...proposal, unresolved: Array(257).fill('x') }
])('rejects malformed or mismatched evidence', async (value) => {
  vi.mocked(api.request).mockResolvedValue(value)
  await expect(proposeWiring('p', 'r', 'b', input)).rejects.toThrow()
})
it('rejects mismatched acceptance', async () => {
  vi.mocked(api.request).mockResolvedValue({
    proposal_id: id,
    digest: 'b'.repeat(64),
    status: 'accepted'
  })
  await expect(acceptWiring('p', 'r', 'b', proposal)).rejects.toThrow()
})
it('accepts a 64-character channel and rejects a 65-character response channel', async () => {
  const valid = { ...proposal, wiring: [{ ...input.wiring[0], channel: 'a'.repeat(64) }] }
  vi.mocked(api.request)
    .mockResolvedValueOnce(valid)
    .mockResolvedValueOnce({ ...valid, wiring: [{ ...input.wiring[0], channel: 'a'.repeat(65) }] })
  await expect(proposeWiring('p', 'r', 'b', input)).resolves.toEqual(valid)
  await expect(proposeWiring('p', 'r', 'b', input)).rejects.toThrow()
})
