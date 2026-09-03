// SOLUSDEV-235 / EXT-05 — the network egress proxy behind permissions.network.
// Fetch and DNS are injected: nothing here touches the network.
import { describe, expect, test, vi } from 'vitest'
import {
  fetchForExtension,
  isPrivateAddress,
  NET_LIMITS,
  sanitizeOutgoingHeaders,
  type NetFetchRequest,
  type NetProxyDeps,
  type ProxyFetch
} from './netProxy'

const ORIGIN = 'https://api.example.com'
const PUBLIC_IP = '93.184.216.34'

function okFetch(body = 'ok', init: ResponseInit = {}): ProxyFetch {
  return vi.fn(async () => new Response(body, { status: 200, ...init })) as unknown as ProxyFetch
}

function deps(over: Partial<NetProxyDeps> = {}): NetProxyDeps {
  return {
    fetch: okFetch(),
    resolve: async () => [PUBLIC_IP],
    timeoutMs: 1000,
    ...over
  }
}

function req(over: Partial<NetFetchRequest> = {}): NetFetchRequest {
  return { url: `${ORIGIN}/v1/parts`, allowedOrigins: [ORIGIN], ...over }
}

const b64 = (s: string): string => Buffer.from(s).toString('base64')
const fromB64 = (s: string): string => Buffer.from(s, 'base64').toString()

describe('isPrivateAddress', () => {
  test.each([
    '10.0.0.1',
    '172.16.0.1',
    '172.31.255.254',
    '192.168.1.1',
    '127.0.0.1',
    '127.255.255.255',
    '169.254.169.254',
    '100.64.0.1',
    '100.127.255.255',
    '0.0.0.0',
    '224.0.0.1',
    '255.255.255.255',
    '::1',
    '::',
    'fc00::1',
    'fd12:3456::1',
    'fe80::1',
    'febf::1',
    '::ffff:10.0.0.1',
    '::ffff:7f00:1',
    'not-an-ip'
  ])('refuses %s', (ip) => {
    expect(isPrivateAddress(ip)).toBe(true)
  })

  test.each([
    PUBLIC_IP,
    '172.32.0.1',
    '100.128.0.1',
    '11.0.0.1',
    '2606:2800:220:1::1',
    '::ffff:93.184.216.34'
  ])('allows %s', (ip) => {
    expect(isPrivateAddress(ip)).toBe(false)
  })
})

describe('sanitizeOutgoingHeaders', () => {
  test('drops credential-bearing and connection headers, keeps the rest', () => {
    expect(
      sanitizeOutgoingHeaders({
        Cookie: 'a=b',
        authorization: 'Bearer x',
        'Proxy-Authorization': 'y',
        Host: 'evil',
        'X-Api-Key': 'k',
        Accept: 'application/json'
      })
    ).toEqual({ 'x-api-key': 'k', accept: 'application/json' })
  })

  test('rejects malformed names, CR/LF values, non-strings, and too many headers', () => {
    expect(sanitizeOutgoingHeaders({ 'bad name': 'x' })).toBeNull()
    expect(sanitizeOutgoingHeaders({ ok: 'a\r\nInjected: b' })).toBeNull()
    expect(sanitizeOutgoingHeaders({ ok: 1 })).toBeNull()
    expect(
      sanitizeOutgoingHeaders(
        Object.fromEntries(Array.from({ length: 40 }, (_, i) => [`h${i}`, 'v']))
      )
    ).toBeNull()
    expect(sanitizeOutgoingHeaders(undefined)).toEqual({})
    expect(sanitizeOutgoingHeaders('x')).toBeNull()
  })
})

describe('fetchForExtension — refusals', () => {
  test.each([
    ['http', { url: 'http://api.example.com/x' }, 'scheme_not_https'],
    ['not a URL', { url: 'nope' }, 'invalid_input'],
    ['userinfo in the URL', { url: 'https://u:p@api.example.com/x' }, 'invalid_input'],
    ['origin not allowed', { url: 'https://other.example.com/x' }, 'origin_not_allowed'],
    [
      'subdomain of an allowed origin',
      { url: 'https://evil.api.example.com/x' },
      'origin_not_allowed'
    ],
    ['empty allowlist', { allowedOrigins: [] }, 'origin_not_allowed'],
    ['non-array allowlist', { allowedOrigins: 'x' as unknown as string[] }, 'invalid_input'],
    ['method not allowed', { method: 'TRACE' }, 'method_not_allowed'],
    ['bad header', { headers: { 'bad name': 'x' } }, 'invalid_input'],
    [
      'oversized body',
      { method: 'POST', bodyBase64: b64('x'.repeat(NET_LIMITS.requestBytes + 1)) },
      'request_too_large'
    ]
  ])('%s', async (_why, over, error) => {
    const d = deps()
    expect(await fetchForExtension(req(over as Partial<NetFetchRequest>), d)).toEqual({
      ok: false,
      error
    })
    expect(d.fetch).not.toHaveBeenCalled()
  })

  test('the allowlist matches the exact origin (a default port is the same origin)', async () => {
    const d = deps()
    const result = await fetchForExtension(
      req({ allowedOrigins: ['https://api.example.com:443'] }),
      d
    )
    expect(result.ok).toBe(true)
  })

  test.each(['10.0.0.1', '127.0.0.1', '169.254.169.254', '::1', 'fd00::1'])(
    'refuses a host that resolves to %s without fetching',
    async (ip) => {
      const d = deps({ resolve: async () => [PUBLIC_IP, ip] })
      expect(await fetchForExtension(req(), d)).toEqual({ ok: false, error: 'address_refused' })
      expect(d.fetch).not.toHaveBeenCalled()
    }
  )

  test('refuses a literal private IP host without resolving', async () => {
    const resolve = vi.fn(async () => [PUBLIC_IP])
    const d = deps({ resolve })
    const result = await fetchForExtension(
      req({ url: 'https://10.0.0.8/x', allowedOrigins: ['https://10.0.0.8'] }),
      d
    )
    expect(result).toEqual({ ok: false, error: 'address_refused' })
    expect(resolve).not.toHaveBeenCalled()
    const v6 = await fetchForExtension(
      req({ url: 'https://[::1]/x', allowedOrigins: ['https://[::1]'] }),
      d
    )
    expect(v6).toEqual({ ok: false, error: 'address_refused' })
  })

  test('DNS failure or an empty answer is dns_failed', async () => {
    expect(
      await fetchForExtension(
        req(),
        deps({
          resolve: async () => {
            throw new Error('ENOTFOUND')
          }
        })
      )
    ).toEqual({ ok: false, error: 'dns_failed' })
    expect(await fetchForExtension(req(), deps({ resolve: async () => [] }))).toEqual({
      ok: false,
      error: 'dns_failed'
    })
  })

  test('a cross-origin redirect is refused and never followed', async () => {
    const fetch = vi.fn(
      async () =>
        new Response(null, { status: 302, headers: { location: 'https://evil.example.com/x' } })
    ) as unknown as ProxyFetch
    expect(await fetchForExtension(req(), deps({ fetch }))).toEqual({
      ok: false,
      error: 'redirect_refused'
    })
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  test('same-origin redirects are followed with GET, up to the hop limit', async () => {
    const calls: Array<{ url: string; method: string }> = []
    const fetch = (async (url: string, init: { method: string }) => {
      calls.push({ url, method: init.method })
      return url.endsWith('/final')
        ? new Response('done', { status: 200 })
        : new Response(null, { status: 303, headers: { location: '/final' } })
    }) as unknown as ProxyFetch
    const result = await fetchForExtension(
      req({ method: 'POST', bodyBase64: b64('p') }),
      deps({ fetch })
    )
    expect(result.ok).toBe(true)
    expect(calls).toEqual([
      { url: `${ORIGIN}/v1/parts`, method: 'POST' },
      { url: `${ORIGIN}/final`, method: 'GET' }
    ])

    const loop = (async () =>
      new Response(null, { status: 302, headers: { location: '/again' } })) as unknown as ProxyFetch
    expect(await fetchForExtension(req(), deps({ fetch: loop }))).toEqual({
      ok: false,
      error: 'redirect_refused'
    })
  })

  test('a response over the cap is refused — by content-length, or while streaming', async () => {
    const declared = okFetch('x', {
      headers: { 'content-length': String(NET_LIMITS.responseBytes + 1) }
    })
    expect(await fetchForExtension(req(), deps({ fetch: declared }))).toEqual({
      ok: false,
      error: 'response_too_large'
    })
    const streamed = okFetch('x'.repeat(NET_LIMITS.responseBytes + 1))
    expect(await fetchForExtension(req(), deps({ fetch: streamed }))).toEqual({
      ok: false,
      error: 'response_too_large'
    })
  })

  test('a fetch that does not settle within the timeout is a timeout', async () => {
    const fetch = ((_url: string, init: { signal: AbortSignal }) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => reject(init.signal.reason))
      })) as unknown as ProxyFetch
    expect(await fetchForExtension(req(), deps({ fetch, timeoutMs: 5 }))).toEqual({
      ok: false,
      error: 'timeout'
    })
  })

  test('any other fetch failure is network_error', async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError('fetch failed')
    }) as unknown as ProxyFetch
    expect(await fetchForExtension(req(), deps({ fetch }))).toEqual({
      ok: false,
      error: 'network_error'
    })
  })
})

describe('fetchForExtension — success', () => {
  test('returns status, allowlisted headers, and the body as base64', async () => {
    const fetch = okFetch('{"a":1}', {
      status: 201,
      headers: {
        'content-type': 'application/json',
        etag: '"v1"',
        'last-modified': 'Wed, 03 Sep 2026 00:00:00 GMT',
        'set-cookie': 'session=secret',
        'x-internal': 'nope'
      }
    })
    const result = await fetchForExtension(req(), deps({ fetch }))
    expect(result).toEqual({
      ok: true,
      status: 201,
      headers: {
        'content-type': 'application/json',
        etag: '"v1"',
        'last-modified': 'Wed, 03 Sep 2026 00:00:00 GMT'
      },
      bodyBase64: b64('{"a":1}')
    })
  })

  test('forwards the method, sanitized headers, and decoded body; never cookies or authorization', async () => {
    const fetch = vi.fn(async () => new Response('', { status: 204 })) as unknown as ProxyFetch
    await fetchForExtension(
      req({
        method: 'post',
        headers: { Cookie: 'x', Authorization: 'y', 'Content-Type': 'text/plain' },
        bodyBase64: b64('hello')
      }),
      deps({ fetch })
    )
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      { method: string; headers: Record<string, string>; body?: Uint8Array; redirect: string }
    ]
    expect(url).toBe(`${ORIGIN}/v1/parts`)
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'content-type': 'text/plain' })
    expect(init.redirect).toBe('manual')
    expect(fromB64(Buffer.from(init.body as Uint8Array).toString('base64'))).toBe('hello')
  })

  test('GET and HEAD never carry a body', async () => {
    const fetch = vi.fn(async () => new Response('', { status: 200 })) as unknown as ProxyFetch
    await fetchForExtension(req({ bodyBase64: b64('ignored') }), deps({ fetch }))
    const init = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as {
      body?: unknown
    }
    expect(init.body).toBeUndefined()
  })
})
