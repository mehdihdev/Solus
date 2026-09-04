// SOLUSDEV-235 / EXT-12 — §6.3 param caps; a project/team id anywhere is invalid.
import { describe, it, expect } from 'vitest'
import { BRIDGE_LIMITS } from './bridgeProtocol'
import { validateParams } from './paramsSchema'

describe('validateParams', () => {
  describe('empty-param methods', () => {
    it.each(['ui.ready', 'settings.get', 'graph.getFocus', 'sources.list', 'focus.get'] as const)(
      '%s accepts {} and rejects any key',
      (method) => {
        expect(validateParams(method, {})).toEqual({})
        expect(validateParams(method, { anything: 1 })).toBeNull()
      }
    )
  })

  it('rejects a project or team id on every method, even where other keys are valid', () => {
    expect(validateParams('graph.getEntity', { entityId: 'e1', projectId: 'p2' })).toBeNull()
    expect(validateParams('graph.getEntity', { entityId: 'e1', project_id: 'p2' })).toBeNull()
    expect(validateParams('storage.get', { key: 'k', teamId: 't' })).toBeNull()
    expect(validateParams('sol.ask', { prompt: 'hi', team_id: 't' })).toBeNull()
  })

  it('rejects unknown keys (no passthrough)', () => {
    expect(validateParams('graph.getEntity', { entityId: 'e1', extra: true })).toBeNull()
  })

  it('returns a fresh literal with only declared keys', () => {
    const input = { entityId: 'e1' }
    const out = validateParams('graph.getEntity', input)
    expect(out).toEqual({ entityId: 'e1' })
    expect(out).not.toBe(input)
  })

  describe('graph', () => {
    it('getNeighborhood defaults depth 1 / limit 200 and caps both', () => {
      expect(validateParams('graph.getNeighborhood', { entityId: 'e' })).toEqual({
        entityId: 'e',
        depth: 1,
        limit: 200
      })
      expect(
        validateParams('graph.getNeighborhood', { entityId: 'e', depth: 2, limit: 5 })
      ).toEqual({ entityId: 'e', depth: 2, limit: 5 })
      expect(validateParams('graph.getNeighborhood', { entityId: 'e', depth: 3 })).toBeNull()
      expect(validateParams('graph.getNeighborhood', { entityId: 'e', limit: 201 })).toBeNull()
      expect(validateParams('graph.getNeighborhood', { entityId: 'e', depth: 1.5 })).toBeNull()
      expect(validateParams('graph.getNeighborhood', { entityId: 'e', limit: 0 })).toBeNull()
    })

    it('search caps q at 200 chars and limit at 50; types is optional', () => {
      expect(validateParams('graph.search', { q: 'motor' })).toEqual({
        q: 'motor',
        types: [],
        limit: 50
      })
      expect(validateParams('graph.search', { q: 'x'.repeat(201) })).toBeNull()
      expect(validateParams('graph.search', { q: '' })).toBeNull()
      expect(validateParams('graph.search', { q: 'm', limit: 51 })).toBeNull()
      expect(validateParams('graph.search', { q: 'm', types: ['ic', 42] })).toBeNull()
      expect(validateParams('graph.search', { q: 'm', types: ['ic'], limit: 3 })).toEqual({
        q: 'm',
        types: ['ic'],
        limit: 3
      })
    })
  })

  describe('telemetry', () => {
    it('subscribe requires 1–32 signal ids', () => {
      expect(validateParams('telemetry.subscribe', { signalIds: ['a'] })).toEqual({
        signalIds: ['a']
      })
      expect(validateParams('telemetry.subscribe', { signalIds: [] })).toBeNull()
      expect(validateParams('telemetry.subscribe', {})).toBeNull()
      expect(validateParams('telemetry.subscribe', { signalIds: Array(33).fill('s') })).toBeNull()
    })

    it('unsubscribe needs a subscription id', () => {
      expect(validateParams('telemetry.unsubscribe', { subscriptionId: 's1' })).toEqual({
        subscriptionId: 's1'
      })
      expect(validateParams('telemetry.unsubscribe', {})).toBeNull()
    })
  })

  describe('findings.create', () => {
    const ok = { title: 'T', body: 'B', severity: 'warning' }

    it('accepts the contract severities and defaults entityIds to []', () => {
      expect(validateParams('findings.create', ok)).toEqual({ ...ok, entityIds: [] })
    })

    it('caps title 120, body 4 KiB (bytes), entityIds 16, and rejects unknown severity', () => {
      expect(validateParams('findings.create', { ...ok, title: 'x'.repeat(121) })).toBeNull()
      expect(validateParams('findings.create', { ...ok, body: 'x'.repeat(4097) })).toBeNull()
      // 2049 two-byte chars = 4098 bytes, only 2049 chars.
      expect(validateParams('findings.create', { ...ok, body: 'é'.repeat(2049) })).toBeNull()
      expect(validateParams('findings.create', { ...ok, severity: 'fatal' })).toBeNull()
      expect(
        validateParams('findings.create', { ...ok, entityIds: Array(17).fill('e') })
      ).toBeNull()
    })
  })

  describe('sol.ask', () => {
    it('caps prompt at 8 KiB and entityIds at 16', () => {
      expect(validateParams('sol.ask', { prompt: 'why?' })).toEqual({
        prompt: 'why?',
        entityIds: []
      })
      expect(
        validateParams('sol.ask', { prompt: 'x'.repeat(BRIDGE_LIMITS.promptBytes) })
      ).not.toBeNull()
      expect(
        validateParams('sol.ask', { prompt: 'x'.repeat(BRIDGE_LIMITS.promptBytes + 1) })
      ).toBeNull()
      expect(validateParams('sol.ask', { prompt: '' })).toBeNull()
      expect(validateParams('sol.ask', { prompt: 'p', entityIds: Array(17).fill('e') })).toBeNull()
    })
  })

  describe('storage', () => {
    it('key follows the route plan rule ^[A-Za-z0-9_.-]{1,64}$', () => {
      expect(validateParams('storage.get', { key: 'cache.v1' })).toEqual({ key: 'cache.v1' })
      expect(validateParams('storage.get', { key: 'a'.repeat(65) })).toBeNull()
      expect(validateParams('storage.get', { key: 'a/b' })).toBeNull()
      expect(validateParams('storage.get', { key: '' })).toBeNull()
      expect(validateParams('storage.delete', { key: 'k' })).toEqual({ key: 'k' })
    })

    it('set caps value at 64 KiB (bytes) and requires a string value', () => {
      expect(validateParams('storage.set', { key: 'k', value: '' })).toEqual({
        key: 'k',
        value: ''
      })
      expect(
        validateParams('storage.set', {
          key: 'k',
          value: 'x'.repeat(BRIDGE_LIMITS.storageValueBytes)
        })
      ).not.toBeNull()
      expect(
        validateParams('storage.set', {
          key: 'k',
          value: 'x'.repeat(BRIDGE_LIMITS.storageValueBytes + 1)
        })
      ).toBeNull()
      expect(validateParams('storage.set', { key: 'k', value: { nested: true } })).toBeNull()
      expect(validateParams('storage.set', { key: 'k' })).toBeNull()
    })
  })

  describe('focus.propose', () => {
    it('requires entityId + contract domain; label/relation optional but typed', () => {
      expect(validateParams('focus.propose', { entityId: 'e', domain: 'electrical' })).toEqual({
        entityId: 'e',
        domain: 'electrical'
      })
      expect(
        validateParams('focus.propose', {
          entityId: 'e',
          domain: 'code',
          label: 'L',
          relation: 'drives'
        })
      ).toEqual({ entityId: 'e', domain: 'code', label: 'L', relation: 'drives' })
      expect(validateParams('focus.propose', { entityId: 'e', domain: 'plasma' })).toBeNull()
      expect(
        validateParams('focus.propose', { entityId: 'e', domain: 'code', label: 42 })
      ).toBeNull()
      expect(
        validateParams('focus.propose', { entityId: 'e', domain: 'code', relation: '' })
      ).toBeNull()
    })
  })

  describe('ui.openExternal', () => {
    it('accepts only https URLs', () => {
      expect(validateParams('ui.openExternal', { url: 'https://example.com/x' })).toEqual({
        url: 'https://example.com/x'
      })
      expect(validateParams('ui.openExternal', { url: 'http://example.com' })).toBeNull()
      expect(validateParams('ui.openExternal', { url: 'javascript:alert(1)' })).toBeNull()
      expect(validateParams('ui.openExternal', { url: 'file:///etc/passwd' })).toBeNull()
      expect(validateParams('ui.openExternal', { url: 'not a url' })).toBeNull()
    })
  })

  describe('net.fetch', () => {
    it('defaults method GET and headers {}; caps body at 1 MiB', () => {
      expect(validateParams('net.fetch', { url: 'https://api.octopart.com/v1' })).toEqual({
        url: 'https://api.octopart.com/v1',
        method: 'GET',
        headers: {}
      })
      const big = 'x'.repeat(BRIDGE_LIMITS.netBodyBytes + 1)
      expect(
        validateParams('net.fetch', { url: 'https://a.b', method: 'POST', body: big })
      ).toBeNull()
      expect(
        validateParams('net.fetch', { url: 'https://a.b', method: 'POST', body: 'ok' })
      ).toEqual({ url: 'https://a.b', method: 'POST', headers: {}, body: 'ok' })
    })

    it('leaves the https rule to the handler (network_denied), rejects garbage URLs', () => {
      expect(validateParams('net.fetch', { url: 'http://a.b' })).not.toBeNull()
      expect(validateParams('net.fetch', { url: 'not a url' })).toBeNull()
      expect(validateParams('net.fetch', { url: 42 })).toBeNull()
    })

    it('rejects unknown methods and forbidden headers', () => {
      expect(validateParams('net.fetch', { url: 'https://a.b', method: 'PATCH' })).toBeNull()
      expect(
        validateParams('net.fetch', { url: 'https://a.b', headers: { Cookie: 'x' } })
      ).toBeNull()
      expect(
        validateParams('net.fetch', { url: 'https://a.b', headers: { authorization: 'x' } })
      ).toBeNull()
      expect(
        validateParams('net.fetch', { url: 'https://a.b', headers: { Referer: 'x' } })
      ).toBeNull()
      expect(
        validateParams('net.fetch', { url: 'https://a.b', headers: { 'X-Api-Key': 1 } })
      ).toBeNull()
      expect(validateParams('net.fetch', { url: 'https://a.b', headers: ['a'] })).toBeNull()
      expect(
        validateParams('net.fetch', { url: 'https://a.b', headers: { 'X-Api-Key': 'k' } })
      ).toEqual({ url: 'https://a.b', method: 'GET', headers: { 'X-Api-Key': 'k' } })
    })
  })
})
