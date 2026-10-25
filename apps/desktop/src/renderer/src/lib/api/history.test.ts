// SOLUSDEV-320 P5-T3d — history client (docs/api/solus.md §9).
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import { listHistory } from './history'

function client(): ApiClient {
  return { request: vi.fn(), requestPage: vi.fn() }
}

describe('listHistory', () => {
  it('requests one page with only the filters that are set', async () => {
    const api = client()
    const page = { data: [{ id: 'a1' }], meta: { next_cursor: 'c2' } }
    vi.mocked(api.requestPage).mockResolvedValue(page)
    expect(
      await listHistory('p1', { since: '2026-10-01', entity: 'e1', limit: 50, cursor: 'c1' }, api)
    ).toBe(page)
    expect(api.requestPage).toHaveBeenCalledWith(
      '/projects/p1/history?since=2026-10-01&entity=e1&cursor=c1&limit=50'
    )
  })

  it('omits the query string when there are no filters', async () => {
    const api = client()
    vi.mocked(api.requestPage).mockResolvedValue({ data: [], meta: {} })
    await listHistory('p1', {}, api)
    expect(api.requestPage).toHaveBeenCalledWith('/projects/p1/history')
  })
})
