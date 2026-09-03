import { describe, it, expect, vi } from 'vitest'
import { joinUrl, unwrapEnvelope, unwrapEnvelopePage, createApiClient } from './client'
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
