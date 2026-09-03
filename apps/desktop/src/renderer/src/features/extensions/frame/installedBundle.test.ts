// SOLUSDEV-235 / EXT-13 — every branch of the resolver, React-free.
import { describe, it, expect, vi } from 'vitest'
import { ApiError } from '../../../lib/api/envelope.types'
import { NO_DESKTOP_MESSAGE, resolveInstalledBundle } from './installedBundle'
import type { InstalledBundleState } from './installedBundle'
import { fakeBridge, fakeBundleDeps, fakeInstall, fakeManifest } from './testing/fixtures'

const input = { projectId: 'p1', slug: 'bom', view: 'page' as const }

describe('resolveInstalledBundle', () => {
  it('is ready straight from the cache when the pinned version is installed locally', async () => {
    const deps = fakeBundleDeps()
    const progress: InstalledBundleState[] = []
    const state = await resolveInstalledBundle(input, deps, (s) => progress.push(s))
    expect(state).toMatchObject({
      status: 'ready',
      version: '1.2.0',
      entry: 'page.html',
      name: 'BOM',
      settings: { refresh: 'hourly' },
      publisher: { displayName: 'Solus', verified: true },
      policy: {
        extensionId: 'bom',
        version: '1.2.0',
        projectId: 'p1',
        grantedScopes: ['graph.read'],
        enabled: true,
        blocked: false,
        mode: 'page'
      }
    })
    expect(progress).toEqual([])
    expect(deps.fetchBundle).not.toHaveBeenCalled()
  })

  it('picks the entry of the requested view', async () => {
    const deps = fakeBundleDeps()
    const widget = await resolveInstalledBundle({ ...input, view: 'widget' }, deps)
    const win = await resolveInstalledBundle({ ...input, view: 'window' }, deps)
    expect(widget).toMatchObject({ status: 'ready', entry: 'widget.html' })
    expect(win).toMatchObject({ status: 'ready', entry: 'window.html', policy: { mode: 'window' } })
  })

  it('errors honestly when the manifest declares no such view', async () => {
    const manifest = fakeManifest({ views: { widget: { entry: 'w.html', preferred: 'compact' } } })
    const install = fakeInstall()
    const deps = fakeBundleDeps({
      listInstalls: async () => [{ ...install, version: { ...install.version, manifest } }]
    })
    expect(await resolveInstalledBundle(input, deps)).toEqual({
      status: 'error',
      step: 'missing_view',
      message: 'BOM has no page view.'
    })
  })

  it('refuses outside the desktop app', async () => {
    const deps = fakeBundleDeps({ bridge: null })
    expect(await resolveInstalledBundle(input, deps)).toEqual({
      status: 'error',
      step: 'no_desktop',
      message: NO_DESKTOP_MESSAGE
    })
    expect(deps.listInstalls).not.toHaveBeenCalled()
  })

  it('reports not_installed when the project has no row for the slug', async () => {
    const deps = fakeBundleDeps({ listInstalls: async () => [] })
    expect(await resolveInstalledBundle(input, deps)).toEqual({ status: 'not_installed' })
  })
})

describe('resolveInstalledBundle install row', () => {
  it('reports blocked before disabled, and disabled before the cache', async () => {
    const blocked = fakeBundleDeps({
      bridge: fakeBridge(),
      listInstalls: async () => [
        fakeInstall({ enabled: false, policy: { blocked: true, default_installed: false } })
      ]
    })
    expect(await resolveInstalledBundle(input, blocked)).toEqual({ status: 'blocked', name: 'BOM' })
    const disabled = fakeBundleDeps({
      bridge: fakeBridge(),
      listInstalls: async () => [fakeInstall({ enabled: false })]
    })
    expect(await resolveInstalledBundle(input, disabled)).toEqual({
      status: 'disabled',
      name: 'BOM'
    })
    expect(disabled.fetchBundle).not.toHaveBeenCalled()
  })

  it('surfaces a failed install lookup as an error, not as not_installed', async () => {
    const deps = fakeBundleDeps({
      listInstalls: async () => {
        throw new ApiError(500, 'internal', 'boom')
      }
    })
    expect(await resolveInstalledBundle(input, deps)).toMatchObject({
      status: 'error',
      step: 'install_lookup'
    })
  })
})

describe('resolveInstalledBundle cache', () => {
  it('downloads and installs once when the bundle is not cached, reporting caching', async () => {
    const bridge = fakeBridge()
    const deps = fakeBundleDeps({ bridge })
    const progress: InstalledBundleState[] = []
    const state = await resolveInstalledBundle(input, deps, (s) => progress.push(s))
    expect(progress).toEqual([{ status: 'caching', name: 'BOM' }])
    expect(deps.fetchBundle).toHaveBeenCalledWith('bom', '1.2.0')
    expect(bridge.install).toHaveBeenCalledTimes(1)
    expect(bridge.install).toHaveBeenCalledWith({
      id: 'bom',
      version: '1.2.0',
      contentHash: 'a'.repeat(64),
      bytes: expect.any(ArrayBuffer)
    })
    expect(state).toMatchObject({ status: 'ready', version: '1.2.0' })
  })

  it('treats a cached OTHER version as not cached (the pin is the truth)', async () => {
    const bridge = fakeBridge({ bom: { version: '1.1.0', source: 'registry' } })
    const deps = fakeBundleDeps({ bridge })
    await resolveInstalledBundle(input, deps)
    expect(bridge.install).toHaveBeenCalledTimes(1)
  })

  it('maps a failed download to §8 copy and does not retry on its own', async () => {
    const bridge = fakeBridge()
    const deps = fakeBundleDeps({
      bridge,
      fetchBundle: vi.fn(async () => {
        throw new TypeError('offline')
      })
    })
    expect(await resolveInstalledBundle(input, deps)).toEqual({
      status: 'error',
      step: 'download',
      message: "Couldn't download BOM."
    })
    expect(deps.fetchBundle).toHaveBeenCalledTimes(1)
    expect(bridge.install).not.toHaveBeenCalled()
  })

  it('maps hash_mismatch and every other installer refusal to their §8 copy', async () => {
    const mismatch = fakeBundleDeps({
      bridge: fakeBridge({}, { ok: false, error: 'hash_mismatch' })
    })
    expect(await resolveInstalledBundle(input, mismatch)).toEqual({
      status: 'error',
      step: 'hash_mismatch',
      message: "The downloaded bundle didn't match the registry."
    })
    const rejected = fakeBundleDeps({
      bridge: fakeBridge({}, { ok: false, error: 'zip_invalid' })
    })
    expect(await resolveInstalledBundle(input, rejected)).toEqual({
      status: 'error',
      step: 'rejected',
      message: "This version's bundle was rejected."
    })
  })

  it('errors when the installer said ok but the index still lacks the version', async () => {
    const bridge = fakeBridge()
    bridge.install = vi.fn(async () => ({ ok: true as const }))
    const deps = fakeBundleDeps({ bridge })
    expect(await resolveInstalledBundle(input, deps)).toMatchObject({
      status: 'error',
      step: 'rejected'
    })
  })
})

describe('resolveInstalledBundle developer mode', () => {
  it('lets a developer registration take precedence with mode dev and version dev', async () => {
    const manifest = fakeManifest()
    const deps = fakeBundleDeps({
      devRegistration: () => ({ manifest, grantedScopes: ['graph.read'], grantedNetwork: [] })
    })
    const state = await resolveInstalledBundle(input, deps)
    expect(state).toMatchObject({
      status: 'ready',
      version: 'dev',
      entry: 'page.html',
      publisher: null,
      settings: {},
      policy: { mode: 'dev', version: 'dev', enabled: true, blocked: false, projectId: 'p1' }
    })
    expect(deps.listInstalls).not.toHaveBeenCalled()
  })

  it('reports a missing view for a developer registration too', async () => {
    const manifest = fakeManifest({
      views: { page: { entry: 'p.html', icon: 'i.svg', label: 'B' } }
    })
    const deps = fakeBundleDeps({
      devRegistration: () => ({ manifest, grantedScopes: [], grantedNetwork: [] })
    })
    expect(await resolveInstalledBundle({ ...input, view: 'window' }, deps)).toEqual({
      status: 'error',
      step: 'missing_view',
      message: 'BOM has no window view.'
    })
  })
})
