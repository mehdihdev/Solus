// SOLUSDEV-235 / EXT-13 — Open in window: manifest-sized request, DEV title suffix, refusals.
import { describe, it, expect, afterEach } from 'vitest'
import type { ReadyBundle } from '../frame/installedBundle'
import { fakeBridge, fakeManifest } from '../frame/testing/fixtures'
import { openExtensionWindow } from './openExtensionWindow'

const w = window as unknown as { solus?: { extensions?: ReturnType<typeof fakeBridge> } }

function ready(mode: 'page' | 'dev' = 'page'): ReadyBundle {
  return {
    status: 'ready',
    policy: {
      extensionId: 'bom',
      version: mode === 'dev' ? 'dev' : '1.2.0',
      projectId: 'p1',
      grantedScopes: [],
      grantedNetwork: [],
      enabled: true,
      blocked: false,
      mode
    },
    version: mode === 'dev' ? 'dev' : '1.2.0',
    manifest: fakeManifest(),
    entry: 'page.html',
    name: 'BOM',
    settings: {},
    publisher: null
  }
}

afterEach(() => {
  delete w.solus
})

describe('openExtensionWindow', () => {
  it('asks main for a window sized and titled from the manifest', async () => {
    const bridge = fakeBridge()
    w.solus = { extensions: bridge }
    expect(await openExtensionWindow(ready())).toBe(true)
    expect(bridge.openWindow).toHaveBeenCalledWith({
      id: 'bom',
      version: '1.2.0',
      title: 'BOM window',
      width: 900,
      height: 600
    })
  })

  it('appends — DEV to a developer registration title', async () => {
    const bridge = fakeBridge()
    w.solus = { extensions: bridge }
    await openExtensionWindow(ready('dev'))
    expect(bridge.openWindow).toHaveBeenCalledWith(
      expect.objectContaining({ version: 'dev', title: 'BOM window — DEV' })
    )
  })

  it('refuses without a ready bundle, a window view, or the desktop bridge', async () => {
    expect(await openExtensionWindow({ status: 'loading' })).toBe(false)
    expect(await openExtensionWindow(ready())).toBe(false)
    w.solus = { extensions: fakeBridge() }
    const noWindow = { ...ready(), manifest: fakeManifest({ views: {} }) }
    expect(await openExtensionWindow(noWindow)).toBe(false)
  })
})
