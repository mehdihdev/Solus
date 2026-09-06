// SOLUSDEV-235 / EXT-14 — which installed extensions earn a rail entry, and in
// what order (wireflow extensions-runtime.md §2: installed + enabled + not
// blocked + `[views.page]`, by install time then label, capped).
import { describe, it, expect } from 'vitest'
import { fakeInstall, fakeManifest } from '../extensions/frame/testing/fixtures'
import type { ExtensionInstallApi, ExtensionPinApi } from '../../lib/api/resources.extensions'
import type { DevExtensionEntry } from '../devExtensions/devExtensionsStore'
import {
  devRailEntriesFrom,
  mergeRailEntries,
  railEntriesFrom,
  RAIL_EXTENSION_CAP,
  type RailExtensionEntry
} from './extensionRail'

function install(
  slug: string,
  installedAt: string,
  overrides: Partial<ExtensionInstallApi> = {},
  label = slug.toUpperCase()
): ExtensionInstallApi {
  const base = fakeInstall({ installed_at: installedAt, ...overrides })
  const manifest = fakeManifest({
    views: { page: { entry: 'page.html', icon: `${slug}.svg`, label } }
  })
  return {
    ...base,
    extension: { ...base.extension, slug },
    version: { ...base.version, manifest }
  }
}

describe('railEntriesFrom', () => {
  it('maps an enabled page-view install to a rail entry', () => {
    const entries = railEntriesFrom([install('bom', '2026-09-01T00:00:00Z')])
    expect(entries).toEqual([
      {
        slug: 'bom',
        label: 'BOM',
        iconPath: 'bom.svg',
        version: '1.2.0',
        installedAt: '2026-09-01T00:00:00Z',
        dev: false,
        pinned: false,
        installed: true,
        firstParty: false,
        publisher: { displayName: 'Solus', verified: true }
      }
    ])
  })

  it('marks an install whose pinned manifest declares a first-party table (STORE ST4)', () => {
    const row = install('bom', '2026-09-01T00:00:00Z')
    const firstParty = {
      ...row,
      version: {
        ...row.version,
        manifest: { ...row.version.manifest, backend: { capability: 'bom', routes: true } }
      }
    }
    expect(railEntriesFrom([firstParty])[0]?.firstParty).toBe(true)
    expect(railEntriesFrom([row])[0]?.firstParty).toBe(false)
  })

  it('drops disabled, blocked and page-less installs', () => {
    const noPage = fakeInstall({
      extension: { ...fakeInstall().extension, slug: 'widget-only' },
      version: {
        ...fakeInstall().version,
        manifest: fakeManifest({ views: { widget: { entry: 'w.html', preferred: 'standard' } } })
      }
    })
    const entries = railEntriesFrom([
      install('off', '2026-09-01T00:00:00Z', { enabled: false }),
      install('blocked', '2026-09-01T00:00:00Z', {
        policy: { blocked: true, default_installed: false }
      }),
      noPage,
      install('bom', '2026-09-02T00:00:00Z')
    ])
    expect(entries.map((e) => e.slug)).toEqual(['bom'])
  })

  it('orders by install time, then label', () => {
    const entries = railEntriesFrom([
      install('zeta', '2026-09-02T00:00:00Z', {}, 'Zeta'),
      install('alpha', '2026-09-02T00:00:00Z', {}, 'Alpha'),
      install('late', '2026-09-03T00:00:00Z', {}, 'Aardvark'),
      install('first', '2026-09-01T00:00:00Z', {}, 'Zulu')
    ])
    expect(entries.map((e) => e.slug)).toEqual(['first', 'alpha', 'zeta', 'late'])
  })

  it('caps the rail — the rest stay reachable from the Store', () => {
    const many = Array.from({ length: RAIL_EXTENSION_CAP + 3 }, (_, i) =>
      install(
        `ext-${String(i).padStart(2, '0')}`,
        `2026-09-01T00:00:${String(i).padStart(2, '0')}Z`
      )
    )
    const entries = railEntriesFrom(many)
    expect(entries).toHaveLength(RAIL_EXTENSION_CAP)
    expect(entries[0]?.slug).toBe('ext-00')
    expect(entries.at(-1)?.slug).toBe(`ext-${String(RAIL_EXTENSION_CAP - 1).padStart(2, '0')}`)
  })

  it('does not mutate its input', () => {
    const rows = [install('b', '2026-09-02T00:00:00Z'), install('a', '2026-09-01T00:00:00Z')]
    const snapshot = [...rows]
    railEntriesFrom(rows)
    expect(rows).toEqual(snapshot)
  })

  it('returns an empty list for no installs', () => {
    expect(railEntriesFrom([])).toEqual([])
  })
})

/** A §6.5 pin row (STORE ST3). */
function pin(slug: string, pinnedAt: string, page = true): ExtensionPinApi {
  return {
    slug,
    name: `${slug} ext`,
    verified: true,
    publisher: { display_name: 'Solus' },
    version: '2.0.0',
    views: page ? ['page'] : ['widget'],
    page: page ? { label: slug.toUpperCase(), icon: `${slug}.svg` } : null,
    pinned_at: pinnedAt
  }
}

describe('railEntriesFrom — pins (STORE ST3)', () => {
  it('draws a pinned extension in a project where it is not installed, marked not installed', () => {
    const entries = railEntriesFrom([], [pin('bom', '2026-09-06T00:00:00Z')])
    expect(entries).toEqual([
      {
        slug: 'bom',
        label: 'BOM',
        iconPath: 'bom.svg',
        version: '2.0.0',
        installedAt: '2026-09-06T00:00:00Z',
        dev: false,
        pinned: true,
        installed: false,
        firstParty: false,
        publisher: { displayName: 'Solus', verified: true }
      }
    ])
  })

  it('merges a pin with the install of the same slug into one entry carrying the install facts', () => {
    const entries = railEntriesFrom(
      [install('bom', '2026-09-01T00:00:00Z')],
      [pin('bom', '2026-09-06T00:00:00Z')]
    )
    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({
      slug: 'bom',
      version: '1.2.0',
      installedAt: '2026-09-01T00:00:00Z',
      pinned: true,
      installed: true
    })
  })

  it('puts pinned entries first, then the project installs, each by time', () => {
    const entries = railEntriesFrom(
      [install('cam', '2026-09-01T00:00:00Z'), install('bom', '2026-09-03T00:00:00Z')],
      [pin('bom', '2026-09-06T00:00:00Z'), pin('scope', '2026-09-05T00:00:00Z')]
    )
    expect(entries.map((e) => [e.slug, e.pinned, e.installed])).toEqual([
      ['scope', true, false],
      ['bom', true, true],
      ['cam', false, true]
    ])
  })

  it('a pin without a page view uses the extension name and the neutral glyph', () => {
    const [entry] = railEntriesFrom([], [pin('widget-only', '2026-09-06T00:00:00Z', false)])
    expect(entry).toMatchObject({ label: 'widget-only ext', iconPath: null, installed: false })
  })

  it('a pinned install that is disabled here is drawn as a pin, not as an install', () => {
    const [entry] = railEntriesFrom(
      [install('bom', '2026-09-01T00:00:00Z', { enabled: false })],
      [pin('bom', '2026-09-06T00:00:00Z')]
    )
    expect(entry).toMatchObject({ slug: 'bom', pinned: true, installed: false })
  })

  it('pins count toward the cap, ahead of installs', () => {
    const pins = Array.from({ length: RAIL_EXTENSION_CAP }, (_, i) =>
      pin(`pin-${i}`, `2026-09-06T00:00:${String(i).padStart(2, '0')}Z`)
    )
    const entries = railEntriesFrom([install('late', '2026-09-01T00:00:00Z')], pins)
    expect(entries).toHaveLength(RAIL_EXTENSION_CAP)
    expect(entries.some((e) => e.slug === 'late')).toBe(false)
  })
})

/** A dev-store row as main would have validated it. */
function devEntry(
  slug: string,
  loadedAt: string,
  views: Partial<ReturnType<typeof fakeManifest>['views']> = {
    page: { entry: 'page.html', icon: `${slug}.svg`, label: `${slug.toUpperCase()} (dev)` }
  }
): DevExtensionEntry {
  return {
    manifest: fakeManifest({ extension: { ...fakeManifest().extension, id: slug }, views }),
    devPath: `/code/${slug}`,
    loadedAt,
    acknowledged: true,
    problems: []
  }
}

describe('devRailEntriesFrom', () => {
  it('maps a dev registration with a page view to a DEV entry, label and icon from its manifest', () => {
    const entries = devRailEntriesFrom({
      entries: { bom: devEntry('bom', '2026-09-05T00:00:00Z') }
    })
    expect(entries).toEqual([
      {
        slug: 'bom',
        label: 'BOM (dev)',
        iconPath: 'bom.svg',
        version: 'dev',
        installedAt: '2026-09-05T00:00:00Z',
        dev: true,
        pinned: false,
        installed: false,
        firstParty: false,
        publisher: null
      }
    ])
  })

  it('skips registrations without a page view and rows that never validated', () => {
    const entries = devRailEntriesFrom({
      entries: {
        'widget-only': devEntry('widget-only', '2026-09-05T00:00:00Z', {
          widget: { entry: 'w.html', preferred: 'standard' }
        }),
        broken: {
          manifest: null,
          devPath: '/code/broken',
          loadedAt: 'x',
          acknowledged: true,
          problems: ['views: bad']
        },
        cam: devEntry('cam', '2026-09-06T00:00:00Z')
      }
    })
    expect(entries.map((e) => e.slug)).toEqual(['cam'])
  })

  it('orders by load time, then label', () => {
    const entries = devRailEntriesFrom({
      entries: {
        zed: devEntry('zed', '2026-09-05T00:00:00Z'),
        alpha: devEntry('alpha', '2026-09-05T00:00:00Z'),
        first: devEntry('first', '2026-09-04T00:00:00Z')
      }
    })
    expect(entries.map((e) => e.slug)).toEqual(['first', 'alpha', 'zed'])
  })
})

describe('mergeRailEntries', () => {
  const registry: readonly RailExtensionEntry[] = railEntriesFrom([
    install('bom', '2026-09-01T00:00:00Z'),
    install('cam', '2026-09-02T00:00:00Z')
  ])

  it('appends dev entries after the registry ones', () => {
    const dev = devRailEntriesFrom({ entries: { lab: devEntry('lab', '2026-09-05T00:00:00Z') } })
    const merged = mergeRailEntries(registry, dev)
    expect(merged.map((e) => [e.slug, e.dev])).toEqual([
      ['bom', false],
      ['cam', false],
      ['lab', true]
    ])
  })

  it('lets a dev registration shadow the registry install of the same slug (the frame resolver prefers dev)', () => {
    const dev = devRailEntriesFrom({ entries: { bom: devEntry('bom', '2026-09-05T00:00:00Z') } })
    const merged = mergeRailEntries(registry, dev)
    expect(merged.map((e) => [e.slug, e.dev])).toEqual([
      ['cam', false],
      ['bom', true]
    ])
  })

  it('returns the registry list itself when there is nothing to merge', () => {
    expect(mergeRailEntries(registry, [])).toBe(registry)
  })
})
