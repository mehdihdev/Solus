// Tests for the live integration catalog (SOLUSDEV-100, design review Q1=B):
// the tile list is driven by GET /integrations so new backend connectors appear
// without frontend edits (the drift that left Altium invisible), degrading to
// the curated static list when the API is unreachable (dev bypass / offline).
import { describe, it, expect, vi } from 'vitest'
import type { Integration as ApiIntegration } from '../../lib/api/resources'
import { loadIntegrationCatalog, FALLBACK_CATALOG } from './integrationCatalog'

const LIVE: ApiIntegration[] = [
  { type: 'altium', auth_kind: 'none', config_fields: ['export'], scopes: [] },
  { type: 'github', auth_kind: 'oauth', config_fields: ['repo'], scopes: ['repo'] },
  { type: 'gitlab', auth_kind: 'oauth', config_fields: ['repo'], scopes: ['read_api'] },
  { type: 'kicad', auth_kind: 'none', config_fields: ['export'], scopes: [] }
]

describe('loadIntegrationCatalog', () => {
  it('marks live committed-export providers as export-file connectable', async () => {
    const catalog = await loadIntegrationCatalog(vi.fn(async () => LIVE))
    const byId = new Map(catalog.map((e) => [e.id, e]))
    expect(byId.get('kicad')?.mode).toBe('export-file')
    expect(byId.get('github')?.mode).toBe('github-oauth')
  })

  it('keeps curated roster members not yet backend-registered as simulated tiles', async () => {
    const catalog = await loadIntegrationCatalog(vi.fn(async () => LIVE))
    const byId = new Map(catalog.map((e) => [e.id, e]))
    expect(byId.get('onshape')?.mode).toBe('simulated')
    expect(byId.get('ros')?.mode).toBe('simulated')
  })

  it('appends non-curated live export connectors (altium) with display metadata', async () => {
    const catalog = await loadIntegrationCatalog(vi.fn(async () => LIVE))
    const altium = catalog.find((e) => e.id === 'altium')
    expect(altium?.mode).toBe('export-file')
    expect(altium?.name).toBe('Altium')
    // Curated order first; live extras after.
    expect(catalog.findIndex((e) => e.id === 'altium')).toBeGreaterThan(
      catalog.findIndex((e) => e.id === 'ros')
    )
  })

  it('hides live providers the app cannot drive yet (gitlab oauth has no bridge flow)', async () => {
    const catalog = await loadIntegrationCatalog(vi.fn(async () => LIVE))
    expect(catalog.find((e) => e.id === 'gitlab')).toBeUndefined()
  })

  it('falls back to the curated static catalog when the API is unreachable', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => {
        throw new Error('offline')
      })
    )
    expect(catalog).toEqual(FALLBACK_CATALOG)
    expect(catalog.map((e) => e.id)).toEqual(['github', 'kicad', 'onshape', 'ros'])
  })

  it('fallback keeps github and kicad optimistically connectable (guards decide at click time)', () => {
    const byId = new Map(FALLBACK_CATALOG.map((e) => [e.id, e]))
    expect(byId.get('github')?.mode).toBe('github-oauth')
    expect(byId.get('kicad')?.mode).toBe('export-file')
    expect(byId.get('onshape')?.mode).toBe('simulated')
  })
})
