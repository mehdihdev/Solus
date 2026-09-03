// SOLUSDEV-235 / EXT-12 — the install+policy snapshot check every call passes
// first (extensions-runtime.md §6.8; dev refusals §10).
import { describe, it, expect } from 'vitest'
import type { ExtensionInstallApi } from '../../../lib/api/resources.extensions'
import { authorize, policyFromInstall, type BridgePolicy } from './policySnapshot'

const base: BridgePolicy = {
  extensionId: 'bom',
  version: '1.2.0',
  projectId: 'p1',
  grantedScopes: ['graph.read', 'storage.own'],
  grantedNetwork: ['https://api.octopart.com'],
  enabled: true,
  blocked: false,
  mode: 'widget'
}

describe('authorize', () => {
  it('allows a granted scoped method and every unscoped method', () => {
    expect(authorize(base, 'graph.getEntity')).toBeNull()
    expect(authorize(base, 'ui.ready')).toBeNull()
    expect(authorize(base, 'settings.get')).toBeNull()
    expect(authorize(base, 'net.fetch')).toBeNull()
  })

  it('refuses an unknown method', () => {
    expect(authorize(base, 'graph.delete')).toBe('unknown_method')
    expect(authorize(base, '')).toBe('unknown_method')
  })

  it('refuses a method whose scope was not granted', () => {
    expect(authorize(base, 'sol.ask')).toBe('scope_denied')
    expect(authorize(base, 'telemetry.subscribe')).toBe('scope_denied')
  })

  it('blocked wins over everything, including unknown methods and ui.ready', () => {
    const blocked = { ...base, blocked: true }
    expect(authorize(blocked, 'graph.getEntity')).toBe('blocked')
    expect(authorize(blocked, 'nope')).toBe('blocked')
    expect(authorize(blocked, 'ui.ready')).toBe('blocked')
  })

  it('disabled in this project is blocked too', () => {
    expect(authorize({ ...base, enabled: false }, 'graph.getEntity')).toBe('blocked')
  })

  it('dev mode refuses server-attributed methods with blocked, even when granted', () => {
    const dev = {
      ...base,
      mode: 'dev' as const,
      grantedScopes: ['sol.ask', 'storage.own', 'findings.write', 'graph.read'] as const
    }
    expect(authorize(dev, 'sol.ask')).toBe('blocked')
    expect(authorize(dev, 'storage.get')).toBe('blocked')
    expect(authorize(dev, 'storage.set')).toBe('blocked')
    expect(authorize(dev, 'findings.create')).toBe('blocked')
    expect(authorize(dev, 'graph.getEntity')).toBeNull()
  })
})

describe('policyFromInstall', () => {
  const install = {
    extension: { slug: 'bom', name: 'BOM', verified: true, publisher: { display_name: 'Solus' } },
    version: { version: '1.2.0', manifest: {} },
    enabled: true,
    granted_scopes: ['graph.read'],
    granted_network: ['https://api.octopart.com'],
    policy: { blocked: false, default_installed: true }
  } as unknown as ExtensionInstallApi

  it('projects the §6.1 row into a policy for the mounted project', () => {
    expect(policyFromInstall(install, 'p1', 'page')).toEqual({
      extensionId: 'bom',
      version: '1.2.0',
      projectId: 'p1',
      grantedScopes: ['graph.read'],
      grantedNetwork: ['https://api.octopart.com'],
      enabled: true,
      blocked: false,
      mode: 'page'
    })
  })

  it('a team block reads as blocked regardless of the stored enabled flag', () => {
    const blocked = { ...install, policy: { blocked: true, default_installed: false } }
    expect(policyFromInstall(blocked, 'p1', 'widget')).toMatchObject({
      blocked: true,
      enabled: false
    })
  })
})
