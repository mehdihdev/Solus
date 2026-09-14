import { describe, it, expect, vi } from 'vitest'
import {
  joinUrl,
  unwrapEnvelope,
  unwrapEnvelopePage,
  createApiClient,
  MAX_RETRY_AFTER_MS
} from './client'
import { ApiError } from './envelope.types'

describe('joinUrl', () => {
  it('joins without double slashes', () => {
    expect(joinUrl('http://x/api/v1/', '/teams')).toBe('http://x/api/v1/teams')
    expect(joinUrl('http://x/api/v1', 'teams')).toBe('http://x/api/v1/teams')
  })
})

describe('unwrapEnvelope', () => {
  it('returns data on 2xx', () => {
    expect(unwrapEnvelope<{ id: string }>(200, { data: { id: 'a' } })).toEqual({ id: 'a' })
  })

  it('throws a typed ApiError on failure', () => {
    try {
      unwrapEnvelope(403, { error: { code: 'forbidden', message: 'nope' } })
      expect.unreachable('should have thrown')
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError)
      expect((e as ApiError).status).toBe(403)
      expect((e as ApiError).code).toBe('forbidden')
    }
  })

  it('falls back to a generic error when body has no error envelope', () => {
    expect(() => unwrapEnvelope(500, null)).toThrowError(/status 500/)
  })
})

describe('unwrapEnvelopePage', () => {
  it('returns data and meta on 2xx, defaulting meta to {}', () => {
    expect(unwrapEnvelopePage<number[]>(200, { data: [1], meta: { has_next: true } })).toEqual({
      data: [1],
      meta: { has_next: true }
    })
    expect(unwrapEnvelopePage<number[]>(200, { data: [] })).toEqual({ data: [], meta: {} })
  })

  it('throws a typed ApiError on failure', () => {
    expect(() => unwrapEnvelopePage(500, null)).toThrowError(ApiError)
  })
})

describe('createApiClient', () => {
  it('sends an optimistic version header only when requested', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockImplementation(async () => new Response(JSON.stringify({ data: {} }), { status: 200 }))
    const client = createApiClient({ baseUrl: 'http://api/v1', fetchImpl })
    await client.request('/entities/r1', { method: 'PATCH', body: { name: 'Leader' }, ifMatch: 4 })
    expect(fetchImpl.mock.calls[0][1]?.headers).toMatchObject({ 'If-Match': '4' })
    await client.request('/entities/r1')
    expect(fetchImpl.mock.calls[1][1]?.headers).not.toHaveProperty('If-Match')
  })

  it('injects the bearer token and parses the envelope', async () => {
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(new Response(JSON.stringify({ data: { ok: true } }), { status: 200 }))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      getToken: () => 'jwt-123',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const result = await client.request<{ ok: boolean }>('/users/me')
    expect(result).toEqual({ ok: true })
    const call = fetchImpl.mock.calls[0]
    expect(call[0]).toBe('http://api/v1/users/me')
    expect(call[1]?.headers).toMatchObject({ Authorization: 'Bearer jwt-123' })
  })

  it('omits Authorization when there is no token', async () => {
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(new Response(JSON.stringify({ data: null }), { status: 200 }))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    await client.request('/version')
    const call = fetchImpl.mock.calls[0]
    expect(call[1]?.headers).not.toHaveProperty('Authorization')
  })

  it('requestPage returns the data payload and the pagination meta', async () => {
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ data: [{ id: 'a' }], meta: { has_next: true, next_cursor: 'c2' } }),
          { status: 200 }
        )
      )
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const page = await client.requestPage<{ id: string }[]>('/users/me/notifications')
    expect(page.data).toEqual([{ id: 'a' }])
    expect(page.meta).toEqual({ has_next: true, next_cursor: 'c2' })
  })
})

describe('PUT (SOLUSDEV-235 — the extensions surface is the first PUT the desktop makes)', () => {
  it('forwards the PUT verb and a JSON body', async () => {
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(new Response(JSON.stringify({ data: { enabled: true } }), { status: 201 }))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const result = await client.request<{ enabled: boolean }>('/projects/p1/extensions/bom', {
      method: 'PUT',
      body: { grants: { scopes: [], network: [] } }
    })
    expect(result).toEqual({ enabled: true })
    const call = fetchImpl.mock.calls[0]
    expect(call[1]?.method).toBe('PUT')
    expect(call[1]?.body).toBe(JSON.stringify({ grants: { scopes: [], network: [] } }))
    expect(call[1]?.headers).toMatchObject({ 'Content-Type': 'application/json' })
  })
})

describe('204 No Content (SOLUSDEV-233 regression)', () => {
  it('resolves a bodiless 2xx instead of throwing after the server acted', async () => {
    // Every DELETE route returns 204 with an empty body. Reading `.data` off
    // the null body used to throw AFTER the server had already deleted — the
    // UI then showed "Couldn't delete…" for a delete that succeeded.
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(new Response(null, { status: 204 }))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    await expect(
      client.request<void>('/projects/p1/sol/conversations/c1', { method: 'DELETE' })
    ).resolves.toBeUndefined()
  })

  it('unwrapEnvelope treats a null 2xx body as void', () => {
    expect(unwrapEnvelope<void>(204, null)).toBeUndefined()
  })
})

// SOLUSDEV-234: the desktop's background pollers (bench, bridge, sources,
// extensions, widgets) plus navigation bursts blew through the API's
// per-token budget, and every poller kept hammering a 429ing server until the
// app was unusable. Two client-side guards, both keyed on GET only:
// concurrent identical reads share ONE network request, and a 429 pauses
// reads until the server's own Retry-After — mutations are never held back.
describe('GET coalescing (SOLUSDEV-234)', () => {
  function okResponse(payload: unknown): Response {
    return new Response(JSON.stringify({ data: payload }), { status: 200 })
  }

  it('shares one network request between concurrent identical GETs', async () => {
    let release: (r: Response) => void = () => {}
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
      () => new Promise<Response>((resolve) => (release = resolve))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const a = client.request<{ n: number }>('/projects/p1/sources')
    const b = client.request<{ n: number }>('/projects/p1/sources')
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    release(okResponse({ n: 1 }))
    await expect(a).resolves.toEqual({ n: 1 })
    await expect(b).resolves.toEqual({ n: 1 })

    // Once settled, the next read is a fresh request (no stale caching).
    fetchImpl.mockResolvedValueOnce(okResponse({ n: 2 }))
    await expect(client.request<{ n: number }>('/projects/p1/sources')).resolves.toEqual({ n: 2 })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('does not share between different paths, non-GETs, or aborted requests', async () => {
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(okResponse(null))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    await Promise.all([
      client.request('/a'),
      client.request('/b'),
      client.request('/a', { method: 'POST', body: {} }),
      client.request('/a', { method: 'POST', body: {} }),
      client.request('/a', { signal: new AbortController().signal })
    ])
    expect(fetchImpl).toHaveBeenCalledTimes(5)
  })

  it('a rejected shared request rejects every waiter and is not retained', async () => {
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.reject(new TypeError('network down'))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const a = client.request('/a')
    const b = client.request('/a')
    await expect(a).rejects.toThrow('network down')
    await expect(b).rejects.toThrow('network down')
    fetchImpl.mockResolvedValueOnce(okResponse(null))
    await expect(client.request('/a')).resolves.toBeNull()
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })
})

describe('429 cooldown (SOLUSDEV-234)', () => {
  const rateLimited = (retryAfter: string): Response =>
    new Response(
      JSON.stringify({ error: { code: 'rate_limited', message: 'Rate limit exceeded' } }),
      {
        status: 429,
        headers: { 'Retry-After': retryAfter }
      }
    )

  it('holds GETs back until Retry-After elapses, then resumes', async () => {
    let nowMs = 1_000_000
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(rateLimited('30'))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => nowMs
    })
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429, code: 'rate_limited' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)

    // Still inside the window: every read fails fast without touching the network.
    nowMs += 10_000
    await expect(client.request('/b')).rejects.toMatchObject({ status: 429, code: 'rate_limited' })
    await expect(client.requestPage('/c')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(1)

    // Window over: reads go to the network again.
    nowMs += 20_001
    fetchImpl.mockResolvedValueOnce(new Response(JSON.stringify({ data: 'ok' }), { status: 200 }))
    await expect(client.request('/a')).resolves.toBe('ok')
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('never holds back mutations, and a 429 on a mutation does not pause reads', async () => {
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(rateLimited('60'))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => 0
    })
    // Separate server buckets (e.g. classify) 429 independently of the global
    // read budget, so a POST 429 says nothing about whether reads would pass.
    await expect(
      client.request('/orchestration/classify', { method: 'POST', body: {} })
    ).rejects.toMatchObject({ status: 429 })
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    // Now reads are paused (the GET 429 above) — a mutation still goes through.
    await expect(client.request('/x', { method: 'DELETE' })).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(3)
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(3)
  })

  it('falls back to a short pause when Retry-After is missing or malformed', async () => {
    let nowMs = 0
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(rateLimited('soon'))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => nowMs
    })
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    nowMs += 5_001
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })
})

describe('coalescing and cooldown are scoped to the signed-in token (SOLUSDEV-234 security review)', () => {
  const ok = (payload: unknown): Response =>
    new Response(JSON.stringify({ data: payload }), { status: 200 })
  const rateLimited = (headers: Record<string, string>): Response =>
    new Response(JSON.stringify({ error: { code: 'rate_limited', message: 'x' } }), {
      status: 429,
      headers
    })
  requestAccountIsolationTests(ok, rateLimited)
  requestRateLimitScopeTests(rateLimited)
  requestMutationInvalidationTests(ok)
})

function requestAccountIsolationTests(
  ok: (payload: unknown) => Response,
  rateLimited: (headers: Record<string, string>) => Response
): void {
  it("never hands one account another account's in-flight response", async () => {
    let token = 'jwt-A'
    let release: (r: Response) => void = () => {}
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
      () => new Promise<Response>((resolve) => (release = resolve))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      getToken: () => token,
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const a = client.request<string>('/users/me/credits')
    await Promise.resolve() // let A resolve its token and take the slot
    const releaseA = release
    token = 'jwt-B' // sign-out / sign-in on a shared machine
    const b = client.request<string>('/users/me/credits')
    await Promise.resolve()
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    release(ok('for-B'))
    releaseA(ok('for-A'))
    await expect(a).resolves.toBe('for-A')
    await expect(b).resolves.toBe('for-B')
  })

  it("a new sign-in does not inherit the previous token's read pause", async () => {
    let token = 'jwt-A'
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(rateLimited({ 'Retry-After': '60', 'X-RateLimit-Remaining': '0' }))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      getToken: () => token,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => 0
    })
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    token = 'jwt-B'
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })
}

function requestRateLimitScopeTests(
  rateLimited: (headers: Record<string, string>) => Response
): void {
  it('clamps an absurd Retry-After so reads can never be frozen for the process lifetime', async () => {
    let nowMs = 0
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(rateLimited({ 'Retry-After': '999999999' }))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => nowMs
    })
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    nowMs = MAX_RETRY_AFTER_MS - 1
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    nowMs = MAX_RETRY_AFTER_MS + 1
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('applies the pause to abortable GETs too (only coalescing is skipped for them)', async () => {
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(rateLimited({ 'Retry-After': '30' }))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => 0
    })
    await expect(client.request('/a')).rejects.toMatchObject({ status: 429 })
    await expect(
      client.request('/a', { signal: new AbortController().signal })
    ).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('a 429 from a route-level limiter (read budget still has headroom) does not pause reads', async () => {
    // The middleware stamps X-RateLimit-* on EVERY response, so a 429 minted
    // by a route's own limiter (extension bundle, artifact content) arrives
    // with Remaining > 0 — it says nothing about the shared read budget.
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      Promise.resolve(rateLimited({ 'Retry-After': '30', 'X-RateLimit-Remaining': '900' }))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      now: () => 0
    })
    await expect(client.request('/extensions/x/versions/1/bundle')).rejects.toMatchObject({
      status: 429
    })
    await expect(client.request('/projects/p/sources')).rejects.toMatchObject({ status: 429 })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })
}

function requestMutationInvalidationTests(ok: (payload: unknown) => Response): void {
  it('a completed mutation drops in-flight reads so the next refetch is fresh', async () => {
    const responses: Array<(r: Response) => void> = []
    const fetchImpl = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
      () => new Promise<Response>((resolve) => responses.push(resolve))
    )
    const client = createApiClient({
      baseUrl: 'http://api/v1',
      fetchImpl: fetchImpl as unknown as typeof fetch
    })
    const stale = client.request<string>('/projects/p/extensions') // poller, pre-mutation
    const mutation = client.request('/projects/p/extensions/bom', { method: 'PUT', body: {} })
    await Promise.resolve()
    responses[1](ok(null))
    await mutation
    const fresh = client.request<string>('/projects/p/extensions') // refetch after mutation
    await Promise.resolve()
    expect(fetchImpl).toHaveBeenCalledTimes(3)
    responses[0](ok('before'))
    responses[2](ok('after'))
    await expect(stale).resolves.toBe('before')
    await expect(fresh).resolves.toBe('after')
  })
}
