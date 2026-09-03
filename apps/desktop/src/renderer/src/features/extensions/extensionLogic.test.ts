// SOLUSDEV-235 — pure catalog rules.
import { describe, it, expect } from 'vitest'
import {
  availabilityOf,
  buildView,
  connectedKinds,
  DEFAULT_INSTALL_STATE,
  initialInstallState,
  installsLabel,
  missingRequirements,
  partitionViews,
  requirementLabel,
  validateCatalog
} from './extensionLogic'
import type { ExtensionManifest } from './extension.types'

function manifest(over: Partial<ExtensionManifest> = {}): ExtensionManifest {
  return {
    id: 'ext',
    name: 'Ext',
    publisher: 'solus',
    summary: 'Does a thing.',
    icon: 'wave',
    version: '1.0.0',
    updatedAt: '2026-08-01T00:00:00Z',
    installs: null,
    requires: [],
    contributions: [],
    permissions: [],
    credits: { thisCycle: 0, perRun: null },
    links: {},
    defaultInstalled: false,
    ...over
  }
}

describe('connectedKinds', () => {
  it('maps API source types onto requirement kinds and ignores unknown types', () => {
    const kinds = connectedKinds(['github', 'kicad', 'onshape', 'ros', 'mystery'])
    expect([...kinds].sort()).toEqual(['cad', 'code', 'eda', 'runtime'])
  })

  it('collapses several sources of one kind', () => {
    expect(connectedKinds(['kicad', 'altium']).size).toBe(1)
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

describe('availability + views', () => {
  it('installed wins regardless of requirements', () => {
    expect(availabilityOf({ ...DEFAULT_INSTALL_STATE, installed: true }, [['eda']])).toBe(
      'installed'
    )
  })

  it('an uninstalled extension is blocked by unmet requirements, otherwise available', () => {
    expect(availabilityOf(DEFAULT_INSTALL_STATE, [['eda']])).toBe('needs_source')
    expect(availabilityOf(DEFAULT_INSTALL_STATE, [])).toBe('available')
  })

  it('bundled extensions start installed and enabled', () => {
    expect(initialInstallState(manifest({ defaultInstalled: true }))).toEqual({
      installed: true,
      enabled: true,
      runFrequency: 'every_sync'
    })
    expect(initialInstallState(manifest()).installed).toBe(false)
  })

  it('buildView joins manifest, state and connected kinds', () => {
    const view = buildView(manifest({ requires: [['eda']] }), DEFAULT_INSTALL_STATE, new Set())
    expect(view.availability).toBe('needs_source')
    expect(view.missing).toEqual([['eda']])
  })

  it('partitionViews splits installed from the rest, keeping order', () => {
    const a = buildView(
      manifest({ id: 'a' }),
      { ...DEFAULT_INSTALL_STATE, installed: true },
      new Set()
    )
    const b = buildView(manifest({ id: 'b' }), DEFAULT_INSTALL_STATE, new Set())
    const c = buildView(
      manifest({ id: 'c' }),
      { ...DEFAULT_INSTALL_STATE, installed: true },
      new Set()
    )
    const { installed, popular } = partitionViews([a, b, c])
    expect(installed.map((v) => v.manifest.id)).toEqual(['a', 'c'])
    expect(popular.map((v) => v.manifest.id)).toEqual(['b'])
  })
})

describe('installsLabel', () => {
  it('renders an honest dash until the catalog reports a count', () => {
    expect(installsLabel(null)).toBe('— installs')
    expect(installsLabel(1200)).toBe('1,200 installs')
  })
})

describe('validateCatalog', () => {
  it('accepts a well-formed catalog', () => {
    expect(validateCatalog([manifest({ id: 'a' }), manifest({ id: 'b' })])).toEqual([])
  })

  it('names duplicate ids, bad slugs, empty copy and empty requirement groups', () => {
    const problems = validateCatalog([
      manifest({ id: 'Bad Id' }),
      manifest({ id: 'a' }),
      manifest({ id: 'a', summary: ' ' }),
      manifest({ id: 'c', requires: [[]] })
    ])
    expect(problems).toEqual([
      'Bad Id: id must be a lowercase slug',
      'a: duplicate id',
      'a: summary is empty',
      'c: empty requirement group'
    ])
  })
})
