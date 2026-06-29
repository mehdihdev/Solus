import { describe, it, expect, vi } from 'vitest'
import { joinUrl, unwrapEnvelope, createApiClient } from './client'
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
})
