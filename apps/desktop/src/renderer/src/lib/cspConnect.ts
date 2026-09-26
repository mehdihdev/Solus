// CSP connect-src widening for the live Solus REST and telemetry clients (SOLUSDEV-152; the
// standing TODO in index.html). The renderer's Content-Security-Policy must list
// the exact HTTP(S) API origin and its WS(S) counterpart under connect-src, or
// the browser blocks API fetches and live telemetry sockets
// BEFORE it is sent ("Refused to connect ... violates the document's CSP") — which
// surfaces in the app as the misleading "Solus can't reach its API" state.
//
// The origin is derived from VITE_API_BASE_URL so each environment is exactly
// scoped: dev points at the http loopback API, a packaged build at its https API.
// Pure module: no import.meta, no side effects — importable from both the renderer
// and the Node build config (electron.vite.config.ts), mirroring prodAuthGuard.ts.

/** API base the renderer falls back to when VITE_API_BASE_URL is unset
 * (kept in lockstep with lib/api/client.ts DEFAULT_BASE_URL). */
export const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1'

/**
 * The API base the renderer will actually call. A missing value and a
 * PRESENT-BUT-BLANK one (`VITE_API_BASE_URL=`, which is what apps/desktop/.env
 * ships) both mean "unset" — the blank case is the one `??` misses, and getting
 * it wrong yields a relative base that quietly misses the API entirely. Shared
 * by the CSP derivation and `api/client.ts` so the two cannot drift.
 */
export function resolveApiBaseUrl(apiBaseUrl: string | undefined): string {
  return apiBaseUrl && apiBaseUrl.trim() ? apiBaseUrl.trim() : DEFAULT_API_BASE_URL
}

/**
 * The origin (`scheme://host:port`) the renderer will call for the REST API,
 * derived from `apiBaseUrl` (or the default when it is absent/blank). Returns
 * null when the value cannot be parsed as a URL, so the CSP is left untouched
 * rather than corrupted.
 */
export function apiOriginForCsp(apiBaseUrl: string | undefined): string | null {
  try {
    const url = new URL(resolveApiBaseUrl(apiBaseUrl))
    return ['http:', 'https:'].includes(url.protocol) && !url.hostname.includes('*')
      ? url.origin
      : null
  } catch {
    return null
  }
}

/**
 * Add the HTTP(S) API origin and its exact WS(S) counterpart to connect-src.
 * No wildcard or additional host/port is granted. Idempotent (never
 * double-adds) and a no-op when `origin` is null or no `connect-src` is present.
 */
export function widenConnectSrc(html: string, origin: string | null): string {
  if (!origin) return html
  const apiOrigin = apiOriginForCsp(origin)
  if (!apiOrigin) return html
  const socket = new URL(apiOrigin)
  socket.protocol = socket.protocol === 'https:' ? 'wss:' : 'ws:'
  const allowed = [apiOrigin, socket.origin]
  // Anchor on the CSP `content="..."` attribute so a stray "connect-src" mention
  // in a nearby HTML comment is never matched. `[^"]` keeps the match inside the
  // attribute; `[^";]` captures just the connect-src directive's source list.
  return html.replace(
    /(content="[^"]*?connect-src\s+)([^";]*)/,
    (match, prefix: string, sources: string) => {
      const list = sources.trim()
      const existing = new Set(list.split(/\s+/))
      const missing = allowed.filter((item) => !existing.has(item))
      return missing.length ? `${prefix}${list} ${missing.join(' ')}` : match
    }
  )
}
