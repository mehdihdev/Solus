// SOLUSDEV-235 / EXT-14 — the rail's install poll: offline without a project or
// fetch, ready with page-view entries, icons reduced or neutral, a failed
// refresh keeps what is on screen, and a project switch never shows the old
// project's entries.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as ext from '../../lib/api/resources.extensions'
import type { Page } from '../../lib/api/client'
import { useInterval } from '../../lib/useInterval'
import { fakeInstall, fakeManifest } from '../extensions/frame/testing/fixtures'
import { useDevExtensionsStore, type DevExtensionEntry } from '../devExtensions/devExtensionsStore'
import { usePinsStore } from '../extensions/pinsStore'
import { useExtensionRail, EXTENSION_RAIL_POLL_MS } from './useExtensionRail'

vi.mock('../../lib/useInterval', () => ({ useInterval: vi.fn() }))
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources.extensions')>()
  return {
    ...actual,
    listProjectExtensions: vi.fn(),
    listExtensionPins: vi.fn(async () => []),
    pinExtension: vi.fn()
  }
})

const SVG = '<svg viewBox="0 0 16 16"><path d="M0 0h16v16H0z"/></svg>'

function install(slug: string, installedAt: string, enabled = true): ext.ExtensionInstallApi {
  const base = fakeInstall({ installed_at: installedAt, enabled })
  return {
    ...base,
    extension: { ...base.extension, slug },
    version: {
      ...base.version,
      manifest: fakeManifest({
        views: { page: { entry: 'page.html', icon: `${slug}.svg`, label: slug.toUpperCase() } }
      })
    }
  }
}

function page(rows: ext.ExtensionInstallApi[], next?: string): Page<ext.ExtensionInstallApi[]> {
  return { data: rows, meta: { has_next: next !== undefined, next_cursor: next ?? null } }
}

/** A transport whose response depends on the requested icon path. */
const fetchIcon = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
  const url = String(input)
  if (url.includes('bom.svg'))
    return new Response(SVG, { headers: { 'content-type': 'image/svg+xml' } })
  if (url.includes('boom.svg')) throw new Error('network')
  return new Response('nope', { status: 404 })
})
const iconTransport = { getToken: async () => null, fetchImpl: fetchIcon }

const listMock = vi.mocked(ext.listProjectExtensions)

/** A validated dev-store row whose manifest declares the given views. */
function devEntry(
  slug: string,
  views: ReturnType<typeof fakeManifest>['views'] = {
    page: { entry: 'page.html', icon: `${slug}.svg`, label: `${slug.toUpperCase()} (dev)` }
  }
): DevExtensionEntry {
  return {
    manifest: fakeManifest({ extension: { ...fakeManifest().extension, id: slug }, views }),
    devPath: `/code/${slug}`,
    loadedAt: '2026-09-05T00:00:00Z',
    acknowledged: true,
    problems: []
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  usePinsStore.getState().reset()
  useDevExtensionsStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
  useAuthStore.setState({ status: 'authenticated' })
})

describe('useExtensionRail', () => {
  it('is offline without a project and never fetches', () => {
    useWorkspaceStore.setState({ project: null })
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    expect(result.current.status).toBe('offline')
    expect(result.current.entries).toEqual([])
    expect(listMock).not.toHaveBeenCalled()
  })

  it('is offline when workspace fetches are disabled', () => {
    useAuthStore.setState({ status: 'unauthenticated' })
    useWorkspaceStore.setState({ linked: false })
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    expect(result.current.status).toBe('offline')
    expect(listMock).not.toHaveBeenCalled()
  })

  it('lists the enabled page-view installs of the open project, following cursors', async () => {
    listMock
      .mockResolvedValueOnce(page([install('bom', '2026-09-01T00:00:00Z')], 'c2'))
      .mockResolvedValueOnce(
        page([
          install('off', '2026-09-01T00:00:00Z', false),
          install('cam', '2026-09-02T00:00:00Z')
        ])
      )
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.entries.map((e) => e.slug)).toEqual(['bom', 'cam'])
    expect(listMock).toHaveBeenNthCalledWith(1, 'p1', undefined)
    expect(listMock).toHaveBeenNthCalledWith(2, 'p1', 'c2')
  })
})

describe('useExtensionRail — icons', () => {
  it('reduces a fetched icon and falls back to null for a miss or a transport failure', async () => {
    listMock.mockResolvedValue(
      page([
        install('bom', '2026-09-01T00:00:00Z'),
        install('cam', '2026-09-02T00:00:00Z'),
        install('boom', '2026-09-03T00:00:00Z')
      ])
    )
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.icons.bom).toContain('<path'))
    await waitFor(() => expect(fetchIcon).toHaveBeenCalledTimes(3))
    expect(result.current.icons).toMatchObject({ cam: null, boom: null })
    expect(Object.keys(result.current.icons).sort()).toEqual(['bom', 'boom', 'cam'])
  })

  it('fetches each icon once, not once per poll', async () => {
    listMock.mockResolvedValue(page([install('bom', '2026-09-01T00:00:00Z')]))
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.icons.bom).toContain('<path'))
    const tick = vi.mocked(useInterval).mock.calls.at(-1)?.[0]
    await act(async () => {
      tick?.()
    })
    expect(fetchIcon).toHaveBeenCalledTimes(1)
  })
})

describe('useExtensionRail — refresh', () => {
  it('goes offline when the first load fails', async () => {
    listMock.mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.entries).toEqual([])
  })

  it('polls on the shared cadence and keeps the list through a failed refresh', async () => {
    listMock.mockResolvedValueOnce(page([install('bom', '2026-09-01T00:00:00Z')]))
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const [tick, ms, on] = vi.mocked(useInterval).mock.calls.at(-1) as [() => void, number, boolean]
    expect(ms).toBe(EXTENSION_RAIL_POLL_MS)
    expect(on).toBe(true)
    listMock.mockRejectedValueOnce(new Error('blip'))
    await act(async () => {
      tick()
    })
    expect(result.current.status).toBe('ready')
    expect(result.current.entries.map((e) => e.slug)).toEqual(['bom'])
  })

  it('never shows the previous project’s entries after a switch', async () => {
    listMock.mockResolvedValueOnce(page([install('bom', '2026-09-01T00:00:00Z')]))
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.entries).toHaveLength(1))
    let release: (v: ReturnType<typeof page>) => void = () => undefined
    listMock.mockImplementationOnce(() => new Promise((resolve) => (release = resolve)))
    act(() => useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } }))
    expect(result.current.entries).toEqual([])
    expect(result.current.status).toBe('loading')
    await act(async () => release(page([install('cam', '2026-09-02T00:00:00Z')])))
    await waitFor(() => expect(result.current.entries.map((e) => e.slug)).toEqual(['cam']))
    expect(listMock).toHaveBeenLastCalledWith('p2', undefined)
  })
})

describe('useExtensionRail — developer registrations (EXT-20)', () => {
  it('appends page-view dev registrations after the installs, marked dev, without fetching an icon', async () => {
    listMock.mockResolvedValue(page([install('bom', '2026-09-01T00:00:00Z')]))
    useDevExtensionsStore.setState({ entries: { lab: devEntry('lab') } })
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.entries.map((e) => [e.slug, e.dev, e.label])).toEqual([
      ['bom', false, 'BOM'],
      ['lab', true, 'LAB (dev)']
    ])
    await waitFor(() => expect(result.current.icons.bom).toContain('<path'))
    expect(result.current.icons.lab).toBeNull()
    expect(fetchIcon).toHaveBeenCalledTimes(1)
    expect(String(fetchIcon.mock.calls[0]?.[0])).not.toContain('lab.svg')
  })

  it('lets a dev registration shadow the registry install of the same slug', async () => {
    listMock.mockResolvedValue(
      page([install('bom', '2026-09-01T00:00:00Z'), install('cam', '2026-09-02T00:00:00Z')])
    )
    useDevExtensionsStore.setState({ entries: { bom: devEntry('bom') } })
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.entries.map((e) => [e.slug, e.dev])).toEqual([
      ['cam', false],
      ['bom', true]
    ])
  })

  it('ignores dev registrations without a page view, and reacts when one is removed', async () => {
    listMock.mockResolvedValue(page([]))
    useDevExtensionsStore.setState({
      entries: {
        widgety: devEntry('widgety', { widget: { entry: 'w.html', preferred: 'standard' } }),
        lab: devEntry('lab')
      }
    })
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.entries.map((e) => e.slug)).toEqual(['lab']))
    act(() => useDevExtensionsStore.setState({ entries: {} }))
    expect(result.current.entries).toEqual([])
  })
})

describe('useExtensionRail — pins (STORE ST3)', () => {
  it('hydrates the pins once and draws a pin-only entry beside the installs', async () => {
    listMock.mockResolvedValue(page([install('cam', '2026-09-02T00:00:00Z')]))
    vi.mocked(ext.listExtensionPins).mockResolvedValue([
      {
        slug: 'bom',
        name: 'BOM',
        verified: true,
        publisher: { display_name: 'Solus' },
        version: '2.0.0',
        views: ['page'],
        page: { label: 'BOM', icon: 'bom.svg' },
        pinned_at: '2026-09-06T00:00:00Z'
      }
    ])
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() =>
      expect(result.current.entries.map((e) => [e.slug, e.installed, e.pinned])).toEqual([
        ['bom', false, true],
        ['cam', true, false]
      ])
    )
    expect(vi.mocked(ext.listExtensionPins)).toHaveBeenCalledTimes(1)
    // The pin-only entry's icon is read from the latest approved version.
    await waitFor(() => expect(result.current.icons.bom).toContain('<svg'))
  })

  it('a pin made after mount reaches the rail without a poll', async () => {
    listMock.mockResolvedValue(page([]))
    const { result } = renderHook(() => useExtensionRail({ iconTransport }))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(ext.pinExtension).mockResolvedValueOnce({
      slug: 'bom',
      name: 'BOM',
      verified: true,
      publisher: { display_name: 'Solus' },
      version: null,
      views: [],
      page: null,
      pinned_at: '2026-09-06T00:00:00Z'
    })
    await act(() => usePinsStore.getState().pin('bom'))
    await waitFor(() => expect(result.current.entries.map((e) => e.slug)).toEqual(['bom']))
    expect(result.current.entries[0]).toMatchObject({ label: 'BOM', iconPath: null })
    expect(result.current.icons.bom).toBeNull()
  })
})
