// SOLUSDEV-235 / EXT-14 — which installed extensions earn a rail entry, and in
// what order (wireflow extensions-runtime.md §2: installed + enabled + not
// blocked + `[views.page]`, by install time then label, capped).
import { describe, it, expect } from 'vitest'
import { fakeInstall, fakeManifest } from '../extensions/frame/testing/fixtures'
import type { ExtensionInstallApi } from '../../lib/api/resources.extensions'
import { railEntriesFrom, RAIL_EXTENSION_CAP } from './extensionRail'

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
        installedAt: '2026-09-01T00:00:00Z'
      }
    ])
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
