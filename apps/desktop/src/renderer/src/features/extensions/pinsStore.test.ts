// SOLUSDEV-246 / STORE ST3 — the pins store: server-backed, never persisted.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as ext from '../../lib/api/resources.extensions'
import { usePinsStore } from './pinsStore'

vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  listExtensionPins: vi.fn(),
  pinExtension: vi.fn(),
  unpinExtension: vi.fn()
}))

function pinRow(slug: string): ext.ExtensionPinApi {
  return {
    slug,
    name: slug.toUpperCase(),
    verified: true,
    publisher: { display_name: 'Solus' },
    version: '1.0.0',
    views: ['page'],
    page: { label: slug.toUpperCase(), icon: 'icon.svg' },
    pinned_at: '2026-09-06T00:00:00Z'
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  usePinsStore.getState().reset()
})

describe('usePinsStore', () => {
  it('hydrates from the server and reports offline only when it has nothing', async () => {
    vi.mocked(ext.listExtensionPins).mockRejectedValueOnce(new Error('down'))
    await usePinsStore.getState().hydrate()
    expect(usePinsStore.getState().status).toBe('offline')

    vi.mocked(ext.listExtensionPins).mockResolvedValueOnce([pinRow('bom')])
    await usePinsStore.getState().hydrate()
    expect(usePinsStore.getState().status).toBe('ready')
    expect(usePinsStore.getState().isPinned('bom')).toBe(true)

    vi.mocked(ext.listExtensionPins).mockRejectedValueOnce(new Error('blip'))
    await usePinsStore.getState().hydrate()
    expect(usePinsStore.getState().status).toBe('ready')
    expect(usePinsStore.getState().pins.map((p) => p.slug)).toEqual(['bom'])
  })

  it('pins and unpins through the server, reporting refusals as false', async () => {
    vi.mocked(ext.pinExtension).mockResolvedValueOnce(pinRow('bom'))
    expect(await usePinsStore.getState().pin('bom')).toBe(true)
    expect(usePinsStore.getState().isPinned('bom')).toBe(true)

    vi.mocked(ext.pinExtension).mockRejectedValueOnce(new Error('429'))
    expect(await usePinsStore.getState().pin('cam')).toBe(false)
    expect(usePinsStore.getState().isPinned('cam')).toBe(false)

    vi.mocked(ext.unpinExtension).mockResolvedValueOnce(undefined)
    expect(await usePinsStore.getState().unpin('bom')).toBe(true)
    expect(usePinsStore.getState().isPinned('bom')).toBe(false)
  })

  it('reset leaves nothing behind', async () => {
    vi.mocked(ext.pinExtension).mockResolvedValueOnce(pinRow('bom'))
    await usePinsStore.getState().pin('bom')
    usePinsStore.getState().reset()
    expect(usePinsStore.getState()).toMatchObject({ status: 'idle', pins: [] })
  })
})
