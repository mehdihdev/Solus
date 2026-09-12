import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import {
  getSourceView,
  listSourceRevisions,
  resetSourceView,
  selectSourceView
} from './resources.revisions'

describe('revision HTTP transport', () => {
  it('unwraps standard API envelopes for discovery and all view operations', async () => {
    const menu = {
      supported: true,
      kind: 'git_branch',
      items: [{ name: 'vlfh_tsfm', commit: 'a'.repeat(40) }],
      next_page: null
    }
    const view = {
      base_source_id: 's',
      source_id: 's',
      status: 'default',
      branch: null,
      commit: null,
      error: null
    }
    const fetchImpl = vi.fn(
      async (url: string | URL | Request) =>
        new Response(JSON.stringify({ data: String(url).includes('/revisions?') ? menu : view }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
    )
    const client = createApiClient({ baseUrl: 'http://localhost/api/v1', fetchImpl })
    expect(await listSourceRevisions('p', 's', 1, client)).toEqual(menu)
    expect(await getSourceView('p', 's', client)).toEqual(view)
    expect(await selectSourceView('p', 's', 'vlfh_tsfm', client)).toEqual(view)
    expect(await resetSourceView('p', 's', client)).toEqual(view)
    expect(fetchImpl).toHaveBeenCalledTimes(4)
  })
})
