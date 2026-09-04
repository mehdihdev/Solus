// Typed Solus REST client (CLAUDE.md §8 — "typed API client only, no raw fetch
// scattered through components"). Wraps fetch with the §1.4 response envelope,
// bearer-token injection, and error normalization.
//
// In this onboarding slice the flows are simulated (no live source/graph calls),
// but the client is the single seam every future feature talks through.
import { ApiError, type ApiMeta, type ApiSuccess } from './envelope.types'
import { resolveApiBaseUrl } from '../cspConnect'

export interface ApiClientOptions {
  baseUrl: string
  /** Returns the current Supabase JWT, or null when unauthenticated. */
  getToken?: () => Promise<string | null> | string | null
  fetchImpl?: typeof fetch
  /** Clock for the 429 cooldown (injectable for tests). Defaults to Date.now. */
  now?: () => number
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

/** Join a base URL and a path without double slashes. Pure + testable. */
export function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`
}

interface ParsedError {
  code?: string
  message?: string
  details?: unknown[]
}

function extractError(body: unknown): ParsedError {
  if (body && typeof body === 'object' && 'error' in body) {
    return (body as { error: ParsedError }).error ?? {}
  }
  return {}
}

/** A list page: the `data` payload plus the envelope's pagination `meta`. */
export interface Page<T> {
  data: T
  meta: ApiMeta
}

/** Normalize a parsed JSON body + status into data or a thrown ApiError. */
export function unwrapEnvelope<T>(status: number, body: unknown): T {
  if (status >= 200 && status < 300) {
    // 204 No Content (every DELETE route) has no body. Reading `.data` off the
    // null body used to throw AFTER the server had already acted, so the UI
    // reported a failure for a delete that succeeded (SOLUSDEV-233).
    if (body === null) return undefined as T
    return (body as ApiSuccess<T>).data
  }
  throw envelopeError(status, body)
}

/** Like `unwrapEnvelope` but keeps the pagination `meta` (for cursor lists). */
export function unwrapEnvelopePage<T>(status: number, body: unknown): Page<T> {
  if (status >= 200 && status < 300) {
    const ok = body as ApiSuccess<T>
    return { data: ok.data, meta: ok.meta ?? {} }
  }
  throw envelopeError(status, body)
}

function envelopeError(status: number, body: unknown): ApiError {
  const err = extractError(body)
  return new ApiError(
    status,
    err.code ?? 'unknown_error',
    err.message ?? `Request failed with status ${status}`,
    err.details
  )
}

export interface ApiClient {
  request<T>(path: string, options?: RequestOptions): Promise<T>
  /** Like `request`, but returns the pagination `meta` alongside `data`. */
  requestPage<T>(path: string, options?: RequestOptions): Promise<Page<T>>
}

/** How long reads pause after a 429 whose `Retry-After` is missing or unparsable. */
export const DEFAULT_RETRY_AFTER_MS = 5_000
/** Ceiling on any `Retry-After` we honour. Our own limiter's window is 60 s;
 *  an intermediary's `86400` must not freeze every read until app restart. */
export const MAX_RETRY_AFTER_MS = 60_000

interface Sent {
  status: number
  body: unknown
}

/** `Retry-After` in delta-seconds → ms, clamped; `null` when absent/malformed. */
function parseRetryAfterMs(header: string | null): number | null {
  if (header === null) return null
  const seconds = Number(header)
  if (!Number.isFinite(seconds) || seconds < 0) return null
  return Math.min(seconds * 1000, MAX_RETRY_AFTER_MS)
}

/** The API middleware stamps `X-RateLimit-Remaining` on EVERY response, so a
 *  429 minted by a route's own limiter (extension bundles, artifact content)
 *  arrives with headroom left in the shared read budget. Only a 429 that
 *  exhausted that budget (or one with no such header, i.e. an intermediary)
 *  should pause reads. */
function isReadBudgetExhausted(res: Response): boolean {
  const remaining = res.headers.get('X-RateLimit-Remaining')
  return remaining === null || Number(remaining) <= 0
}

function rateLimitedLocally(): Sent {
  return {
    status: 429,
    body: { error: { code: 'rate_limited', message: 'Rate limit exceeded' } }
  }
}

const isRead = (req: RequestOptions): boolean => (req.method ?? 'GET') === 'GET'

export function createApiClient(options: ApiClientOptions): ApiClient {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch
  const now = options.now ?? Date.now
  // SOLUSDEV-234. The desktop is polling-heavy (bench, bridge, sources,
  // extensions, widgets — several hooks mounted more than once), and a burst
  // over the API's per-token budget used to snowball: every poller kept
  // firing into a 429ing server until the window reset, taking user-initiated
  // reads down with it. Two guards, both GET-only so a mutation is never
  // silently swallowed, and both scoped to the bearer token so that a
  // sign-out/sign-in on a shared machine can neither be handed the previous
  // account's in-flight response nor inherit its pause:
  //   - concurrent identical reads share ONE in-flight request (dropped when
  //     a mutation completes, so a refetch after a write is always fresh);
  //   - a read-budget 429 pauses reads until the server's own Retry-After.
  const inFlight = new Map<string, Promise<Sent>>()
  let readsPaused: { token: string | null; untilMs: number } = { token: null, untilMs: 0 }

  async function transmit(path: string, req: RequestOptions, token: string | null): Promise<Sent> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (req.body !== undefined) headers['Content-Type'] = 'application/json'
    if (token) headers.Authorization = `Bearer ${token}`

    const res = await fetchImpl(joinUrl(options.baseUrl, path), {
      method: req.method ?? 'GET',
      headers,
      body: req.body !== undefined ? JSON.stringify(req.body) : undefined,
      signal: req.signal
    })
    const text = await res.text()
    if (res.status === 429 && isRead(req) && isReadBudgetExhausted(res)) {
      const retryMs = parseRetryAfterMs(res.headers.get('Retry-After')) ?? DEFAULT_RETRY_AFTER_MS
      const untilMs = now() + retryMs
      if (readsPaused.token !== token || untilMs > readsPaused.untilMs) {
        readsPaused = { token, untilMs }
      }
    }
    return { status: res.status, body: text ? JSON.parse(text) : null }
  }

  async function send(path: string, req: RequestOptions): Promise<Sent> {
    const token = typeof options.getToken === 'function' ? await options.getToken() : null
    if (!isRead(req)) {
      return transmit(path, req, token).finally(() => inFlight.clear())
    }
    if (readsPaused.token === token && now() < readsPaused.untilMs) return rateLimitedLocally()
    // An abortable read is never shared: its caller's cancellation must not
    // cancel (or be ignored by) a sibling with a different lifetime.
    if (req.signal !== undefined) return transmit(path, req, token)
    const key = `${token ?? ''}\u0000${path}`
    const pending = inFlight.get(key)
    if (pending) return pending
    const started = transmit(path, req, token).finally(() => {
      if (inFlight.get(key) === started) inFlight.delete(key)
    })
    inFlight.set(key, started)
    return started
  }

  return {
    async request<T>(path: string, req: RequestOptions = {}): Promise<T> {
      const { status, body } = await send(path, req)
      return unwrapEnvelope<T>(status, body)
    },
    async requestPage<T>(path: string, req: RequestOptions = {}): Promise<Page<T>> {
      const { status, body } = await send(path, req)
      return unwrapEnvelopePage<T>(status, body)
    }
  }
}

// `??` only falls back on null/undefined, so a PRESENT-BUT-BLANK
// `VITE_API_BASE_URL=` (which is what apps/desktop/.env ships) yielded `''` —
// and `joinUrl('', '/projects/x')` is `/projects/x`, a relative URL resolved
// against the renderer's own origin. Every call then missed the API entirely
// and surfaced as "Solus can't reach its API", with the integration catalog
// silently degrading to its offline fallback (so Onshape/Altium/GitLab tiles
// vanished). `cspConnect` already treated blank as absent — that asymmetry WAS
// the bug — so take the constant from there rather than restating it, which is
// what its "kept in lockstep" note asks for.
const DEFAULT_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL)

/** The app client's base URL and token source, exposed so the SSE stream
 *  (which cannot go through `request`, being a streaming body) reuses ONE
 *  configuration instead of re-deriving it. */
export const apiBaseUrl = DEFAULT_BASE_URL

export async function apiToken(): Promise<string | null> {
  const { useAuthStore } = await import('../../store/authStore')
  return useAuthStore.getState().accessToken
}

/**
 * App-wide client. The bearer token is the current Supabase access token held
 * in the auth store (set on bootstrap/sign-in). Imported lazily inside the
 * callback to avoid a module-load cycle with the store.
 */
export const api: ApiClient = createApiClient({
  baseUrl: DEFAULT_BASE_URL,
  getToken: async () => {
    const { useAuthStore } = await import('../../store/authStore')
    return useAuthStore.getState().accessToken
  }
})
