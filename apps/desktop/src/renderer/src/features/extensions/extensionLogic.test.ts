// SOLUSDEV-235 — pure rules over the server catalog and install rows.
import { describe, it, expect } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import {
  assetUrlsOf,
  availabilityOf,
  buildViews,
  catalogSummaryOf,
  connectedKinds,
  contributionsOf,
  declaredGrants,
  grantsRequiredOf,
  installsLabel,
  installStateOf,
  isSafeExternalUrl,
  missingRequirements,
  NOT_INSTALLED,
  partitionViews,
  PERMISSION_TEXT,
  requirementLabel,
  settingValuesOf,
  toRequirements
} from './extensionLogic'
import { catalogItem, installRow, manifest, viewOf } from './testing/fixtures'

describe('connectedKinds', () => {
  it('maps API source types onto requirement kinds and ignores unknown types', () => {
    const kinds = connectedKinds(['github', 'kicad', 'onshape', 'ros', 'mystery'])
    expect([...kinds].sort()).toEqual(['cad', 'code', 'eda', 'runtime'])
  })

  it('collapses several sources of one kind', () => {
    expect(connectedKinds(['kicad', 'altium']).size).toBe(1)
  })
})

describe('toRequirements', () => {
  it('admits only the contract source kinds and drops groups left empty', () => {
    expect(toRequirements([['eda', 'bogus'], ['nope'], ['cad']])).toEqual([['eda'], ['cad']])
    expect(toRequirements('garbage' as never)).toEqual([])
  })
})

describe('missingRequirements', () => {
  it('is empty when nothing is required', () => {
    expect(missingRequirements([], new Set())).toEqual([])
  })

  it('treats a group as an OR: one connected member satisfies it', () => {
    expect(missingRequirements([['cad', 'eda']], new Set(['eda']))).toEqual([])
    expect(missingRequirements([['cad', 'eda']], new Set(['code']))).toEqual([['cad', 'eda']])
  })

  it('treats groups as an AND: every group must be met', () => {
    expect(missingRequirements([['eda'], ['runtime']], new Set(['eda']))).toEqual([['runtime']])
  })
})

describe('requirementLabel', () => {
  it('joins alternatives with | and conjunctions with +', () => {
    expect(requirementLabel([['cad', 'eda']])).toBe('CAD|EDA')
    expect(requirementLabel([['eda'], ['canbus']])).toBe('EDA + CANBUS')
  })
})

describe('installStateOf', () => {
  it('reads the install row into the Store state', () => {
    const state = installStateOf(
      installRow({
        enabled: false,
        update_available: { version: '1.3.0', widens_permissions: true },
        policy: { blocked: true, default_installed: false }
      })
    )
    expect(state).toEqual({
      installed: true,
      enabled: false,
      settings: { refresh: 'hourly' },
      grantedScopes: ['graph.read', 'sources.read'],
      grantedNetwork: ['https://api.octopart.com'],
      pinnedVersion: '1.2.0',
      updateAvailable: { version: '1.3.0', widensPermissions: true },
      blocked: true
    })
  })

  it('NOT_INSTALLED carries no grants, no pin, no settings', () => {
    expect(NOT_INSTALLED).toEqual({
      installed: false,
      enabled: false,
      settings: {},
      grantedScopes: [],
      grantedNetwork: [],
      pinnedVersion: null,
      updateAvailable: null,
      blocked: false
    })
  })
})

describe('catalogSummaryOf', () => {
  it('keeps the honest install count and derives the requirements', () => {
    const summary = catalogSummaryOf(catalogItem({ install_count: 0 }))
    expect(summary).toMatchObject({
      slug: 'bom',
      publisher: 'Solus',
      verified: true,
      installCount: 0,
      latestVersion: '1.2.0',
      requires: [['eda']],
      views: ['widget', 'page'],
      inCatalog: true
    })
  })

  it('reports null when the catalog carries no count', () => {
    expect(
      catalogSummaryOf(catalogItem({ install_count: undefined as never })).installCount
    ).toBeNull()
  })
})

describe('availabilityOf', () => {
  it('installed wins regardless of requirements', () => {
    expect(availabilityOf(installStateOf(installRow()), [['eda']], false)).toBe('installed')
  })

  it('a team block beats a missing source', () => {
    expect(availabilityOf(NOT_INSTALLED, [['eda']], true)).toBe('blocked')
  })

  it('an uninstalled extension is blocked by unmet requirements, otherwise available', () => {
    expect(availabilityOf(NOT_INSTALLED, [['eda']], false)).toBe('needs_source')
    expect(availabilityOf(NOT_INSTALLED, [], false)).toBe('available')
  })
})

describe('buildViews', () => {
  const scene = manifest({
    extension: { ...manifest().extension, id: 'scene', name: 'Scene', requires: [] },
    permissions: { scopes: [], network: [] }
  })

  it('joins the catalog with install rows, details and connected sources in catalog order', () => {
    const views = buildViews({
      catalog: [
        catalogItem(),
        catalogItem({ slug: 'scene', name: 'Scene', requires: [], views: ['widget'] })
      ],
      installs: [installRow({ version: { ...installRow().version, manifest: scene } })],
      details: {},
      connected: new Set(),
      blocked: new Set()
    })
    expect(views.map((v) => v.catalog.slug)).toEqual(['bom', 'scene'])
    expect(views[0]).toMatchObject({ availability: 'needs_source', manifest: null })
    expect(views[0].missing).toEqual([['eda']])
    expect(views[1]).toMatchObject({ availability: 'installed', state: { pinnedVersion: '1.2.0' } })
    expect(views[1].manifest?.extension.id).toBe('scene')
  })

  it('fills the manifest of an uninstalled extension from the fetched detail', () => {
    const views = buildViews({
      catalog: [catalogItem()],
      installs: [],
      details: { bom: manifest() },
      connected: new Set(['eda']),
      blocked: new Set()
    })
    expect(views[0].availability).toBe('available')
    expect(views[0].manifest?.permissions.scopes).toEqual(['graph.read', 'sources.read'])
    expect(views[0].catalog.assetUrls.privacyPolicy).toBe(
      '/extensions/bom/versions/1.2.0/assets/PRIVACY.md'
    )
  })

  it('keeps an install whose version left the catalog, marked as such', () => {
    const views = buildViews({
      catalog: [],
      installs: [installRow()],
      details: {},
      connected: new Set(),
      blocked: new Set()
    })
    expect(views).toHaveLength(1)
    expect(views[0].catalog).toMatchObject({
      slug: 'bom',
      name: 'BOM',
      inCatalog: false,
      installCount: null,
      latestVersion: '1.2.0'
    })
    expect(views[0].availability).toBe('installed')
  })

  it('marks a slug the server refused as blocked', () => {
    const views = buildViews({
      catalog: [catalogItem({ requires: [] })],
      installs: [],
      details: {},
      connected: new Set(),
      blocked: new Set(['bom'])
    })
    expect(views[0].availability).toBe('blocked')
  })
})

describe('partitionViews', () => {
  it('splits installed from the rest, keeping order', () => {
    const a = viewOf({ install: {}, catalog: { slug: 'a' } })
    const b = viewOf({ catalog: { slug: 'b' } })
    const c = viewOf({ install: {}, catalog: { slug: 'c' } })
    const { installed, popular } = partitionViews([a, b, c])
    expect(installed.map((v) => v.catalog.slug)).toEqual(['a', 'c'])
    expect(popular.map((v) => v.catalog.slug)).toEqual(['b'])
  })
})

describe('contributionsOf', () => {
  it('derives rows from the manifest views plus a permissions summary', () => {
    const rows = contributionsOf(
      viewOf({
        manifest: manifest({
          views: {
            widget: { entry: 'w.html', preferred: 'wide' },
            page: { entry: 'p.html', icon: 'i.svg', label: 'BOM' },
            window: { entry: 'x.html', title: 'BOM viewer' }
          }
        })
      })
    )
    expect(rows.map((r) => [r.kind, r.title])).toEqual([
      ['widget', 'Widget'],
      ['page', 'Page: BOM'],
      ['window', 'Window: BOM viewer'],
      ['permissions', 'Permissions']
    ])
    expect(rows[3].detail).toBe('2 scopes · 1 network origin')
  })

  it('falls back to the catalog view kinds before the manifest is loaded', () => {
    const view = { ...viewOf({ catalog: { views: ['widget', 'window'] } }), manifest: null }
    expect(contributionsOf(view).map((r) => r.title)).toEqual(['Widget', 'Window'])
  })

  it('says when an extension asks for nothing', () => {
    const rows = contributionsOf(
      viewOf({ manifest: manifest({ permissions: { scopes: [], network: [] } }) })
    )
    expect(rows.at(-1)?.detail).toBe('Asks for nothing')
  })
})

describe('grants', () => {
  it('declaredGrants is the whole declared set (all-or-nothing)', () => {
    expect(declaredGrants(manifest())).toEqual({
      scopes: ['graph.read', 'sources.read'],
      network: ['https://api.octopart.com']
    })
  })

  it('grantsRequiredOf reads the 409 details and admits only contract scopes', () => {
    const err = new ApiError(409, 'grants_required', 'widened', [
      { scopes: ['telemetry.read', 'bogus'], network: ['https://x.example', 42] }
    ])
    expect(grantsRequiredOf(err)).toEqual({
      scopes: ['telemetry.read'],
      network: ['https://x.example']
    })
    expect(grantsRequiredOf(new ApiError(409, 'grants_required', 'x'))).toEqual({
      scopes: [],
      network: []
    })
  })

  it('PERMISSION_TEXT covers every scope in the closed set', () => {
    for (const scope of [
      'graph.read',
      'telemetry.read',
      'sources.read',
      'findings.write',
      'sol.ask',
      'storage.own',
      'focus.read',
      'focus.write'
    ] as const)
      expect(PERMISSION_TEXT[scope].title).toBeTruthy()
  })
})

describe('settingValuesOf', () => {
  it('overlays stored values on the manifest defaults', () => {
    expect(settingValuesOf(manifest(), { refresh: 'daily', stray: 'x' })).toEqual({
      refresh: 'daily',
      include_dnp: false,
      max_rows: 200,
      currency: 'USD'
    })
  })
})

describe('assetUrlsOf', () => {
  it('derives the store-facing asset routes from the manifest paths', () => {
    expect(assetUrlsOf('bom', '1.2.0', manifest())).toEqual({
      icon: '/extensions/bom/versions/1.2.0/assets/icon.svg',
      privacyPolicy: '/extensions/bom/versions/1.2.0/assets/PRIVACY.md'
    })
    expect(assetUrlsOf('bom', '1.2.0', null)).toEqual({ icon: null, privacyPolicy: null })
  })
})

describe('installsLabel', () => {
  it('renders an honest dash until the catalog reports a count', () => {
    expect(installsLabel(null)).toBe('— installs')
    expect(installsLabel(1200)).toBe('1,200 installs')
  })

  it('uses the singular for exactly one install', () => {
    expect(installsLabel(1)).toBe('1 install')
    expect(installsLabel(0)).toBe('0 installs')
  })
})

describe('isSafeExternalUrl', () => {
  it('accepts only well-formed https URLs', () => {
    expect(isSafeExternalUrl('https://docs.solusforge.com/x')).toBe(true)
    expect(isSafeExternalUrl('http://docs.solusforge.com/x')).toBe(false)
    expect(isSafeExternalUrl('javascript:alert(1)')).toBe(false)
    expect(isSafeExternalUrl('file:///etc/passwd')).toBe(false)
    expect(isSafeExternalUrl('not a url')).toBe(false)
    expect(isSafeExternalUrl(undefined)).toBe(false)
  })
})
