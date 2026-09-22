import { expect, it, vi } from 'vitest'
import { api } from './client'
import { listDocumentTree } from './resources.documentTree'

it.each([{}, { items: [null], next_offset: null }, { items: [], next_offset: 0 }])(
  'rejects malformed pages and non-advancing cursors',
  async (value) => {
    const client = { ...api, request: vi.fn().mockResolvedValue(value) }
    await expect(listDocumentTree('c1', { node: 'root', offset: 0 }, client)).rejects.toThrow(
      'Invalid document listing'
    )
  }
)
it('encodes the connection and query and unwraps a valid page', async () => {
  const page = {
    items: [{ id: 'd1', name: 'Arm', kind: 'document', node: null }],
    next_offset: null
  }
  const client = { ...api, request: vi.fn().mockResolvedValue(page) }
  await expect(
    listDocumentTree('c/1', { node: 'folder:f1', cacheOnly: true }, client)
  ).resolves.toEqual(page)
  expect(client.request).toHaveBeenCalledWith(
    '/users/me/connections/c%2F1/document-tree?node=folder%3Af1&cache_only=true'
  )
})
