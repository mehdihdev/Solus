// SOLUSDEV-235 — the in-repo catalog is build-time data; keep it honest.
import { describe, it, expect } from 'vitest'
import { EXTENSION_CATALOG } from './extensions.catalog'
import { validateCatalog } from './extensionLogic'
import { Icons } from '../../components/ui/icons.constants'

describe('EXTENSION_CATALOG', () => {
  it('passes catalog validation', () => {
    expect(validateCatalog(EXTENSION_CATALOG)).toEqual([])
  })

  it('names only icons the icon set actually ships', () => {
    for (const m of EXTENSION_CATALOG) expect(Icons[m.icon]).toBeDefined()
  })

  it('never fabricates an install count (SOLUSDEV-152)', () => {
    for (const m of EXTENSION_CATALOG) expect(m.installs).toBeNull()
  })

  it('ships the core capabilities installed and the source-gated ones not', () => {
    const byId = new Map(EXTENSION_CATALOG.map((m) => [m.id, m]))
    for (const id of ['live-signals', 'scene', 'experiments', 'cross-domain-findings'])
      expect(byId.get(id)?.defaultInstalled).toBe(true)
    for (const id of ['bom', 'can-telemetry', 'datasheet-finder', 'fsae-rules-checker'])
      expect(byId.get(id)?.defaultInstalled).toBe(false)
  })

  it('every entry links documentation and an issue tracker', () => {
    for (const m of EXTENSION_CATALOG) {
      expect(m.links.documentation).toMatch(/^https:\/\//)
      expect(m.links.issues).toMatch(/^https:\/\//)
    }
  })
})
