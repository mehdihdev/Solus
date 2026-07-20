// Tests for the live integration catalog (SOLUSDEV-100, de-simulated in
// SOLUSDEV-152): the tile list is driven by GET /integrations so only
// connectors the backend actually registers — and the app can actually drive —
// are offered. No tile ever fakes a connect.
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

  it('never lists providers the backend does not register (onshape, ros)', async () => {
    const catalog = await loadIntegrationCatalog(vi.fn(async () => LIVE))
    expect(catalog.find((e) => e.id === 'onshape')).toBeUndefined()
    expect(catalog.find((e) => e.id === 'ros')).toBeUndefined()
  })

  it('drops a curated provider the live registry no longer carries', async () => {
    const withoutKicad = LIVE.filter((integration) => integration.type !== 'kicad')
    const catalog = await loadIntegrationCatalog(vi.fn(async () => withoutKicad))
    expect(catalog.find((e) => e.id === 'kicad')).toBeUndefined()
    expect(catalog.find((e) => e.id === 'github')?.mode).toBe('github-oauth')
  })

  it('appends non-curated live export connectors (altium) with display metadata', async () => {
    const catalog = await loadIntegrationCatalog(vi.fn(async () => LIVE))
    const altium = catalog.find((e) => e.id === 'altium')
    expect(altium?.mode).toBe('export-file')
    expect(altium?.name).toBe('Altium')
    // Curated order first; live extras after.
    expect(catalog.findIndex((e) => e.id === 'altium')).toBeGreaterThan(
      catalog.findIndex((e) => e.id === 'kicad')
    )
  })

  it('hides live providers the app cannot drive yet (gitlab oauth has no bridge flow)', async () => {
    const catalog = await loadIntegrationCatalog(vi.fn(async () => LIVE))
    expect(catalog.find((e) => e.id === 'gitlab')).toBeUndefined()
  })

  it('falls back to the drivable curated catalog when the API is unreachable', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => {
        throw new Error('offline')
      })
    )
    expect(catalog).toEqual(FALLBACK_CATALOG)
    expect(catalog.map((e) => e.id)).toEqual(['github', 'kicad'])
  })

  it('fallback keeps github and kicad optimistically connectable (guards decide at click time)', () => {
    const byId = new Map(FALLBACK_CATALOG.map((e) => [e.id, e]))
    expect(byId.get('github')?.mode).toBe('github-oauth')
    expect(byId.get('kicad')?.mode).toBe('export-file')
  })
})
