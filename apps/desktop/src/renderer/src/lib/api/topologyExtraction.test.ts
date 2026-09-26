import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './client'
import { confirmExtraction, proposeExtraction, type ExtractionProposal } from './topologyExtraction'

vi.mock('./client', () => ({ api: { request: vi.fn() } }))
const input = { brain_id: 'b1', source_ref: 'source:r1', source_kind: 'firmware' as const }
const response = (): ExtractionProposal => ({
  robot_id: 'r1',
  brain_id: 'b1',
  source_ref: 'source:r1',
  proposal_digest: 'a'.repeat(64),
  extraction: { source_kind: 'firmware', status: 'success', rows: [], notes: [] }
})
beforeEach(() => vi.mocked(api.request).mockReset())
it('sends only opaque identifiers to the scoped proposal route', async () => {
  vi.mocked(api.request).mockResolvedValue(response())
  await proposeExtraction('p1', 'r1', input)
  expect(api.request).toHaveBeenCalledWith(
    '/projects/p1/hardware/robots/r1/topology/extraction/propose',
    { method: 'POST', body: input }
  )
})
it.each([
  { brain_id: 'foreign' },
  { proposal_digest: null },
  { extraction: { source_kind: 'firmware', status: 'success', rows: [null], notes: [] } },
  { extraction: { source_kind: 'firmware', status: 'success', rows: [], notes: [{}] } },
  {
    extraction: {
      source_kind: 'firmware',
      status: 'success',
      rows: [{ source_namespace: 'x', source_ref: 'x', provenance: [{}] }],
      notes: []
    }
  }
])('rejects malformed or mismatched evidence before rendering', async (patch) => {
  vi.mocked(api.request).mockResolvedValue({ ...response(), ...patch })
  await expect(proposeExtraction('p1', 'r1', input)).rejects.toThrow(/could not be verified/)
})

const confirmation = {
  ...input,
  proposal_digest: 'a'.repeat(64),
  operation_id: '00000000-0000-4000-8000-000000000001',
  selections: [{ row_index: 0, name: 'Elbow' }]
}
const accepted = {
  robot_id: 'r1',
  brain_id: 'b1',
  proposal_digest: 'a'.repeat(64),
  entity_ids: ['00000000-0000-4000-8000-000000000002'],
  created: 1
}
it('confirms exactly the reviewed selection', async () => {
  vi.mocked(api.request).mockResolvedValue(accepted)
  expect(await confirmExtraction('p1', 'r1', confirmation)).toEqual(accepted)
})
it.each([
  { created: -1 },
  { entity_ids: [{}] },
  { brain_id: 'foreign' },
  { proposal_digest: 'b'.repeat(64) },
  { entity_ids: [] }
])('rejects invalid acceptance %j', async (patch) => {
  vi.mocked(api.request).mockResolvedValue({ ...accepted, ...patch })
  await expect(confirmExtraction('p1', 'r1', confirmation)).rejects.toThrow()
})
