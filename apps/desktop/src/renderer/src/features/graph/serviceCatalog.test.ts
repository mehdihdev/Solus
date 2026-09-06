import { beforeEach, expect, it, vi } from 'vitest'
import { ServiceCatalog } from './serviceCatalog'
import { ApiError } from '../../lib/api/envelope.types'
import { listConnections, listConnectionDocuments } from '../../lib/api/resources'
import { api } from '../../lib/api/client'
vi.mock('../../lib/api/resources', () => ({
  listConnections: vi.fn(),
  listConnectionDocuments: vi.fn()
}))
beforeEach(() => vi.clearAllMocks())
it('retains both accounts and document results through repeated opens', async () => {
  vi.mocked(listConnections).mockResolvedValue([])
  vi.mocked(listConnectionDocuments).mockResolvedValue({
    items: [{ id: 'd1', name: 'Arm' }],
    cached: true,
    fetched_at: 't'
  })
  const catalog = new ServiceCatalog(api)
  await catalog.loadAccounts()
  await catalog.loadDocuments('c1')
  await catalog.loadAccounts()
  await catalog.loadDocuments('c1')
  expect(listConnections).toHaveBeenCalledTimes(1)
  expect(listConnectionDocuments).toHaveBeenCalledTimes(1)
  expect(listConnectionDocuments).toHaveBeenCalledWith('c1', { cacheOnly: true }, api)
  expect(catalog.snapshot().documents.c1.items[0].name).toBe('Arm')
})
it('retains cache misses until an explicit refresh spends the listing call', async () => {
  vi.mocked(listConnectionDocuments).mockRejectedValueOnce(
    new ApiError(409, 'listing_not_cached', 'Load first')
  )
  const catalog = new ServiceCatalog(api)
  await catalog.loadDocuments('c1')
  await catalog.loadDocuments('c1')
  expect(listConnectionDocuments).toHaveBeenCalledTimes(1)
  expect(catalog.snapshot().documents.c1.status).toBe('missing')
  vi.mocked(listConnectionDocuments).mockResolvedValue({
    items: [],
    cached: false,
    fetched_at: 'now'
  })
  await catalog.loadDocuments('c1', true)
  expect(listConnectionDocuments).toHaveBeenLastCalledWith('c1', { refresh: true }, api)
  expect(catalog.snapshot().documents.c1.status).toBe('ready')
})
it('coalesces simultaneous opens and rejects publication after disposal', async () => {
  let finish!: (value: Awaited<ReturnType<typeof listConnectionDocuments>>) => void
  vi.mocked(listConnectionDocuments).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve
    })
  )
  const catalog = new ServiceCatalog(api)
  const first = catalog.loadDocuments('c1')
  const second = catalog.loadDocuments('c1')
  catalog.dispose()
  finish({ items: [{ id: 'private', name: 'Old account' }], cached: true, fetched_at: 't' })
  await Promise.all([first, second])
  expect(listConnectionDocuments).toHaveBeenCalledTimes(1)
  expect(catalog.snapshot().documents).toEqual({})
})
it('keeps ordinary listing failures visible without retrying on reopen', async () => {
  vi.mocked(listConnectionDocuments).mockRejectedValue(new Error('Unavailable'))
  const catalog = new ServiceCatalog(api)
  await catalog.loadDocuments('c1')
  await catalog.loadDocuments('c1')
  expect(catalog.snapshot().documents.c1).toMatchObject({ status: 'error', error: 'Unavailable' })
  expect(listConnectionDocuments).toHaveBeenCalledTimes(1)
})
