import { expect, it, vi } from 'vitest'
import { api } from './client'
import { decidePartLink, proposePartLinks } from './partSuggestions'
vi.mock('./client', () => ({ api: { request: vi.fn() } }))
const row = {
  id: 's',
  candidate_robot_id: 'r',
  subject_kind: 'part',
  subject_ref: 'part',
  status: 'pending',
  confidence: 0.9,
  reason: 'Confirmed identity'
}
it('validates and returns bounded part suggestions', async () => {
  vi.mocked(api.request).mockResolvedValue([row])
  await expect(proposePartLinks('p', 'part')).resolves.toEqual([
    { id: 's', robotId: 'r', confidence: 0.9, reason: 'Confirmed identity' }
  ])
  expect(api.request).toHaveBeenLastCalledWith('/projects/p/hardware/parts/part/suggestions', {
    method: 'POST'
  })
})
it.each([
  { ...row, confidence: NaN },
  { ...row, reason: {} },
  { ...row, subject_ref: 'other' },
  { ...row, subject_kind: 'device' },
  { ...row, status: 'accepted' }
])('rejects malformed or wrong-subject suggestions', async (value) => {
  vi.mocked(api.request).mockResolvedValue([value])
  await expect(proposePartLinks('p', 'part')).rejects.toThrow()
})
it('does not treat an unbound acceptance response as a completed attachment', async () => {
  vi.mocked(api.request).mockResolvedValue({ id: 's', status: 'accepted', bound: false })
  await expect(decidePartLink('p', 's', true)).rejects.toThrow()
  vi.mocked(api.request).mockResolvedValue({ id: 's', status: 'accepted', bound: true })
  await expect(decidePartLink('p', 's', true)).resolves.toBeUndefined()
})
