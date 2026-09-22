import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../lib/api/client'
import { ApiError } from '../../lib/api/envelope.types'
import { listDocumentTree } from '../../lib/api/resources.documentTree'
import { DocumentTreeCatalog } from './documentTreeCatalog'

vi.mock('../../lib/api/resources.documentTree', () => ({ listDocumentTree: vi.fn() }))
beforeEach(() => vi.clearAllMocks())
const folder = { id: 'f1', name: 'Robot', kind: 'folder' as const, node: 'folder:f1' }
const document = { id: 'd1', name: 'Arm', kind: 'document' as const, node: null }

it('keeps a root cache miss until an explicit load and reuses loaded folders', async () => {
  vi.mocked(listDocumentTree).mockRejectedValueOnce(
    new ApiError(409, 'listing_not_cached', 'Load first')
  )
  const catalog = new DocumentTreeCatalog(api)
  await catalog.load('c1')
  expect(catalog.snapshot()['c1:root'].status).toBe('missing')
  vi.mocked(listDocumentTree).mockResolvedValue({ items: [folder], next_offset: null })
  await catalog.load('c1', 'root', true)
  await catalog.load('c1', 'root')
  expect(listDocumentTree).toHaveBeenCalledTimes(2)
  expect(catalog.snapshot()['c1:root'].items).toEqual([folder])
})

it('loads additional pages, deduplicates identities, and preserves rows on errors', async () => {
  vi.mocked(listDocumentTree).mockResolvedValueOnce({ items: [folder], next_offset: 20 })
  const catalog = new DocumentTreeCatalog(api)
  await catalog.load('c1', 'root', true)
  vi.mocked(listDocumentTree).mockResolvedValueOnce({
    items: [folder, document],
    next_offset: null
  })
  await catalog.more('c1', 'root')
  expect(catalog.snapshot()['c1:root'].items).toEqual([folder, document])
  expect(listDocumentTree).toHaveBeenLastCalledWith('c1', { node: 'root', offset: 20 }, api)
  vi.mocked(listDocumentTree).mockRejectedValueOnce(new Error('Provider unavailable'))
  await catalog.load('c1', 'root', true)
  expect(catalog.snapshot()['c1:root'].items).toEqual([folder, document])
  expect(catalog.snapshot()['c1:root'].error).toBe('Provider unavailable')
})

it('coalesces calls and ignores late results after account state disposal', async () => {
  let finish!: (value: Awaited<ReturnType<typeof listDocumentTree>>) => void
  vi.mocked(listDocumentTree).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    })
  )
  const catalog = new DocumentTreeCatalog(api)
  const first = catalog.load('c1')
  const second = catalog.load('c1')
  expect(listDocumentTree).toHaveBeenCalledTimes(1)
  catalog.dispose()
  finish({ items: [folder], next_offset: null })
  await Promise.all([first, second])
  expect(catalog.snapshot()).toEqual({})
})

it('turns malformed pages into a retryable error', async () => {
  vi.mocked(listDocumentTree).mockResolvedValueOnce({
    items: undefined,
    next_offset: null
  } as never)
  const catalog = new DocumentTreeCatalog(api)
  await catalog.load('c1')
  expect(catalog.snapshot()['c1:root'].status).toBe('error')
  vi.mocked(listDocumentTree).mockResolvedValueOnce({ items: [], next_offset: null })
  await catalog.load('c1', 'root', true)
  expect(catalog.snapshot()['c1:root'].status).toBe('ready')
})
