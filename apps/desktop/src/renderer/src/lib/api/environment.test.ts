// SOLUSDEV-320 P5-T3d — environment divergences client (docs/api/solus.md §2.1).
import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import { getEnvironmentDivergences } from './environment'

describe('getEnvironmentDivergences', () => {
  it('GETs the project route and returns the document as-is', async () => {
    const api: ApiClient = { request: vi.fn(), requestPage: vi.fn() }
    const doc = { schema_version: 1, computed_at: 't', spec_entry_id: null, machines: [] }
    vi.mocked(api.request).mockResolvedValue(doc)
    expect(await getEnvironmentDivergences('p1', api)).toBe(doc)
    expect(api.request).toHaveBeenCalledWith('/projects/p1/environment/divergences')
  })
})
