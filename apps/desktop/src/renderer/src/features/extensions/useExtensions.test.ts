// SOLUSDEV-235 — server catalog × server install rows × connected sources → views,
// and the install / update / uninstall flows over the typed client + desktop bridge.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act, waitFor, type RenderHookResult } from '@testing-library/react'
import { useExtensions, EXTENSIONS_POLL_MS, type ExtensionsData } from './useExtensions'
import * as ext from '../../lib/api/resources.extensions'
import * as bridgeModule from '../../lib/desktopBridge'
import * as sourcesHook from '../project/useProjectSources'
import { ApiError } from '../../lib/api/envelope.types'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { Source } from '../../lib/api/resources'
import type { Page } from '../../lib/api/client'
import type { ExtensionsBridge } from '../../lib/desktopBridge'
import { catalogItem, detail, installRow, manifest } from './testing/fixtures'
import { BUNDLE_DEFERRED_NOTE } from './extensionErrors'

vi.mock('../project/useProjectSources', () => ({ useProjectSources: vi.fn() }))
vi.mock('../../lib/desktopBridge', async (importOriginal) => ({
  ...(await importOriginal<typeof bridgeModule>()),
  getDesktopExtensionsBridge: vi.fn(() => null)
}))
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  listExtensions: vi.fn(),
  listProjectExtensions: vi.fn(),
  getExtension: vi.fn(),
  installExtension: vi.fn(),
  patchExtensionInstall: vi.fn(),
  uninstallProjectExtension: vi.fn(),
  fetchExtensionBundle: vi.fn()
}))

const scene = manifest({
  extension: { ...manifest().extension, id: 'scene', name: 'Scene', requires: [] },
  permissions: { scopes: ['graph.read'], network: [] }
})
const sceneRow = installRow({ version: { ...installRow().version, manifest: scene } })

function page<T>(data: T[], next: string | null = null): Promise<Page<T[]>> {
  return Promise.resolve({ data, meta: { has_next: next !== null, next_cursor: next } }) as never
}

function mockSources(status: sourcesHook.ProjectSourcesStatus, types: string[] = []): void {
  vi.mocked(sourcesHook.useProjectSources).mockReturnValue({
    status,
    sources: types.map((type) => ({ id: type, type }) as Source),
    actions: { refresh: vi.fn(), syncNow: vi.fn(), disconnect: vi.fn() }
  })
}

function fakeBridge(installOk = true): ExtensionsBridge {
  return {
    index: vi.fn(),
    install: vi.fn(async () => (installOk ? { ok: true } : { ok: false, error: 'hash_mismatch' })),
    uninstall: vi.fn(async () => ({ ok: true })),
    devLoad: vi.fn(),
    devRemove: vi.fn(),
    openWindow: vi.fn(),
    netFetch: vi.fn()
  } as unknown as ExtensionsBridge
}

async function ready(): Promise<RenderHookResult<ExtensionsData, string>> {
  const rendered = renderHook(() => useExtensions('p1'))
  await waitFor(() => expect(rendered.result.current.status).toBe('ready'))
  return rendered
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'P1' }, linked: true })
  mockSources('ready', [])
  vi.mocked(bridgeModule.getDesktopExtensionsBridge).mockReturnValue(null)
  vi.mocked(ext.listExtensions).mockImplementation(() =>
    page([
      catalogItem(),
      catalogItem({ slug: 'scene', name: 'Scene', requires: [], views: ['widget'] })
    ])
  )
  vi.mocked(ext.listProjectExtensions).mockImplementation(() => page([sceneRow]))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useExtensions — reading', () => {
  it('joins the server catalog with the install rows into views', async () => {
    const { result } = await ready()
    const byId = new Map(result.current.views.map((v) => [v.catalog.slug, v]))
    expect(byId.get('scene')).toMatchObject({
      availability: 'installed',
      state: {
        enabled: true,
        pinnedVersion: '1.2.0',
        grantedScopes: ['graph.read', 'sources.read']
      }
    })
    expect(byId.get('scene')?.manifest?.extension.id).toBe('scene')
    expect(byId.get('bom')).toMatchObject({ availability: 'needs_source', manifest: null })
    expect(byId.get('bom')?.missing).toEqual([['eda']])
    expect(result.current.updatesAvailable).toBe(0)
  })

  it('walks every catalog page, then appends installs the catalog no longer lists', async () => {
    vi.mocked(ext.listExtensions)
      .mockImplementationOnce(() => page([catalogItem({ slug: 'a', name: 'A' })], 'c2'))
      .mockImplementationOnce(() => page([catalogItem({ slug: 'b', name: 'B' })]))
    const { result } = await ready()
    expect(result.current.views.map((v) => v.catalog.slug)).toEqual(['a', 'b', 'scene'])
    expect(result.current.views[2].catalog.inCatalog).toBe(false)
    expect(vi.mocked(ext.listExtensions).mock.calls[1][0]).toMatchObject({ cursor: 'c2' })
  })

  it('unblocks an extension once a satisfying source is connected', async () => {
    mockSources('ready', ['kicad'])
    const { result } = await ready()
    expect(result.current.views.find((v) => v.catalog.slug === 'bom')?.availability).toBe(
      'available'
    )
  })

  it('counts installs with an update available', async () => {
    vi.mocked(ext.listProjectExtensions).mockImplementation(() =>
      page([{ ...sceneRow, update_available: { version: '1.3.0', widens_permissions: false } }])
    )
    const { result } = await ready()
    expect(result.current.updatesAvailable).toBe(1)
  })

  it('is offline without a fetchable session: nothing is called, nothing is shown', () => {
    useWorkspaceStore.setState({ linked: false })
    const { result } = renderHook(() => useExtensions('p1'))
    expect(result.current.status).toBe('offline')
    expect(result.current.views).toEqual([])
    expect(ext.listExtensions).not.toHaveBeenCalled()
  })

  it('reports offline when the Store API is unreachable, with requirements unmet', async () => {
    vi.mocked(ext.listExtensions).mockRejectedValue(new TypeError('fetch failed'))
    const { result } = renderHook(() => useExtensions('p1'))
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.views).toEqual([])
  })

  it('passes the sources status through so the screen can explain an offline gap', async () => {
    mockSources('offline', [])
    const { result } = await ready()
    expect(result.current.sourcesStatus).toBe('offline')
  })

  it("never judges requirements against another project's sources", async () => {
    mockSources('ready', ['kicad'])
    useWorkspaceStore.setState({ project: { id: 'p2', name: 'P2' } })
    const { result } = await ready()
    expect(result.current.sourcesStatus).toBe('offline')
    expect(result.current.views.find((v) => v.catalog.slug === 'bom')?.availability).toBe(
      'needs_source'
    )
  })

  it('re-reads the install rows on the poll interval', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await ready()
    expect(ext.listProjectExtensions).toHaveBeenCalledTimes(1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXTENSIONS_POLL_MS)
    })
    expect(ext.listProjectExtensions).toHaveBeenCalledTimes(2)
    expect(ext.listExtensions).toHaveBeenCalledTimes(1)
  })

  it('loadDetail fills the manifest of an uninstalled extension', async () => {
    vi.mocked(ext.getExtension).mockResolvedValue(detail())
    const { result } = await ready()
    await act(() => result.current.actions.loadDetail('bom'))
    const bom = result.current.views.find((v) => v.catalog.slug === 'bom')
    expect(bom?.manifest?.permissions.scopes).toEqual(['graph.read', 'sources.read'])
    expect(bom?.catalog.assetUrls.privacyPolicy).toBe(
      '/extensions/bom/versions/1.2.0/assets/PRIVACY.md'
    )
  })
})

describe('useExtensions — install', () => {
  const grants = {
    scopes: ['graph.read', 'sources.read'] as const,
    network: ['https://api.octopart.com']
  }

  it('PUTs the install, then fetches the bundle, then hands it to the desktop — in that order', async () => {
    const order: string[] = []
    const bridge = fakeBridge()
    vi.mocked(bridgeModule.getDesktopExtensionsBridge).mockReturnValue(bridge)
    vi.mocked(ext.installExtension).mockImplementation(async () => {
      order.push('put')
      return installRow()
    })
    vi.mocked(ext.fetchExtensionBundle).mockImplementation(async () => {
      order.push('bundle')
      return { bytes: new ArrayBuffer(4), contentHash: 'a'.repeat(64) }
    })
    vi.mocked(bridge.install).mockImplementation(async () => {
      order.push('desktop')
      return { ok: true }
    })
    const { result } = await ready()
    const outcome = await act(() => result.current.actions.install('bom', grants))
    expect(outcome).toEqual({ ok: true, bundle: 'cached' })
    expect(order).toEqual(['put', 'bundle', 'desktop'])
    expect(ext.installExtension).toHaveBeenCalledWith('p1', 'bom', { version: '1.2.0', grants })
    expect(ext.fetchExtensionBundle).toHaveBeenCalledWith('bom', '1.2.0')
    expect(bridge.install).toHaveBeenCalledWith({
      id: 'bom',
      version: '1.2.0',
      contentHash: 'a'.repeat(64),
      bytes: expect.any(ArrayBuffer)
    })
    expect(result.current.views.find((v) => v.catalog.slug === 'bom')?.availability).toBe(
      'installed'
    )
  })

  it('records the server install without a desktop bridge and says the bundle is deferred', async () => {
    vi.mocked(ext.installExtension).mockResolvedValue(installRow())
    const { result } = await ready()
    const outcome = await act(() => result.current.actions.install('bom', grants))
    expect(outcome).toEqual({ ok: true, bundle: 'deferred', note: BUNDLE_DEFERRED_NOTE })
    expect(ext.fetchExtensionBundle).not.toHaveBeenCalled()
    expect(result.current.views.find((v) => v.catalog.slug === 'bom')?.state.installed).toBe(true)
  })

  it('keeps the server install but reports a bundle the desktop refused', async () => {
    vi.mocked(bridgeModule.getDesktopExtensionsBridge).mockReturnValue(fakeBridge(false))
    vi.mocked(ext.installExtension).mockResolvedValue(installRow())
    vi.mocked(ext.fetchExtensionBundle).mockResolvedValue({
      bytes: new ArrayBuffer(4),
      contentHash: 'a'.repeat(64)
    })
    const { result } = await ready()
    const outcome = await act(() => result.current.actions.install('bom', grants))
    expect(outcome).toMatchObject({
      ok: true,
      bundle: 'failed',
      note: expect.stringMatching(/hash_mismatch/)
    })
  })

  it('refuses a bundle whose hash header disagrees with the install row', async () => {
    const bridge = fakeBridge()
    vi.mocked(bridgeModule.getDesktopExtensionsBridge).mockReturnValue(bridge)
    vi.mocked(ext.installExtension).mockResolvedValue(installRow())
    vi.mocked(ext.fetchExtensionBundle).mockResolvedValue({
      bytes: new ArrayBuffer(4),
      contentHash: 'b'.repeat(64)
    })
    const { result } = await ready()
    const outcome = await act(() => result.current.actions.install('bom', grants))
    expect(outcome).toMatchObject({ ok: true, bundle: 'failed' })
    expect(bridge.install).not.toHaveBeenCalled()
  })

  it('surfaces a team block and marks the extension blocked', async () => {
    vi.mocked(ext.installExtension).mockRejectedValue(
      new ApiError(403, 'extension_blocked', 'blocked')
    )
    const { result } = await ready()
    const outcome = await act(() => result.current.actions.install('bom', grants))
    expect(outcome).toEqual({
      ok: false,
      code: 'extension_blocked',
      message: 'Blocked by your team.'
    })
    expect(result.current.views.find((v) => v.catalog.slug === 'bom')?.availability).toBe('blocked')
  })

  it('maps the other route-plan error codes to user-facing text', async () => {
    vi.mocked(ext.installExtension)
      .mockRejectedValueOnce(new ApiError(422, 'validation_error', 'bad'))
      .mockRejectedValueOnce(new ApiError(403, 'scope_denied', 'no'))
      .mockRejectedValueOnce(new TypeError('fetch failed'))
    const { result } = await ready()
    const a = await act(() => result.current.actions.install('bom', grants))
    const b = await act(() => result.current.actions.install('bom', grants))
    const c = await act(() => result.current.actions.install('bom', grants))
    expect(a).toMatchObject({
      ok: false,
      code: 'validation_error',
      message: expect.stringMatching(/rejected/i)
    })
    expect(b).toMatchObject({
      ok: false,
      code: 'scope_denied',
      message: expect.stringMatching(/permission/i)
    })
    expect(c).toMatchObject({
      ok: false,
      code: 'unreachable',
      message: expect.stringMatching(/reach/i)
    })
  })
})

describe('useExtensions — update, uninstall, patch', () => {
  const updatable = {
    ...sceneRow,
    update_available: { version: '1.3.0', widens_permissions: true }
  }

  it('PUTs the latest version with the current grants; a 409 surfaces the additions', async () => {
    vi.mocked(ext.listProjectExtensions).mockImplementation(() => page([updatable]))
    vi.mocked(ext.installExtension).mockRejectedValueOnce(
      new ApiError(409, 'grants_required', 'more', [{ scopes: ['telemetry.read'], network: [] }])
    )
    const { result } = await ready()
    const first = await act(() => result.current.actions.update('scene'))
    expect(ext.installExtension).toHaveBeenCalledWith('p1', 'scene', {
      version: '1.3.0',
      grants: { scopes: ['graph.read', 'sources.read'], network: ['https://api.octopart.com'] }
    })
    expect(first).toEqual({
      ok: false,
      code: 'grants_required',
      message: expect.any(String),
      grantsRequired: { scopes: ['telemetry.read'], network: [] }
    })

    vi.mocked(ext.installExtension).mockResolvedValueOnce({
      ...sceneRow,
      version: { ...sceneRow.version, version: '1.3.0' }
    })
    const widened = {
      scopes: ['graph.read', 'sources.read', 'telemetry.read'] as const,
      network: ['https://api.octopart.com']
    }
    const second = await act(() => result.current.actions.update('scene', widened))
    expect(second).toMatchObject({ ok: true })
    expect(ext.installExtension).toHaveBeenLastCalledWith('p1', 'scene', {
      version: '1.3.0',
      grants: widened
    })
    expect(result.current.views.find((v) => v.catalog.slug === 'scene')?.state.pinnedVersion).toBe(
      '1.3.0'
    )
  })

  it('refuses to update when the server reports nothing newer', async () => {
    const { result } = await ready()
    const outcome = await act(() => result.current.actions.update('scene'))
    expect(outcome).toMatchObject({ ok: false, code: 'no_update' })
    expect(ext.installExtension).not.toHaveBeenCalled()
  })

  it('DELETEs the install, then removes the bundle from the desktop', async () => {
    const order: string[] = []
    const bridge = fakeBridge()
    vi.mocked(bridgeModule.getDesktopExtensionsBridge).mockReturnValue(bridge)
    vi.mocked(ext.uninstallProjectExtension).mockImplementation(async () => {
      order.push('delete')
    })
    vi.mocked(bridge.uninstall).mockImplementation(async () => {
      order.push('desktop')
      return { ok: true }
    })
    const { result } = await ready()
    const outcome = await act(() => result.current.actions.uninstall('scene'))
    expect(outcome).toEqual({ ok: true })
    expect(order).toEqual(['delete', 'desktop'])
    expect(ext.uninstallProjectExtension).toHaveBeenCalledWith('p1', 'scene')
    expect(bridge.uninstall).toHaveBeenCalledWith('scene')
    expect(result.current.views.find((v) => v.catalog.slug === 'scene')?.state.installed).toBe(
      false
    )
  })

  it('leaves the install in place when the DELETE fails', async () => {
    vi.mocked(ext.uninstallProjectExtension).mockRejectedValue(
      new ApiError(403, 'forbidden', 'viewer')
    )
    const { result } = await ready()
    const outcome = await act(() => result.current.actions.uninstall('scene'))
    expect(outcome).toMatchObject({ ok: false, code: 'forbidden' })
    expect(result.current.views.find((v) => v.catalog.slug === 'scene')?.state.installed).toBe(true)
  })

  it('PATCHes enablement and settings and applies the returned row', async () => {
    vi.mocked(ext.patchExtensionInstall)
      .mockResolvedValueOnce({ ...sceneRow, enabled: false })
      .mockResolvedValueOnce({ ...sceneRow, settings: { refresh: 'daily' } })
    const { result } = await ready()
    await act(() => result.current.actions.setEnabled('scene', false))
    expect(ext.patchExtensionInstall).toHaveBeenCalledWith('p1', 'scene', { enabled: false })
    expect(result.current.views.find((v) => v.catalog.slug === 'scene')?.state.enabled).toBe(false)
    await act(() => result.current.actions.setSettings('scene', { refresh: 'daily' }))
    expect(ext.patchExtensionInstall).toHaveBeenLastCalledWith('p1', 'scene', {
      settings: { refresh: 'daily' }
    })
    expect(result.current.views.find((v) => v.catalog.slug === 'scene')?.state.settings).toEqual({
      refresh: 'daily'
    })
  })
})
