// Tests for the live integration catalog (SOLUSDEV-100, de-simulated in
// SOLUSDEV-152): the tile list is driven by GET /integrations (and, for
// local-bridge tools, GET /integrations/local-tools — SOLUSDEV-72) so only
// connectors the backend actually registers — and the app can actually drive —
// are offered. No tile ever fakes a connect.
import { describe, it, expect, vi } from 'vitest'
import type { Integration as ApiIntegration, LocalTool } from '../../lib/api/resources'
import { loadIntegrationCatalog, FALLBACK_CATALOG } from './integrationCatalog'

/** Explicit empty local-tools fetch so these tests never touch the network. */
const NO_TOOLS = async (): Promise<LocalTool[]> => []

const LIVE: ApiIntegration[] = [
  { type: 'altium', auth_kind: 'none', config_fields: ['export'], scopes: [] },
  { type: 'github', auth_kind: 'oauth', config_fields: ['repo', 'branch'], scopes: ['repo'] },
  { type: 'gitlab', auth_kind: 'oauth', config_fields: ['repo', 'branch'], scopes: ['read_api'] },
  { type: 'kicad', auth_kind: 'none', config_fields: ['export'], scopes: [] },
  {
    type: 'onshape',
    auth_kind: 'oauth',
    config_fields: ['document_id', 'workspace_id', 'element_id'],
    scopes: ['OAuth2Read', 'OAuth2Write']
  }
]

const FUSION_TOOL: LocalTool = {
  type: 'fusion',
  display_name: 'Fusion',
  hosting: 'vendor-run',
  url_host: '127.0.0.1:27182',
  connect_notice: 'Launch Fusion and enable Preferences → General → API → Fusion MCP Server',
  requires: 'companion'
}

describe('loadIntegrationCatalog', () => {
  registerLiveCatalogCapabilitiesTests()

  registerCatalogFallbacksTests()
})

describe('loadIntegrationCatalog — local-bridge tiles (SOLUSDEV-72)', () => {
  // The acceptance bar: the NEXT local tool must need zero frontend edits.
  it('derives a REAL local-bridge tile from the live local-tools registry', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => LIVE),
      vi.fn(async () => [FUSION_TOOL])
    )
    const fusion = catalog.find((e) => e.id === 'fusion')
    expect(fusion?.mode).toBe('local-bridge')
    expect(fusion?.name).toBe('Fusion')
    // The registry entry rides along so the connect action can show its
    // guidance without a per-tool lookup.
    expect(fusion?.localTool).toEqual(FUSION_TOOL)
  })

  it('a tool the frontend has never heard of still gets a tile', async () => {
    const next: LocalTool = { ...FUSION_TOOL, type: 'blender', display_name: 'Blender' }
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => LIVE),
      vi.fn(async () => [next])
    )
    expect(catalog.find((e) => e.id === 'blender')?.mode).toBe('local-bridge')
    expect(catalog.find((e) => e.id === 'blender')?.name).toBe('Blender')
  })

  it('never duplicates a provider that already has a drivable tile', async () => {
    const githubTool: LocalTool = { ...FUSION_TOOL, type: 'github', display_name: 'GitHub' }
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => LIVE),
      vi.fn(async () => [githubTool])
    )
    const github = catalog.filter((e) => e.id === 'github')
    expect(github).toHaveLength(1)
    expect(github[0].mode).toBe('oauth')
  })

  it('a failing local-tools fetch degrades to no bridge tiles, not an error', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => LIVE),
      vi.fn(async () => {
        throw new Error('offline')
      })
    )
    expect(catalog.find((e) => e.mode === 'local-bridge')).toBeUndefined()
    expect(catalog.find((e) => e.id === 'github')?.mode).toBe('oauth')
  })
})

function registerLiveCatalogCapabilitiesTests(): void {
  it('marks live committed-export providers as export-file connectable', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => LIVE),
      NO_TOOLS
    )
    const byId = new Map(catalog.map((e) => [e.id, e]))
    expect(byId.get('kicad')?.mode).toBe('export-file')
    expect(byId.get('github')?.mode).toBe('oauth')
  })

  it('offers every live OAuth provider, not just github', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => LIVE),
      NO_TOOLS
    )
    const byId = new Map(catalog.map((e) => [e.id, e]))
    expect(byId.get('gitlab')?.mode).toBe('oauth')
    expect(byId.get('onshape')?.mode).toBe('oauth')
    expect(byId.get('onshape')?.name).toBe('Onshape')
  })

  // The acceptance bar: the NEXT OAuth connector must need no frontend edit.
  it('offers an OAuth provider the frontend has never heard of', async () => {
    const withFuture: ApiIntegration[] = [
      ...LIVE,
      { type: 'fusion', auth_kind: 'oauth', config_fields: ['hub_id', 'project_id'], scopes: [] }
    ]
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => withFuture),
      NO_TOOLS
    )
    const fusion = catalog.find((e) => e.id === 'fusion')
    expect(fusion?.mode).toBe('oauth')
    // No display copy exists for it yet, so it gets the generic tile — but it
    // is still connectable, which is the point.
    expect(fusion?.name).toBe('Fusion')
    expect(fusion?.configFields).toEqual(['hub_id', 'project_id'])
  })

  it('carries the live config fields so the configure step can be chosen', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => LIVE),
      NO_TOOLS
    )
    const byId = new Map(catalog.map((e) => [e.id, e]))
    expect(byId.get('github')?.configFields).toEqual(['repo', 'branch'])
    expect(byId.get('onshape')?.configFields).toEqual(['document_id', 'workspace_id', 'element_id'])
  })

  it('still hides providers the app cannot drive (unregistered ros, token-only auth)', async () => {
    // The hiding rule stays: a tile is only offered when a REAL connect flow
    // exists. `ros` is not registered at all; a token-auth connector has no
    // drivable flow in the app yet.
    const withToken: ApiIntegration[] = [
      ...LIVE,
      { type: 'jira', auth_kind: 'token', config_fields: ['board'], scopes: [] }
    ]
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => withToken),
      NO_TOOLS
    )
    expect(catalog.find((e) => e.id === 'ros')).toBeUndefined()
    expect(catalog.find((e) => e.id === 'jira')).toBeUndefined()
  })
}

function registerCatalogFallbacksTests(): void {
  it('drops a curated provider the live registry no longer carries', async () => {
    const withoutKicad = LIVE.filter((integration) => integration.type !== 'kicad')
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => withoutKicad),
      NO_TOOLS
    )
    expect(catalog.find((e) => e.id === 'kicad')).toBeUndefined()
    expect(catalog.find((e) => e.id === 'github')?.mode).toBe('oauth')
  })

  it('appends non-curated live connectors with display metadata', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => LIVE),
      NO_TOOLS
    )
    const altium = catalog.find((e) => e.id === 'altium')
    expect(altium?.mode).toBe('export-file')
    expect(altium?.name).toBe('Altium')
    // Curated order first; live extras after.
    expect(catalog.findIndex((e) => e.id === 'altium')).toBeGreaterThan(
      catalog.findIndex((e) => e.id === 'kicad')
    )
  })

  it('falls back to the drivable curated catalog when the API is unreachable', async () => {
    const catalog = await loadIntegrationCatalog(
      vi.fn(async () => {
        throw new Error('offline')
      }),
      NO_TOOLS
    )
    expect(catalog).toEqual(FALLBACK_CATALOG)
    expect(catalog.map((e) => e.id)).toEqual(['github', 'kicad'])
  })

  it('fallback keeps github and kicad optimistically connectable (guards decide at click time)', () => {
    const byId = new Map(FALLBACK_CATALOG.map((e) => [e.id, e]))
    expect(byId.get('github')?.mode).toBe('oauth')
    expect(byId.get('github')?.configFields).toEqual(['repo', 'branch'])
    expect(byId.get('kicad')?.mode).toBe('export-file')
  })
}
