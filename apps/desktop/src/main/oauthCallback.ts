// Pure helpers for the loopback OAuth callback (no Electron imports, so they are
// unit-testable). The main process opens the provider URL in the system browser
// and runs a localhost server on OAUTH_LOOPBACK_PORT to catch the redirect; these
// functions build that redirect URL, validate the authorize URL, and parse the
// incoming request (with a CSRF state check).

/** Fixed loopback port — must match the entry in Supabase's redirect allowlist. */
export const OAUTH_LOOPBACK_PORT = 53682
export const OAUTH_CALLBACK_PATH = '/auth/callback'
/** Loopback host. 127.0.0.1 (not "localhost") to avoid an IPv6 (::1) miss. */
export const OAUTH_LOOPBACK_HOST = '127.0.0.1'

const LOOPBACK_BASE = `http://${OAUTH_LOOPBACK_HOST}:${OAUTH_LOOPBACK_PORT}`

/** Redirect URL the provider sends the browser back to, carrying our CSRF state. */
export function loopbackRedirectUrl(state: string, port: number = OAUTH_LOOPBACK_PORT): string {
  return `http://${OAUTH_LOOPBACK_HOST}:${port}${OAUTH_CALLBACK_PATH}?solus_cb=${encodeURIComponent(state)}`
}

/**
 * The main process hands `shell.openExternal` whatever URL the renderer built.
 * Only allow https (the Supabase authorize URL) — never file:/custom schemes,
 * which openExternal would otherwise launch. Pure + testable.
 */
export function isValidAuthorizeUrl(authorizeUrl: string): boolean {
  try {
    return new URL(authorizeUrl).protocol === 'https:'
  } catch {
    return false
  }
}

export interface OAuthCallbackResult {
  code?: string
  error?: string
}

/**
 * Parse a loopback callback request URL. Returns the PKCE `code` on success, or
 * a human-readable `error` from the provider, or null when the request should be
 * ignored — wrong path, or a `solus_cb` state that doesn't match what we issued
 * (a forged/racing local request), so the genuine callback can still arrive.
 */
export function parseOAuthCallback(
  requestUrl: string,
  expectedState: string,
  base = LOOPBACK_BASE
): OAuthCallbackResult | null {
  let url: URL
  try {
    url = new URL(requestUrl, base)
  } catch {
    return null
  }
  if (url.pathname !== OAUTH_CALLBACK_PATH) return null
  if (url.searchParams.get('solus_cb') !== expectedState) return null

  const error = url.searchParams.get('error_description') ?? url.searchParams.get('error')
  if (error) return { error }

  const code = url.searchParams.get('code')
  if (code) return { code }

  return { error: 'No authorization code in callback' }
}
