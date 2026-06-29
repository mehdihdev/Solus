// Typed Solus REST client (CLAUDE.md §8 — "typed API client only, no raw fetch
// scattered through components"). Wraps fetch with the §1.4 response envelope,
// bearer-token injection, and error normalization.
//
// In this onboarding slice the flows are simulated (no live source/graph calls),
// but the client is the single seam every future feature talks through.
import { ApiError, type ApiSuccess } from './envelope.types'

export interface ApiClientOptions {
  baseUrl: string
  /** Returns the current Supabase JWT, or null when unauthenticated. */
  getToken?: () => Promise<string | null> | string | null
  fetchImpl?: typeof fetch
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
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

/** Normalize a parsed JSON body + status into data or a thrown ApiError. */
export function unwrapEnvelope<T>(status: number, body: unknown): T {
  if (status >= 200 && status < 300) {
    return (body as ApiSuccess<T>).data
  }
  const err = extractError(body)
  throw new ApiError(
    status,
    err.code ?? 'unknown_error',
    err.message ?? `Request failed with status ${status}`,
    err.details
  )
}

export interface ApiClient {
  request<T>(path: string, options?: RequestOptions): Promise<T>
}

export function createApiClient(options: ApiClientOptions): ApiClient {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch
  return {
    async request<T>(path: string, req: RequestOptions = {}): Promise<T> {
      const headers: Record<string, string> = { Accept: 'application/json' }
      if (req.body !== undefined) headers['Content-Type'] = 'application/json'
      const token = typeof options.getToken === 'function' ? await options.getToken() : null
      if (token) headers.Authorization = `Bearer ${token}`

      const res = await fetchImpl(joinUrl(options.baseUrl, path), {
        method: req.method ?? 'GET',
        headers,
        body: req.body !== undefined ? JSON.stringify(req.body) : undefined,
        signal: req.signal
      })
      const text = await res.text()
      const parsed = text ? JSON.parse(text) : null
      return unwrapEnvelope<T>(res.status, parsed)
    }
  }
}

const DEFAULT_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

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
