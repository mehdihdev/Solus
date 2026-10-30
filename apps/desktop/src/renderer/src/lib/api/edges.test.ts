// SOLUSDEV-320 P4-T2 — candidate edge client against docs/api/relations.md §3.
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import { confirmEdge, declineEdge, listEdgeCandidates } from './edges'

function client(): ApiClient {
  return { request: vi.fn(), requestPage: vi.fn() }
}

describe('edge candidates client', () => {
  it('lists candidates with only the filters given', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue([{ id: 'r1' }])
    expect(await listEdgeCandidates('p1', {}, api)).toEqual([{ id: 'r1' }])
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/edges/candidates')
    await listEdgeCandidates('p1', { relation_type: 'wires', subject: 'e1' }, api)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/edges/candidates?relation_type=wires&subject=e1'
    )
  })

  it('confirms and declines through POST with the optional reason', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue({ id: 'r1', origin: 'manual', confidence: 1 })
    expect(await confirmEdge('p1', 'r1', api)).toMatchObject({ origin: 'manual' })
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/edges/r1/confirm', {
      method: 'POST'
    })
    await declineEdge('p1', 'r1', 'wrong pin', api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/edges/r1/decline', {
      method: 'POST',
      body: { reason: 'wrong pin' }
    })
    await declineEdge('p1', 'r1', undefined, api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/edges/r1/decline', {
      method: 'POST',
      body: {}
    })
  })
})
