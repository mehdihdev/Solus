// SOLUSDEV-235 / EXT-05 — the network egress proxy behind an extension's
// `permissions.network` (ADR-035 §2: "hosts outside the allowlist are refused").
// The frame itself has connect-src 'none'; every request an extension makes
// arrives here through the bridge, and THIS process decides:
//
//   https only · exact-origin allowlist · resolved addresses must be public
//   (no private / loopback / link-local / metadata / CGNAT / unspecified /
//   multicast) · redirects handled manually and refused across origins ·
//   15 s wall clock · 5 MiB response cap · Cookie / Authorization never
//   forwarded · only a handful of response headers come back.
//
// Fetch and DNS are injected so the rules are provable without a network. The
// production fetch is Node's (undici): unlike Electron's net.fetch it carries
// no session cookies, so the user's Solus session can never ride along.
import { lookup } from 'node:dns/promises'
import { isIP } from 'node:net'

export const NET_LIMITS = {
  timeoutMs: 15_000,
  responseBytes: 5 * 1024 * 1024,
  requestBytes: 5 * 1024 * 1024,
  redirects: 3,
  headers: 32
} as const

const METHODS = new Set(['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'])
const BODYLESS = new Set(['GET', 'HEAD'])
/** Never forwarded: credentials the extension must not be able to replay,
 *  plus the pseudo/connection headers the transport owns. */
const STRIPPED_HEADERS = new Set([
  'cookie',
  'authorization',
  'proxy-authorization',
  'host',
  'content-length',
  'connection',
  'transfer-encoding'
])
const RETURNED_HEADERS = ['content-type', 'content-length', 'etag', 'last-modified']
const HEADER_NAME_RE = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/
// eslint-disable-next-line no-control-regex
const HEADER_VALUE_BAD_RE = /[\x00-\x08\x0a-\x1f\x7f]/
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308])
const GET_AFTER_REDIRECT = new Set([301, 302, 303])

export type NetFetchError =
  | 'invalid_input'
  | 'scheme_not_https'
  | 'origin_not_allowed'
  | 'method_not_allowed'
  | 'request_too_large'
  | 'address_refused'
  | 'dns_failed'
  | 'redirect_refused'
  | 'timeout'
  | 'network_error'
  | 'response_too_large'

export interface NetFetchRequest {
  readonly url: string
  readonly method?: string
  readonly headers?: Record<string, string>
  readonly bodyBase64?: string
  /** The manifest's `permissions.network` — https origins, matched exactly. */
  readonly allowedOrigins: readonly string[]
}

export type NetFetchResult =
  | {
      readonly ok: true
      readonly status: number
      readonly headers: Readonly<Record<string, string>>
      readonly bodyBase64: string
    }
  | { readonly ok: false; readonly error: NetFetchError }

/** The slice of fetch this module relies on. */
export interface ProxyFetchInit {
  method: string
  headers: Record<string, string>
  body?: Uint8Array
  redirect: 'manual'
  signal: AbortSignal
}
export interface ProxyResponse {
  readonly status: number
  readonly headers: { get(name: string): string | null }
  readonly body: ReadableStream<Uint8Array> | null
}
export type ProxyFetch = (url: string, init: ProxyFetchInit) => Promise<ProxyResponse>

export interface NetProxyDeps {
  fetch: ProxyFetch
  /** Every address `hostname` resolves to (A and AAAA). */
  resolve: (hostname: string) => Promise<string[]>
  timeoutMs: number
}

// ---------------------------------------------------------------------------
// Address classification
// ---------------------------------------------------------------------------

function isPrivateV4(octets: number[]): boolean {
  const [a, b] = octets
  return (
    a === 0 || // "this" network
    a === 10 ||
    a === 127 ||
    (a === 169 && b === 254) || // link-local incl. cloud metadata
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 100 && b >= 64 && b <= 127) || // CGNAT
    a >= 224 // multicast + reserved + broadcast
  )
}

function v4ToHextets(quad: string): string {
  const [a, b, c, d] = quad.split('.').map(Number)
  return `${((a << 8) | b).toString(16)}:${((c << 8) | d).toString(16)}`
}

/** Expand an IPv6 literal to 8 hextets (embedded IPv4 folded in); null if malformed. */
function hextets(ip: string): number[] | null {
  const lower = ip.toLowerCase()
  const v4Tail = lower.match(/^(.*:)(\d+\.\d+\.\d+\.\d+)$/)
  const text = v4Tail ? `${v4Tail[1]}${v4ToHextets(v4Tail[2])}` : lower
  const [head, tail] = text.split('::')
  const left = head ? head.split(':') : []
  const right = tail ? tail.split(':') : []
  if (tail === undefined && left.length !== 8) return null
  const fill = Array<string>(8 - left.length - right.length).fill('0')
  const all = [...left, ...fill, ...right]
  if (all.length !== 8) return null
  const parsed = all.map((h) => parseInt(h, 16))
  return parsed.every((n) => Number.isInteger(n) && n >= 0 && n <= 0xffff) ? parsed : null
}

function isPrivateV6(ip: string): boolean {
  const h = hextets(ip)
  if (h === null) return true
  const isMapped = h.slice(0, 5).every((x) => x === 0) && h[5] === 0xffff
  if (isMapped) return isPrivateV4([h[6] >> 8, h[6] & 0xff, h[7] >> 8, h[7] & 0xff])
  if (h.slice(0, 7).every((x) => x === 0) && h[7] <= 1) return true // :: and ::1
  if ((h[0] & 0xfe00) === 0xfc00) return true // fc00::/7 unique local
  if ((h[0] & 0xffc0) === 0xfe80) return true // fe80::/10 link-local
  return (h[0] & 0xff00) === 0xff00 // ff00::/8 multicast
}

/** True for any address an extension must not reach — and for anything that
 *  is not a well-formed IP at all (fail closed). */
export function isPrivateAddress(ip: string): boolean {
  const kind = isIP(ip)
  if (kind === 4) return isPrivateV4(ip.split('.').map(Number))
  if (kind === 6) return isPrivateV6(ip)
  return true
}

// ---------------------------------------------------------------------------
// Request validation
// ---------------------------------------------------------------------------

/** Lower-cased, credential-free headers; null when the shape is unacceptable. */
export function sanitizeOutgoingHeaders(headers: unknown): Record<string, string> | null {
  if (headers === undefined) return {}
  if (typeof headers !== 'object' || headers === null || Array.isArray(headers)) return null
  const entries = Object.entries(headers as Record<string, unknown>)
  if (entries.length > NET_LIMITS.headers) return null
  const out: Record<string, string> = {}
  for (const [name, value] of entries) {
    if (!HEADER_NAME_RE.test(name) || typeof value !== 'string' || HEADER_VALUE_BAD_RE.test(value))
      return null
    const lowered = name.toLowerCase()
    if (!STRIPPED_HEADERS.has(lowered)) out[lowered] = value
  }
  return out
}

type Refusal = { ok: false; error: NetFetchError }
const refuse = (error: NetFetchError): Refusal => ({ ok: false, error })

function parseTarget(url: unknown): URL | Refusal {
  if (typeof url !== 'string') return refuse('invalid_input')
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return refuse('invalid_input')
  }
  if (parsed.protocol !== 'https:') return refuse('scheme_not_https')
  if (parsed.username || parsed.password) return refuse('invalid_input')
  return parsed
}

function originOf(value: string): string | null {
  try {
    const u = new URL(value)
    return u.protocol === 'https:' && u.pathname === '/' && !u.search && !u.hash ? u.origin : null
  } catch {
    return null
  }
}

function checkOrigin(target: URL, allowedOrigins: unknown): Refusal | null {
  if (!Array.isArray(allowedOrigins) || allowedOrigins.some((o) => typeof o !== 'string'))
    return refuse('invalid_input')
  const allowed = new Set(allowedOrigins.map(originOf))
  return allowed.has(target.origin) ? null : refuse('origin_not_allowed')
}

interface Prepared {
  method: string
  headers: Record<string, string>
  body?: Uint8Array
}

function prepare(req: NetFetchRequest): Prepared | Refusal {
  if (req.method !== undefined && typeof req.method !== 'string') return refuse('invalid_input')
  const method = (req.method ?? 'GET').toUpperCase()
  if (!METHODS.has(method)) return refuse('method_not_allowed')
  const headers = sanitizeOutgoingHeaders(req.headers)
  if (headers === null) return refuse('invalid_input')
  if (BODYLESS.has(method) || req.bodyBase64 === undefined) return { method, headers }
  if (typeof req.bodyBase64 !== 'string') return refuse('invalid_input')
  const body = new Uint8Array(Buffer.from(req.bodyBase64, 'base64'))
  return body.byteLength > NET_LIMITS.requestBytes
    ? refuse('request_too_large')
    : { method, headers, body }
}

async function checkAddresses(hostname: string, deps: NetProxyDeps): Promise<Refusal | null> {
  const literal = hostname.startsWith('[') ? hostname.slice(1, -1) : hostname
  if (isIP(literal)) return isPrivateAddress(literal) ? refuse('address_refused') : null
  let addresses: string[]
  try {
    addresses = await deps.resolve(hostname)
  } catch {
    return refuse('dns_failed')
  }
  if (addresses.length === 0) return refuse('dns_failed')
  return addresses.some(isPrivateAddress) ? refuse('address_refused') : null
}

// ---------------------------------------------------------------------------
// Fetch + response
// ---------------------------------------------------------------------------

async function readCapped(body: ReadableStream<Uint8Array> | null): Promise<Uint8Array | null> {
  if (body === null) return new Uint8Array(0)
  const reader = body.getReader()
  const chunks: Uint8Array[] = []
  let total = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    total += value.byteLength
    if (total > NET_LIMITS.responseBytes) {
      await reader.cancel()
      return null
    }
    chunks.push(value)
  }
  return new Uint8Array(Buffer.concat(chunks))
}

function returnedHeaders(response: ProxyResponse): Record<string, string> {
  const out: Record<string, string> = {}
  for (const name of RETURNED_HEADERS) {
    const value = response.headers.get(name)
    if (value !== null) out[name] = value
  }
  return out
}

/** Follow same-origin redirects by hand (≤ NET_LIMITS.redirects); any hop to
 *  another origin — or one hop too many — is refused. */
async function fetchFollowing(
  target: URL,
  prepared: Prepared,
  deps: NetProxyDeps,
  signal: AbortSignal
): Promise<{ response: ProxyResponse } | Refusal> {
  let url = target
  let { method, body } = prepared
  for (let hop = 0; hop <= NET_LIMITS.redirects; hop++) {
    const response = await deps.fetch(url.toString(), {
      method,
      headers: prepared.headers,
      ...(body !== undefined ? { body } : {}),
      redirect: 'manual',
      signal
    })
    const location = response.headers.get('location')
    if (!REDIRECT_STATUSES.has(response.status) || location === null) return { response }
    let next: URL
    try {
      next = new URL(location, url)
    } catch {
      return refuse('redirect_refused')
    }
    if (next.origin !== target.origin) return refuse('redirect_refused')
    url = next
    if (GET_AFTER_REDIRECT.has(response.status)) {
      method = 'GET'
      body = undefined
    }
  }
  return refuse('redirect_refused')
}

function failureKind(error: unknown, signal: AbortSignal): NetFetchError {
  const aborted = signal.aborted || (error instanceof Error && error.name === 'AbortError')
  return aborted ? 'timeout' : 'network_error'
}

async function complete(response: ProxyResponse): Promise<NetFetchResult> {
  const declared = Number(response.headers.get('content-length') ?? 0)
  if (declared > NET_LIMITS.responseBytes) return refuse('response_too_large')
  const body = await readCapped(response.body)
  if (body === null) return refuse('response_too_large')
  return {
    ok: true,
    status: response.status,
    headers: returnedHeaders(response),
    bodyBase64: Buffer.from(body).toString('base64')
  }
}

/** The whole decision for one extension network request. Never throws. */
export async function fetchForExtension(
  req: NetFetchRequest,
  deps: NetProxyDeps
): Promise<NetFetchResult> {
  const target = parseTarget(req.url)
  if (!(target instanceof URL)) return target
  const originBad = checkOrigin(target, req.allowedOrigins)
  if (originBad) return originBad
  const prepared = prepare(req)
  if ('ok' in prepared) return prepared
  const addressBad = await checkAddresses(target.hostname, deps)
  if (addressBad) return addressBad

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new Error('timeout')), deps.timeoutMs)
  try {
    // A fetch Response carries its own `ok`, so discriminate on `error`.
    const followed = await fetchFollowing(target, prepared, deps, controller.signal)
    if ('error' in followed) return followed
    return await complete(followed.response)
  } catch (error) {
    return refuse(failureKind(error, controller.signal))
  } finally {
    clearTimeout(timer)
  }
}

export const realNetProxyDeps: NetProxyDeps = {
  fetch: (url, init) => globalThis.fetch(url, init) as Promise<ProxyResponse>,
  resolve: async (hostname) =>
    (await lookup(hostname, { all: true, verbatim: true })).map((entry) => entry.address),
  timeoutMs: NET_LIMITS.timeoutMs
}
