// SOLUSDEV-235 / EXT-12 — the BridgeHost pipeline (extensions-runtime.md §6):
// drop → authorize → duplicate id → rate limit → schema → handler → one response.
// Includes the hostile-frame cases the §9 checklist names (projectId params,
// oversized messages, private-range / non-https net.fetch, cross-project focus).
import { describe, it, expect, vi } from 'vitest'
import { ApiError } from '../../../lib/api/envelope.types'
import { createBridgeHost, type BridgeHost, type BridgeHostOptions } from './bridgeHost'
import { BRIDGE_LIMITS, type BridgeOutbound, type BridgeResponse } from './bridgeProtocol'
import type { BridgePolicy } from './policySnapshot'
import { createOpenExternalLimiter, createRateLimiter } from './rateLimiter'
import { fakeBridgeDeps, type FakeBridgeDeps } from './testing/fakeBridgeDeps'
import type { RegistryTimers } from './handlers/telemetryRegistry'

const FRAME_WINDOW = { tag: 'this frame' }
const OTHER_WINDOW = { tag: 'someone else' }
const TOKEN = 'tok-secret-9f2c'

const BASE: BridgePolicy = {
  extensionId: 'bom',
  version: '1.2.0',
  projectId: 'p1',
  grantedScopes: ['graph.read', 'storage.own', 'focus.read', 'focus.write', 'telemetry.read'],
  grantedNetwork: ['https://api.octopart.com'],
  enabled: true,
  blocked: false,
  mode: 'widget'
}

interface Harness {
  host: BridgeHost
  posted: BridgeOutbound[]
  deps: FakeBridgeDeps
  /** Send one frame request and resolve to the host's reply (or undefined if dropped). */
  call(method: string, params?: unknown, id?: string): Promise<BridgeResponse | undefined>
  raw(data: unknown, source?: unknown): Promise<void>
  timers: RegistryTimers & { fire(): void }
}

function manualTimers(): Harness['timers'] {
  const queue: (() => void)[] = []
  return {
    setTimeout: (fn) => (queue.push(fn), fn),
    clearTimeout: (h) => {
      const i = queue.indexOf(h as () => void)
      if (i >= 0) queue.splice(i, 1)
    },
    fire: () => queue.splice(0).forEach((fn) => fn())
  }
}

function harness(
  policy: Partial<BridgePolicy> = {},
  extra: Partial<BridgeHostOptions> = {}
): Harness {
  const posted: BridgeOutbound[] = []
  const deps = extra.deps ? (extra.deps as FakeBridgeDeps) : fakeBridgeDeps()
  const timers = manualTimers()
  let n = 0
  const host = createBridgeHost({
    frame: { postMessage: (m) => posted.push(m), isSource: (s) => s === FRAME_WINDOW },
    policy: { ...BASE, ...policy },
    settings: { refresh: 'hourly' },
    rateLimiter: createRateLimiter({ now: () => 0 }),
    openExternalLimiter: createOpenExternalLimiter(() => 0),
    timers,
    ...extra,
    deps
  })
  const raw = (data: unknown, source: unknown = FRAME_WINDOW): Promise<void> =>
    host.handleMessage({ origin: 'null', source, data })
  return {
    host,
    posted,
    deps,
    timers,
    raw,
    async call(method, params = {}, id = `r${++n}`) {
      const before = posted.length
      await raw({ v: 1, id, method, params })
      const reply = posted.slice(before).find((m) => 'id' in m && m.id === id)
      return reply as BridgeResponse | undefined
    }
  }
}

const errorOf = (reply: BridgeResponse | undefined): string | undefined =>
  reply && !reply.ok ? reply.error.code : undefined

describe('drops (§6.5) — no response, no oracle', () => {
  it('ignores messages whose source is not the mounted frame, uncounted', async () => {
    const h = harness()
    await h.raw({ v: 1, id: 'x', method: 'ui.ready', params: {} }, OTHER_WINDOW)
    await h.raw({ v: 1, id: 'x', method: 'ui.ready', params: {} }, null)
    expect(h.posted).toEqual([])
    expect(h.host.stats().dropped).toBe(0)
  })

  it.each([
    ['wrong version', { v: 2, id: 'x', method: 'ui.ready', params: {} }],
    ['array params', { v: 1, id: 'x', method: 'ui.ready', params: [] }],
    ['missing id', { v: 1, method: 'ui.ready', params: {} }],
    ['not an object', 'ui.ready'],
    [
      'oversized',
      { v: 1, id: 'x', method: 'm', params: { p: 'x'.repeat(BRIDGE_LIMITS.messageBytes) } }
    ]
  ])('drops and counts %s from the frame', async (_label, data) => {
    const h = harness()
    await h.raw(data)
    expect(h.posted).toEqual([])
    expect(h.host.stats().dropped).toBe(1)
    expect(h.deps.emitRefusal).not.toHaveBeenCalled()
  })
})

describe('refusals (§6.4) — one error reply + a bridge_refused event', () => {
  it('unknown method', async () => {
    const h = harness()
    expect(errorOf(await h.call('graph.delete'))).toBe('unknown_method')
    expect(h.deps.emitRefusal).toHaveBeenCalledWith({
      extensionId: 'bom',
      version: '1.2.0',
      method: 'graph.delete',
      code: 'unknown_method'
    })
  })

  it('scope not granted', async () => {
    const h = harness()
    expect(errorOf(await h.call('sol.ask', { prompt: 'x' }))).toBe('scope_denied')
    expect(h.deps.sol.ask).not.toHaveBeenCalled()
    expect(h.deps.emitRefusal).toHaveBeenCalledWith(
      expect.objectContaining({ code: 'scope_denied' })
    )
  })

  it('blocked and disabled installs refuse everything with blocked', async () => {
    const blocked = harness({ blocked: true })
    expect(errorOf(await blocked.call('graph.getEntity', { entityId: 'e' }))).toBe('blocked')
    const disabled = harness({ enabled: false })
    expect(errorOf(await disabled.call('ui.ready'))).toBe('blocked')
    expect(disabled.deps.emitRefusal).toHaveBeenCalledWith(
      expect.objectContaining({ code: 'blocked' })
    )
  })

  it('dev mode refuses server-attributed methods but serves the rest', async () => {
    const h = harness({ mode: 'dev', version: 'dev', grantedScopes: ['storage.own', 'graph.read'] })
    expect(errorOf(await h.call('storage.get', { key: 'k' }))).toBe('blocked')
    expect(h.deps.storage.get).not.toHaveBeenCalled()
    const reply = await h.call('graph.getEntity', { entityId: 'e1' })
    expect(reply?.ok).toBe(true)
  })

  it('rate limit: the window cap refuses the next request and does not run it', async () => {
    const h = harness({}, { rateLimiter: createRateLimiter({ now: () => 0, maxRequests: 2 }) })
    expect((await h.call('graph.getFocus'))?.ok).toBe(true)
    expect((await h.call('graph.getFocus'))?.ok).toBe(true)
    expect(errorOf(await h.call('graph.getFocus'))).toBe('rate_limited')
    expect(h.deps.graph.focusedEntity).toHaveBeenCalledTimes(2)
    expect(h.deps.emitRefusal).toHaveBeenCalledWith(
      expect.objectContaining({ code: 'rate_limited' })
    )
  })

  it('rate limit: the in-flight cap refuses while a request is pending, then admits', async () => {
    let release: (v: unknown) => void = () => undefined
    const deps = fakeBridgeDeps()
    ;(deps.graph.getEntity as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((resolve) => (release = resolve))
    )
    const h = harness(
      {},
      { deps, rateLimiter: createRateLimiter({ now: () => 0, maxInFlight: 1 }) }
    )
    const first = h.call('graph.getEntity', { entityId: 'e' }, 'a')
    expect(errorOf(await h.call('graph.getEntity', { entityId: 'e' }, 'b'))).toBe('rate_limited')
    release({ id: 'e' })
    expect((await first)?.ok).toBe(true)
    expect((await h.call('graph.getEntity', { entityId: 'e' }, 'c'))?.ok).toBe(true)
  })

  it('a duplicate in-flight id is invalid_params', async () => {
    let release: (v: unknown) => void = () => undefined
    const deps = fakeBridgeDeps()
    ;(deps.graph.getEntity as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((resolve) => (release = resolve))
    )
    const h = harness({}, { deps })
    const first = h.call('graph.getEntity', { entityId: 'e' }, 'same')
    expect(errorOf(await h.call('graph.getFocus', {}, 'same'))).toBe('invalid_params')
    expect(h.deps.graph.focusedEntity).not.toHaveBeenCalled()
    release({ id: 'e' })
    await first
    // Both replies echo the same id; the pending one lands last and is the success.
    expect(h.posted.at(-1)).toMatchObject({ id: 'same', ok: true })
  })

  it('param caps: an oversized storage value never reaches the store', async () => {
    const h = harness()
    const value = 'x'.repeat(BRIDGE_LIMITS.storageValueBytes + 1)
    // Still under the 64 KiB message cap? No — so also assert a smaller-but-invalid case.
    await h.raw({ v: 1, id: 'big', method: 'storage.set', params: { key: 'k', value } })
    expect(h.deps.storage.set).not.toHaveBeenCalled()
    expect(errorOf(await h.call('storage.set', { key: 'bad/key', value: 'v' }))).toBe(
      'invalid_params'
    )
    expect(h.deps.storage.set).not.toHaveBeenCalled()
  })

  it('a projectId in params is invalid_params; the host project is used regardless', async () => {
    const h = harness()
    expect(errorOf(await h.call('graph.getEntity', { entityId: 'e', projectId: 'p2' }))).toBe(
      'invalid_params'
    )
    expect(h.deps.graph.getEntity).not.toHaveBeenCalled()
    await h.call('graph.getEntity', { entityId: 'e' })
    expect(h.deps.graph.getEntity).toHaveBeenCalledWith('p1', 'e')
  })

  it('a handler throwing a generic error is internal and NOT a refusal event', async () => {
    const deps = fakeBridgeDeps()
    ;(deps.graph.search as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('kaboom'))
    const h = harness({}, { deps })
    const reply = await h.call('graph.search', { q: 'x' })
    expect(errorOf(reply)).toBe('internal')
    expect(reply && !reply.ok ? reply.error.message : '').not.toContain('kaboom')
    expect(deps.emitRefusal).not.toHaveBeenCalled()
  })
})

describe('net.fetch (§6.5)', () => {
  it('non-https → network_denied without touching the desktop bridge', async () => {
    const h = harness()
    expect(errorOf(await h.call('net.fetch', { url: 'http://api.octopart.com/x' }))).toBe(
      'network_denied'
    )
    expect(h.deps.net?.fetch).not.toHaveBeenCalled()
  })

  it('origin not granted → network_denied without touching the desktop bridge', async () => {
    const h = harness()
    expect(errorOf(await h.call('net.fetch', { url: 'https://169.254.169.254/latest' }))).toBe(
      'network_denied'
    )
    expect(errorOf(await h.call('net.fetch', { url: 'https://api.octopart.com.evil.io/' }))).toBe(
      'network_denied'
    )
    expect(h.deps.net?.fetch).not.toHaveBeenCalled()
    expect(h.deps.emitRefusal).toHaveBeenCalledWith(
      expect.objectContaining({ code: 'network_denied' })
    )
  })

  it('a granted origin goes to main with the extension id, base64 body, and the granted list', async () => {
    const h = harness()
    const reply = await h.call('net.fetch', {
      url: 'https://api.octopart.com/v4/parts',
      method: 'POST',
      headers: { 'X-Api-Key': 'k' },
      body: '{"q":"motor"}'
    })
    expect(h.deps.net?.fetch).toHaveBeenCalledWith({
      id: 'bom',
      url: 'https://api.octopart.com/v4/parts',
      method: 'POST',
      headers: { 'X-Api-Key': 'k' },
      bodyBase64: btoa('{"q":"motor"}'),
      allowedOrigins: ['https://api.octopart.com']
    })
    expect(reply?.ok && reply.result).toEqual({
      status: 200,
      headers: { 'content-type': 'application/json' },
      body: '{"a":1}',
      encoding: 'text'
    })
  })

  it('maps main refusals; response_too_large carries the §6.5 message', async () => {
    const deps = fakeBridgeDeps()
    ;(deps.net!.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      error: 'response_too_large'
    })
    const h = harness({}, { deps })
    const reply = await h.call('net.fetch', { url: 'https://api.octopart.com/big' })
    expect(reply && !reply.ok ? reply.error : null).toEqual({
      code: 'network_denied',
      message: 'response too large'
    })
  })

  it('outside Electron (no bridge) net.fetch is unavailable', async () => {
    const h = harness({}, { deps: fakeBridgeDeps({ net: null }) })
    expect(errorOf(await h.call('net.fetch', { url: 'https://api.octopart.com/' }))).toBe(
      'unavailable'
    )
  })
})

describe('refusal events (SEC-H4) — every refusal code reaches emitRefusal', () => {
  it.each([
    ['unknown_method', {}, 'graph.delete', {}],
    ['scope_denied', {}, 'sol.ask', { prompt: 'x' }],
    ['blocked', { blocked: true }, 'graph.getFocus', {}],
    ['network_denied', {}, 'net.fetch', { url: 'https://evil.example/' }],
    ['invalid_params', {}, 'graph.getEntity', { entityId: 42 }]
  ] as const)('%s', async (code, policy, method, params) => {
    const h = harness(policy)
    expect(errorOf(await h.call(method, params))).toBe(code)
    expect(h.deps.emitRefusal).toHaveBeenCalledTimes(1)
    expect(h.deps.emitRefusal).toHaveBeenCalledWith({
      extensionId: 'bom',
      version: '1.2.0',
      method,
      code
    })
  })

  it('rate_limited is emitted too, and the limiter runs BEFORE authorize', async () => {
    const h = harness({}, { rateLimiter: createRateLimiter({ now: () => 0, maxRequests: 1 }) })
    expect(errorOf(await h.call('graph.delete'))).toBe('unknown_method')
    // A second unknown-method spam is answered by the limiter, not by authorize.
    expect(errorOf(await h.call('graph.delete'))).toBe('rate_limited')
    expect(errorOf(await h.call('sol.ask', { prompt: 'x' }))).toBe('rate_limited')
    expect(h.deps.emitRefusal).toHaveBeenLastCalledWith(
      expect.objectContaining({ method: 'sol.ask', code: 'rate_limited' })
    )
  })

  it('a blocked extension spamming is rate-limited first as well', async () => {
    const h = harness(
      { blocked: true },
      { rateLimiter: createRateLimiter({ now: () => 0, maxRequests: 1 }) }
    )
    expect(errorOf(await h.call('graph.getFocus'))).toBe('blocked')
    expect(errorOf(await h.call('graph.getFocus'))).toBe('rate_limited')
  })
})

describe('ui.openExternal (SEC-C1) — no unscoped exfiltration channel', () => {
  const links = { storeLinks: ['https://docs.example.com/bom'] }

  it('refuses an https URL whose origin is not granted, without opening anything', async () => {
    const h = harness(links)
    expect(
      errorOf(await h.call('ui.openExternal', { url: 'https://evil.example/?d=secret' }))
    ).toBe('network_denied')
    expect(h.deps.ui.openExternal).not.toHaveBeenCalled()
    expect(h.deps.emitRefusal).toHaveBeenCalledWith(
      expect.objectContaining({ method: 'ui.openExternal', code: 'network_denied' })
    )
  })

  it('opens a URL on a granted origin', async () => {
    const h = harness(links)
    const reply = await h.call('ui.openExternal', { url: 'https://api.octopart.com/part/1' })
    expect(reply?.ok).toBe(true)
    expect(h.deps.ui.openExternal).toHaveBeenCalledWith('https://api.octopart.com/part/1')
  })

  it('opens an exact store.links URL, but not a variation of it', async () => {
    const h = harness(links)
    expect((await h.call('ui.openExternal', { url: 'https://docs.example.com/bom' }))?.ok).toBe(
      true
    )
    expect(
      errorOf(await h.call('ui.openExternal', { url: 'https://docs.example.com/bom?x=1' }))
    ).toBe('network_denied')
    expect(h.deps.ui.openExternal).toHaveBeenCalledTimes(1)
  })

  it('an extension with no granted origins and no store links cannot open any URL', async () => {
    const h = harness({ grantedNetwork: [], storeLinks: [] })
    expect(errorOf(await h.call('ui.openExternal', { url: 'https://example.com/' }))).toBe(
      'network_denied'
    )
    expect(h.deps.ui.openExternal).not.toHaveBeenCalled()
  })

  it('the 4th call within 60 s is rate_limited; the window then slides', async () => {
    let t = 0
    const h = harness(links, { openExternalLimiter: createOpenExternalLimiter(() => t) })
    const url = 'https://api.octopart.com/'
    for (let i = 0; i < BRIDGE_LIMITS.openExternalPerWindow; i++) {
      expect((await h.call('ui.openExternal', { url }))?.ok).toBe(true)
    }
    expect(errorOf(await h.call('ui.openExternal', { url }))).toBe('rate_limited')
    expect(h.deps.ui.openExternal).toHaveBeenCalledTimes(BRIDGE_LIMITS.openExternalPerWindow)
    t = BRIDGE_LIMITS.openExternalWindowMs + 1
    expect((await h.call('ui.openExternal', { url }))?.ok).toBe(true)
  })

  it('a refused URL does not consume the openExternal budget', async () => {
    const h = harness(links, { openExternalLimiter: createOpenExternalLimiter(() => 0) })
    for (let i = 0; i < 5; i++) await h.call('ui.openExternal', { url: 'https://evil.example/' })
    expect((await h.call('ui.openExternal', { url: 'https://api.octopart.com/' }))?.ok).toBe(true)
  })
})

describe('server errors (§6.4 mapping)', () => {
  it('storage quota from the API is storage_quota and emits a refusal', async () => {
    const deps = fakeBridgeDeps()
    ;(deps.storage.set as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(413, 'storage_quota_exceeded', 'used 261000 of 262144')
    )
    const h = harness({}, { deps })
    const reply = await h.call('storage.set', { key: 'k', value: 'v' })
    expect(reply && !reply.ok ? reply.error : null).toEqual({
      code: 'storage_quota',
      message: 'Storage quota exceeded'
    })
    expect(deps.emitRefusal).toHaveBeenCalledWith(
      expect.objectContaining({ code: 'storage_quota' })
    )
  })

  it('a storage miss is { value: null }, not an error', async () => {
    const deps = fakeBridgeDeps()
    ;(deps.storage.get as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(404, 'not_found', 'no such key')
    )
    const h = harness({}, { deps })
    const reply = await h.call('storage.get', { key: 'missing' })
    expect(reply?.ok && reply.result).toEqual({ value: null })
  })

  it('a 5xx is unavailable with a generic message', async () => {
    const deps = fakeBridgeDeps()
    ;(deps.sources.list as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(503, 'internal_error', 'pg down at 10.0.0.4')
    )
    const h = harness({ grantedScopes: ['sources.read'] }, { deps })
    const reply = await h.call('sources.list')
    expect(reply && !reply.ok ? reply.error : null).toEqual({
      code: 'unavailable',
      message: 'Solus is unavailable'
    })
  })
})

describe('results', () => {
  it('sources.list strips config, account and errors', async () => {
    const h = harness({ grantedScopes: ['sources.read'] })
    const reply = await h.call('sources.list')
    expect(reply?.ok && reply.result).toEqual([
      {
        id: 's1',
        kind: 'github',
        name: 'firmware',
        status: 'connected',
        lastSyncAt: '2026-09-01T00:00:00Z'
      }
    ])
    expect(JSON.stringify(reply)).not.toContain('SECRET')
  })

  it('graph.getNeighborhood answers { entities, relations } from the host project', async () => {
    const h = harness()
    const reply = await h.call('graph.getNeighborhood', { entityId: 'e', depth: 2 })
    expect(h.deps.graph.getNeighborhood).toHaveBeenCalledWith('p1', 'e', 2, 200)
    expect(reply?.ok && reply.result).toEqual({ entities: [], relations: [] })
  })

  it('settings.get returns the extension’s own values as a copy', async () => {
    const h = harness()
    const reply = await h.call('settings.get')
    expect(reply?.ok && reply.result).toEqual({ refresh: 'hourly' })
  })

  it('focus.propose stamps the host project and reports the arbitration result', async () => {
    const h = harness()
    const reply = await h.call('focus.propose', { entityId: 'driver', domain: 'electrical' })
    expect(h.deps.focus.propose).toHaveBeenCalledWith({
      entity: { projectId: 'p1', entityId: 'driver' },
      domain: 'electrical',
      path: []
    })
    expect(reply?.ok && reply.result).toEqual({ accepted: true })
  })

  it('focus.propose refuses a cross-project trail as invalid_params', async () => {
    const deps = fakeBridgeDeps()
    ;(deps.focus.get as ReturnType<typeof vi.fn>).mockReturnValue({
      entity: { projectId: 'p2', entityId: 'x' },
      domain: 'code',
      path: []
    })
    const h = harness({}, { deps })
    expect(
      errorOf(await h.call('focus.propose', { entityId: 'e', domain: 'code', relation: 'r' }))
    ).toBe('invalid_params')
    expect(deps.focus.propose).not.toHaveBeenCalled()
  })

  it('findings.create and telemetry answer unavailable when the seam is not wired', async () => {
    const h = harness(
      { grantedScopes: ['findings.write', 'telemetry.read'] },
      { deps: fakeBridgeDeps({ findings: null, telemetry: null }) }
    )
    expect(
      errorOf(await h.call('findings.create', { title: 't', body: 'b', severity: 'info' }))
    ).toBe('unavailable')
    expect(errorOf(await h.call('telemetry.subscribe', { signalIds: ['s'] }))).toBe('unavailable')
  })
})

describe('handshake and events (§6.2, §6.7)', () => {
  it('init carries the §6.2 payload and nothing else', () => {
    const h = harness()
    h.host.init()
    expect(h.posted).toEqual([
      {
        v: 1,
        event: 'init',
        data: {
          extensionId: 'bom',
          version: '1.2.0',
          projectId: 'p1',
          settings: { refresh: 'hourly' },
          theme: { '--bg': '#0b0b0c', '--acc': '#ffb000' },
          focus: null,
          mode: 'widget'
        }
      }
    ])
  })

  it('ui.ready completes the handshake (sending init first if it was never sent)', async () => {
    const onReady = vi.fn()
    const h = harness({}, { onReady })
    expect(h.host.isReady()).toBe(false)
    const reply = await h.call('ui.ready')
    expect(reply?.ok && reply.result).toEqual({})
    expect(h.host.isReady()).toBe(true)
    expect(onReady).toHaveBeenCalledTimes(1)
    expect(h.posted[0]).toMatchObject({ event: 'init' })
    await h.call('ui.ready')
    expect(onReady).toHaveBeenCalledTimes(1)
  })

  it('events before ui.ready are dropped; after, they flow', async () => {
    const h = harness()
    h.host.sendEvent('theme.changed', { '--bg': '#fff' })
    expect(h.posted).toEqual([])
    await h.call('ui.ready')
    h.host.sendEvent('theme.changed', { '--bg': '#fff' })
    expect(h.posted.at(-1)).toEqual({ v: 1, event: 'theme.changed', data: { '--bg': '#fff' } })
  })

  it('focus.changed goes only to frames with focus.read or graph.read', async () => {
    const without = harness({ grantedScopes: ['sources.read'] })
    await without.call('ui.ready')
    without.host.sendEvent('focus.changed', null)
    expect(without.posted.some((m) => 'event' in m && m.event === 'focus.changed')).toBe(false)

    const withGraph = harness({ grantedScopes: ['graph.read'] })
    await withGraph.call('ui.ready')
    withGraph.host.sendEvent('focus.changed', null)
    expect(withGraph.posted.at(-1)).toEqual({ v: 1, event: 'focus.changed', data: null })
  })

  it('updateSettings notifies the frame and updates settings.get', async () => {
    const h = harness()
    await h.call('ui.ready')
    h.host.updateSettings({ refresh: 'daily' })
    expect(h.posted.at(-1)).toEqual({ v: 1, event: 'settings.changed', data: { refresh: 'daily' } })
    const reply = await h.call('settings.get')
    expect(reply?.ok && reply.result).toEqual({ refresh: 'daily' })
  })

  it('updatePolicy to blocked refuses subsequent calls (snapshot refresh)', async () => {
    const h = harness()
    expect((await h.call('graph.getFocus'))?.ok).toBe(true)
    h.host.updatePolicy({ ...BASE, blocked: true, enabled: false })
    expect(errorOf(await h.call('graph.getFocus'))).toBe('blocked')
  })

  it('telemetry: subscribe → batched telemetry.sample events → unsubscribe; cap at 8', async () => {
    const h = harness()
    await h.call('ui.ready')
    const reply = await h.call('telemetry.subscribe', { signalIds: ['rpm'] })
    const { subscriptionId } = (reply?.ok ? reply.result : {}) as { subscriptionId: string }
    expect(subscriptionId).toMatch(/^sub-/)
    h.deps.fakeTelemetry.push([{ signalId: 'rpm', t: 1, value: 10 }])
    h.deps.fakeTelemetry.push([{ signalId: 'rpm', t: 2, value: 11 }])
    h.timers.fire()
    expect(h.posted.at(-1)).toEqual({
      v: 1,
      event: 'telemetry.sample',
      data: {
        subscriptionId,
        samples: [
          { signalId: 'rpm', t: 1, value: 10 },
          { signalId: 'rpm', t: 2, value: 11 }
        ]
      }
    })
    expect((await h.call('telemetry.unsubscribe', { subscriptionId }))?.ok).toBe(true)
    expect(h.deps.fakeTelemetry.unsubscribe).toHaveBeenCalledTimes(1)
    expect(errorOf(await h.call('telemetry.unsubscribe', { subscriptionId }))).toBe(
      'invalid_params'
    )

    for (let i = 0; i < BRIDGE_LIMITS.subscriptions; i++) {
      expect((await h.call('telemetry.subscribe', { signalIds: ['s'] }))?.ok).toBe(true)
    }
    expect(errorOf(await h.call('telemetry.subscribe', { signalIds: ['s'] }))).toBe(
      'invalid_params'
    )
  })

  it('dispose unsubscribes telemetry and ignores everything afterwards', async () => {
    const h = harness()
    await h.call('ui.ready')
    await h.call('telemetry.subscribe', { signalIds: ['rpm'] })
    h.host.dispose()
    expect(h.deps.fakeTelemetry.unsubscribe).toHaveBeenCalled()
    const before = h.posted.length
    await h.call('graph.getFocus')
    h.host.sendEvent('theme.changed', {})
    expect(h.posted.length).toBe(before)
  })
})

describe('§3 — nothing sensitive ever leaves the host', () => {
  it('no outbound message contains the session token, a bearer header, or an API URL', async () => {
    const deps = fakeBridgeDeps()
    // A deps layer that HOLDS the token (as the real client does) must still
    // never surface it in results.
    ;(deps.graph.getEntity as ReturnType<typeof vi.fn>).mockImplementation(async () => {
      void TOKEN
      return { id: 'e', name: 'U1' }
    })
    const h = harness(
      { grantedScopes: [...BASE.grantedScopes, 'sources.read', 'sol.ask'] },
      { deps }
    )
    h.host.init()
    await h.call('ui.ready')
    await h.call('graph.getEntity', { entityId: 'e' })
    await h.call('sources.list')
    await h.call('sol.ask', { prompt: 'hi' })
    await h.call('net.fetch', { url: 'https://api.octopart.com/x' })
    await h.call('graph.delete')
    const wire = JSON.stringify(h.posted)
    expect(wire).not.toContain(TOKEN)
    expect(wire).not.toMatch(/Bearer/i)
    expect(wire).not.toMatch(/https?:\/\/(api\.test|127\.0\.0\.1|localhost)/)
    expect(wire).not.toContain('Authorization')
  })
})
