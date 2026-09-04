// SOLUSDEV-235 / SEC-C1 — the ONE origin-allowlist predicate `net.fetch` and
// `ui.openExternal` share, plus the exact-URL store-link escape hatch.
import { describe, it, expect } from 'vitest'
import { isGrantedOrigin, isStoreLink } from './originAllow'
import type { BridgePolicy } from './policySnapshot'

const policy: BridgePolicy = {
  extensionId: 'bom',
  version: '1.2.0',
  projectId: 'p1',
  grantedScopes: [],
  grantedNetwork: ['https://api.octopart.com'],
  storeLinks: ['https://docs.example.com/bom', 'https://github.com/acme/bom/issues'],
  enabled: true,
  blocked: false,
  mode: 'widget'
}

describe('isGrantedOrigin', () => {
  it('accepts an https URL whose origin is granted', () => {
    expect(isGrantedOrigin(policy, 'https://api.octopart.com/v4/parts?q=x')).toBe(true)
  })

  it.each([
    ['http on a granted host', 'http://api.octopart.com/x'],
    ['a suffix-spoofed host', 'https://api.octopart.com.evil.io/'],
    ['a different port', 'https://api.octopart.com:8443/'],
    ['an ungranted host', 'https://169.254.169.254/latest'],
    ['garbage', 'not a url'],
    ['a store link (not an origin grant)', 'https://docs.example.com/bom']
  ])('refuses %s', (_why, url) => {
    expect(isGrantedOrigin(policy, url)).toBe(false)
  })

  it('an empty grant list admits nothing', () => {
    expect(isGrantedOrigin({ ...policy, grantedNetwork: [] }, 'https://api.octopart.com/')).toBe(
      false
    )
  })
})

describe('isStoreLink', () => {
  it('matches only the exact manifest store.links values', () => {
    expect(isStoreLink(policy, 'https://docs.example.com/bom')).toBe(true)
    expect(isStoreLink(policy, 'https://docs.example.com/bom/')).toBe(false)
    expect(isStoreLink(policy, 'https://docs.example.com/')).toBe(false)
  })

  it('a policy without store links matches nothing', () => {
    const bare = { grantedNetwork: policy.grantedNetwork }
    expect(isStoreLink(bare, 'https://docs.example.com/bom')).toBe(false)
  })
})
