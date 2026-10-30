// SOLUSDEV-320 P2-T1 — search client against docs/api/search.md §3.
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import { searchProject } from './search'

function client(): ApiClient {
  return {
    request: vi.fn().mockResolvedValue({ entities: [], solus: [], truncated: false }),
    requestPage: vi.fn()
  }
}

describe('searchProject', () => {
  it('sends only q when no options are given', async () => {
    const api = client()
    await searchProject('p1', 'cam', undefined, api)
    expect(api.request).toHaveBeenCalledWith('/projects/p1/search?q=cam', undefined)
  })

  it('serialises scope, comma lists and limit, omitting empty ones', async () => {
    const api = client()
    await searchProject(
      'p1',
      'ov 9281',
      { scope: 'entities', kinds: ['part', 'ic'], domains: [], sections: ['identity'], limit: 8 },
      api
    )
    expect(api.request).toHaveBeenCalledWith(
      '/projects/p1/search?q=ov+9281&scope=entities&kinds=part%2Cic&sections=identity&limit=8',
      undefined
    )
  })

  it('passes an abort signal through to the client', async () => {
    const api = client()
    const { signal } = new AbortController()
    await searchProject('p1', 'cam', { signal }, api)
    expect(api.request).toHaveBeenCalledWith('/projects/p1/search?q=cam', { signal })
  })

  it('returns the unwrapped response', async () => {
    const api = client()
    const body = { entities: [{ id: 'e1' }], solus: [], truncated: true }
    vi.mocked(api.request).mockResolvedValue(body)
    expect(await searchProject('p1', 'cam', {}, api)).toBe(body)
  })
})
