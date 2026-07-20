// CSP connect-src widening for the live Solus REST client (SOLUSDEV-152; the
// standing TODO in index.html). The renderer's Content-Security-Policy must list
// the API origin under connect-src, or the browser blocks every fetch to the API
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
 * The origin (`scheme://host:port`) the renderer will call for the REST API,
 * derived from `apiBaseUrl` (or the default when it is absent/blank). Returns
 * null when the value cannot be parsed as a URL, so the CSP is left untouched
 * rather than corrupted.
 */
export function apiOriginForCsp(apiBaseUrl: string | undefined): string | null {
  const raw = apiBaseUrl && apiBaseUrl.trim() ? apiBaseUrl.trim() : DEFAULT_API_BASE_URL
  try {
    return new URL(raw).origin
  } catch {
    return null
  }
}

/**
 * Add `origin` to the CSP meta's `connect-src` directive. Idempotent (never
 * double-adds) and a no-op when `origin` is null or no `connect-src` is present.
 */
export function widenConnectSrc(html: string, origin: string | null): string {
  if (!origin) return html
  // Anchor on the CSP `content="..."` attribute so a stray "connect-src" mention
  // in a nearby HTML comment is never matched. `[^"]` keeps the match inside the
  // attribute; `[^";]` captures just the connect-src directive's source list.
  return html.replace(
    /(content="[^"]*?connect-src\s+)([^";]*)/,
    (match, prefix: string, sources: string) => {
      const list = sources.trim()
      if (list.split(/\s+/).includes(origin)) return match
      return `${prefix}${list} ${origin}`
    }
  )
}
