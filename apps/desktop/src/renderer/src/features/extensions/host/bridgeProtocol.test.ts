// SOLUSDEV-235 / EXT-12 — wire-shape parsing (extensions-runtime.md §6.1, §6.5).
import { describe, it, expect } from 'vitest'
import { PERMISSION_SCOPES } from '@solus/shared-types'
import {
  BRIDGE_LIMITS,
  METHOD_SCOPES,
  REFUSAL_CODES,
  SERVER_ATTRIBUTED_METHODS,
  isKnownMethod,
  parseBridgeRequest
} from './bridgeProtocol'

const valid = { v: 1, id: 'req-1', method: 'graph.getFocus', params: {} }

describe('parseBridgeRequest', () => {
  it('accepts a well-formed v1 request and rebuilds it as a fresh literal', () => {
    const parsed = parseBridgeRequest({ ...valid, extra: 'ignored' })
    expect(parsed).toEqual(valid)
    expect(parsed).not.toHaveProperty('extra')
  })

  it.each([
    ['wrong version', { ...valid, v: 2 }],
    ['string version', { ...valid, v: '1' }],
    ['missing id', { v: 1, method: 'x', params: {} }],
    ['empty id', { ...valid, id: '' }],
    ['oversized id', { ...valid, id: 'a'.repeat(BRIDGE_LIMITS.idLength + 1) }],
    ['id with forbidden chars', { ...valid, id: 'a b' }],
    ['non-string method', { ...valid, method: 42 }],
    ['array params', { ...valid, params: [] }],
    ['null params', { ...valid, params: null }],
    ['missing params', { v: 1, id: 'x', method: 'm' }],
    ['not an object', 'hello'],
    ['null', null],
    ['array', [valid]]
  ])('drops %s', (_label, data) => {
    expect(parseBridgeRequest(data)).toBeNull()
  })

  it('accepts an id at exactly the cap', () => {
    expect(parseBridgeRequest({ ...valid, id: 'a'.repeat(BRIDGE_LIMITS.idLength) })).not.toBeNull()
  })

  it('drops a message whose serialized form exceeds 64 KiB', () => {
    const big = { ...valid, params: { q: 'x'.repeat(BRIDGE_LIMITS.messageBytes) } }
    expect(parseBridgeRequest(big)).toBeNull()
  })

  it('measures bytes, not characters', () => {
    // 30k four-byte code points → 120 KB even though only 60k UTF-16 units.
    const big = { ...valid, params: { q: '😀'.repeat(30_000) } }
    expect(parseBridgeRequest(big)).toBeNull()
  })

  it('drops an unserializable message instead of throwing', () => {
    const cyclic: Record<string, unknown> = { ...valid }
    cyclic.params = { self: cyclic }
    expect(parseBridgeRequest(cyclic)).toBeNull()
  })
})

describe('METHOD_SCOPES', () => {
  it('is the closed §6.3 table', () => {
    expect(Object.keys(METHOD_SCOPES).sort()).toEqual(
      [
        'ui.ready',
        'settings.get',
        'ui.openExternal',
        'graph.getFocus',
        'graph.getEntity',
        'graph.getNeighborhood',
        'graph.search',
        'telemetry.subscribe',
        'telemetry.unsubscribe',
        'sources.list',
        'findings.create',
        'sol.ask',
        'storage.get',
        'storage.set',
        'storage.delete',
        'focus.get',
        'focus.propose',
        'net.fetch'
      ].sort()
    )
  })

  it('names only contract scopes (or null for the unscoped methods)', () => {
    for (const scope of Object.values(METHOD_SCOPES)) {
      if (scope !== null) expect(PERMISSION_SCOPES).toContain(scope)
    }
    expect(METHOD_SCOPES['ui.ready']).toBeNull()
    expect(METHOD_SCOPES['net.fetch']).toBeNull()
    expect(METHOD_SCOPES['storage.set']).toBe('storage.own')
  })

  it('isKnownMethod is a type guard over the table', () => {
    expect(isKnownMethod('graph.search')).toBe(true)
    expect(isKnownMethod('graph.delete')).toBe(false)
    expect(isKnownMethod('__proto__')).toBe(false)
    expect(isKnownMethod('constructor')).toBe(false)
  })

  it('the server-attributed set is exactly sol.ask, findings.create and storage.*', () => {
    expect([...SERVER_ATTRIBUTED_METHODS].sort()).toEqual([
      'findings.create',
      'sol.ask',
      'storage.delete',
      'storage.get',
      'storage.set'
    ])
  })

  it('refusal codes are the seven §6.4 names that emit a data event', () => {
    expect([...REFUSAL_CODES].sort()).toEqual([
      'blocked',
      'invalid_params',
      'network_denied',
      'rate_limited',
      'scope_denied',
      'storage_quota',
      'unknown_method'
    ])
  })
})
