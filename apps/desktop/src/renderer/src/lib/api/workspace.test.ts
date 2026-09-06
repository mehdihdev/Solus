import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import { ApiError } from './envelope.types'
import { getWorkspaceLayout, listAllRelations, saveWorkspaceLayout } from './workspace'

function client(): ApiClient {
  return { request: vi.fn(), requestPage: vi.fn() }
}

describe('workspace navigation reads and positions', () => {
  it('walks relation pages so containment is complete beyond 500 edges', async () => {
    const api = client()
    vi.mocked(api.requestPage)
      .mockResolvedValueOnce({
        data: [{ id: 'r1' }],
        meta: { has_next: true, next_cursor: 'next/+=' }
      })
      .mockResolvedValueOnce({ data: [{ id: 'r2' }], meta: { has_next: false } })
    expect(await listAllRelations('p1', api)).toEqual([{ id: 'r1' }, { id: 'r2' }])
    expect(api.requestPage).toHaveBeenNthCalledWith(1, '/projects/p1/relations?limit=500')
    expect(api.requestPage).toHaveBeenNthCalledWith(
      2,
      '/projects/p1/relations?limit=500&cursor=next%2F%2B%3D'
    )
    expect(api.request).not.toHaveBeenCalled()
  })

  it('refuses a repeated pagination cursor instead of looping forever', async () => {
    const api = client()
    vi.mocked(api.requestPage).mockResolvedValue({
      data: [],
      meta: { has_next: true, next_cursor: 'same' }
    })
    await expect(listAllRelations('p1', api)).rejects.toThrow(/cursor/i)
    expect(api.requestPage).toHaveBeenCalledTimes(2)
  })

  it('reads and writes only the project layout with its version', async () => {
    const api = client()
    const layout = { version: 2, positions: { e1: { x: 0, y: 15 } } }
    vi.mocked(api.request).mockResolvedValue(layout)
    expect(await getWorkspaceLayout('p1', api)).toEqual(layout)
    expect(await saveWorkspaceLayout('p1', layout, api)).toEqual(layout)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/workspace-layout', {
      method: 'PUT',
      body: layout
    })
  })

  it('preserves layout version conflicts for the UI to resolve', async () => {
    const api = client()
    vi.mocked(api.request).mockRejectedValue(new ApiError(409, 'conflict', 'Layout changed'))
    await expect(
      saveWorkspaceLayout('p1', { version: 0, positions: {} }, api)
    ).rejects.toMatchObject({ status: 409, code: 'conflict' })
  })
})
