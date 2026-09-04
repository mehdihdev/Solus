// SOLUSDEV-235 / EXT-20 — the renderer-side developer registrations (ADR-035
// §4, extensions-runtime.md §7): hydrate from main's index, load/reload/remove
// through the bridge, and the selector the frame resolver consumes.
import { describe, it, expect, vi } from 'vitest'
import { fakeBridge, fakeManifest } from '../extensions/frame/testing/fixtures'
import {
  createDevExtensionsStore,
  NO_DESKTOP_PROBLEM,
  selectDevRegistration,
  useDevExtensionsStore
} from './devExtensionsStore'

const NOW = '2026-09-03T10:00:00.000Z'
const BOM_PATH = '/Users/maya/code/solus-ext-bom'
const BROKEN_PATH = '/Users/maya/code/broken-ext'
const PROBLEMS = [
  'views.page.entry: must be a relative path with no `..` segments',
  'store.privacy_policy: required when permissions are declared'
]

/** A bridge whose devLoad answers per folder: manifest for good paths, problems otherwise. */
function bridgeAnswering(
  answers: Record<string, ReturnType<typeof fakeManifest> | readonly string[]>,
  initial: Parameters<typeof fakeBridge>[0] = {}
): ReturnType<typeof fakeBridge> {
  const bridge = fakeBridge(initial)
  bridge.devLoad = vi.fn(async (path: string) => {
    const answer = answers[path]
    if (answer === undefined) return { ok: false as const, problems: ['path: unknown'] }
    if (Array.isArray(answer)) return { ok: false as const, problems: answer as string[] }
    return { ok: true as const, manifest: answer as ReturnType<typeof fakeManifest>, devPath: path }
  })
  return bridge
}

function storeWith(
  bridge: ReturnType<typeof fakeBridge> | null
): ReturnType<typeof createDevExtensionsStore> {
  return createDevExtensionsStore({ bridge: () => bridge, now: () => NOW })
}

describe('devExtensionsStore.hydrate', () => {
  it('keeps only dev rows from the index and re-validates each through devLoad', async () => {
    const bridge = bridgeAnswering(
      { [BOM_PATH]: fakeManifest() },
      {
        bom: { version: '1.2.0', source: 'dev', devPath: BOM_PATH },
        lint: { version: '0.4.0', source: 'registry' }
      }
    )
    const store = storeWith(bridge)

    await store.getState().hydrate()

    expect(bridge.devLoad).toHaveBeenCalledTimes(1)
    expect(bridge.devLoad).toHaveBeenCalledWith(BOM_PATH)
    expect(Object.keys(store.getState().entries)).toEqual(['bom'])
    expect(store.getState().entries.bom).toEqual({
      manifest: fakeManifest(),
      devPath: BOM_PATH,
      loadedAt: NOW,
      problems: []
    })
  })

  it('lists a registration whose folder no longer validates as not loaded, with its problems', async () => {
    const bridge = bridgeAnswering(
      { [BROKEN_PATH]: PROBLEMS },
      { broken: { version: '0.1.0', source: 'dev', devPath: BROKEN_PATH } }
    )
    const store = storeWith(bridge)

    await store.getState().hydrate()

    expect(store.getState().entries.broken).toEqual({
      manifest: null,
      devPath: BROKEN_PATH,
      loadedAt: NOW,
      problems: PROBLEMS
    })
  })

  it('does nothing outside the desktop app', async () => {
    const store = storeWith(null)
    await store.getState().hydrate()
    expect(store.getState().entries).toEqual({})
  })
})

describe('devExtensionsStore.load', () => {
  it('registers the manifest under its id on success', async () => {
    const bridge = bridgeAnswering({ [BOM_PATH]: fakeManifest() })
    const store = storeWith(bridge)

    const outcome = await store.getState().load(BOM_PATH)

    expect(outcome).toEqual({ ok: true, slug: 'bom' })
    expect(store.getState().entries.bom).toEqual({
      manifest: fakeManifest(),
      devPath: BOM_PATH,
      loadedAt: NOW,
      problems: []
    })
  })

  it('returns the refusal verbatim and registers nothing for a refused folder', async () => {
    const refusal = [
      'path: must be an existing directory that is not the filesystem root, your home folder (or an ancestor of it), or ~/.solus'
    ]
    const bridge = bridgeAnswering({ '/Users/maya': refusal })
    const store = storeWith(bridge)

    const outcome = await store.getState().load('/Users/maya')

    expect(outcome).toEqual({ ok: false, slug: null, problems: refusal })
    expect(store.getState().entries).toEqual({})
  })

  it('returns manifest problems verbatim for a folder that never loaded', async () => {
    const bridge = bridgeAnswering({ [BROKEN_PATH]: PROBLEMS })
    const store = storeWith(bridge)

    const outcome = await store.getState().load(BROKEN_PATH)

    expect(outcome).toEqual({ ok: false, slug: null, problems: PROBLEMS })
    expect(store.getState().entries).toEqual({})
  })

  it('keeps the last good manifest and attaches the problems when a loaded folder breaks', async () => {
    const bridge = bridgeAnswering({ [BOM_PATH]: fakeManifest() })
    const store = storeWith(bridge)
    await store.getState().load(BOM_PATH)
    bridge.devLoad = vi.fn(async () => ({ ok: false as const, problems: PROBLEMS }))

    const outcome = await store.getState().load(BOM_PATH)

    expect(outcome).toEqual({ ok: false, slug: 'bom', problems: PROBLEMS })
    expect(store.getState().entries.bom.manifest).toEqual(fakeManifest())
    expect(store.getState().entries.bom.problems).toEqual(PROBLEMS)
  })

  it('refuses outside the desktop app', async () => {
    const store = storeWith(null)
    const outcome = await store.getState().load(BOM_PATH)
    expect(outcome).toEqual({ ok: false, slug: null, problems: [NO_DESKTOP_PROBLEM] })
  })

  it('reports a bridge failure as a problem instead of throwing', async () => {
    const bridge = fakeBridge()
    bridge.devLoad = vi.fn(async () => {
      throw new Error('ipc down')
    })
    const store = storeWith(bridge)

    const outcome = await store.getState().load(BOM_PATH)

    expect(outcome.ok).toBe(false)
    expect(outcome.ok === false && outcome.problems).toHaveLength(1)
  })
})

describe('devExtensionsStore.reload', () => {
  it('re-validates the registered folder and refreshes the manifest and timestamp', async () => {
    const bridge = bridgeAnswering({ [BOM_PATH]: fakeManifest() })
    let tick = 0
    const store = createDevExtensionsStore({ bridge: () => bridge, now: () => `t${tick++}` })
    await store.getState().load(BOM_PATH)
    const updated = fakeManifest({ extension: { ...fakeManifest().extension, version: '1.3.0' } })
    bridge.devLoad = vi.fn(async () => ({
      ok: true as const,
      manifest: updated,
      devPath: BOM_PATH
    }))

    const outcome = await store.getState().reload('bom')

    expect(outcome).toEqual({ ok: true, slug: 'bom' })
    expect(bridge.devLoad).toHaveBeenCalledWith(BOM_PATH)
    expect(store.getState().entries.bom.manifest).toEqual(updated)
    expect(store.getState().entries.bom.loadedAt).toBe('t1')
  })

  it('surfaces problems on the row and keeps the last good manifest', async () => {
    const bridge = bridgeAnswering({ [BOM_PATH]: fakeManifest() })
    const store = storeWith(bridge)
    await store.getState().load(BOM_PATH)
    bridge.devLoad = vi.fn(async () => ({ ok: false as const, problems: PROBLEMS }))

    const outcome = await store.getState().reload('bom')

    expect(outcome).toEqual({ ok: false, slug: 'bom', problems: PROBLEMS })
    expect(store.getState().entries.bom.manifest).toEqual(fakeManifest())
    expect(store.getState().entries.bom.problems).toEqual(PROBLEMS)
  })

  it('answers not-loaded for an unknown slug without touching the bridge', async () => {
    const bridge = fakeBridge()
    const store = storeWith(bridge)

    const outcome = await store.getState().reload('ghost')

    expect(outcome.ok).toBe(false)
    expect(bridge.devLoad).not.toHaveBeenCalled()
  })
})

describe('devExtensionsStore.remove', () => {
  it('drops the registration when main confirms', async () => {
    const bridge = bridgeAnswering({ [BOM_PATH]: fakeManifest() })
    const store = storeWith(bridge)
    await store.getState().load(BOM_PATH)

    expect(await store.getState().remove('bom')).toBe(true)

    expect(bridge.devRemove).toHaveBeenCalledWith('bom')
    expect(store.getState().entries).toEqual({})
  })

  it('keeps the registration when main refuses', async () => {
    const bridge = bridgeAnswering({ [BOM_PATH]: fakeManifest() })
    bridge.devRemove = vi.fn(async () => ({ ok: false }))
    const store = storeWith(bridge)
    await store.getState().load(BOM_PATH)

    expect(await store.getState().remove('bom')).toBe(false)

    expect(Object.keys(store.getState().entries)).toEqual(['bom'])
  })

  it('refuses outside the desktop app', async () => {
    const store = storeWith(null)
    expect(await store.getState().remove('bom')).toBe(false)
  })
})

describe('selectDevRegistration', () => {
  it('returns the installedBundle shape with every declared scope and origin granted', () => {
    const manifest = fakeManifest({
      permissions: { scopes: ['graph.read', 'sol.ask'], network: ['https://api.example.com'] }
    })
    const state = {
      entries: { bom: { manifest, devPath: BOM_PATH, loadedAt: NOW, problems: [] } }
    }

    expect(selectDevRegistration(state, 'bom')).toEqual({
      manifest,
      grantedScopes: ['graph.read', 'sol.ask'],
      grantedNetwork: ['https://api.example.com']
    })
  })

  it('returns null for an unknown slug and for a registration that never validated', () => {
    const state = {
      entries: {
        broken: { manifest: null, devPath: BROKEN_PATH, loadedAt: NOW, problems: PROBLEMS }
      }
    }
    expect(selectDevRegistration(state, 'bom')).toBeNull()
    expect(selectDevRegistration(state, 'broken')).toBeNull()
  })
})

describe('useDevExtensionsStore', () => {
  it('starts empty and is not persisted', () => {
    expect(useDevExtensionsStore.getState().entries).toEqual({})
    expect(localStorage.length).toBe(0)
  })
})
