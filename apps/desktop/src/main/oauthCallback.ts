// Pure helpers for the loopback OAuth callback (no Electron imports, so they are
// unit-testable). The main process opens the provider URL in the system browser
// and runs a localhost server on OAUTH_LOOPBACK_PORT to catch the redirect; these
// functions build that redirect URL, validate the authorize URL, and parse the
// incoming request (with a CSRF state check).

/** Fixed loopback port — must match the entry in Supabase's redirect allowlist. */
export const OAUTH_LOOPBACK_PORT = 53682
export const OAUTH_CALLBACK_PATH = '/auth/callback'
/** Loopback host we BIND. 127.0.0.1 (not "localhost") so the socket is pinned to
 *  IPv4 loopback rather than whatever the resolver happens to return first. */
export const OAUTH_LOOPBACK_HOST = '127.0.0.1'
/** IPv6 loopback, bound alongside the above. `localhost` resolves to `::1` first
 *  on many systems, so a connector redirect written as `localhost` can arrive
 *  over IPv6 — with only the IPv4 socket open that callback is refused and the
 *  sign-in hangs. Both are loopback-only; neither is reachable off-machine. */
export const OAUTH_LOOPBACK_HOST_V6 = '::1'
/** Host used in the CONNECTOR redirect URL. Onshape's OAuth app will not accept a
 *  bare IP, so this must read `localhost` — which is exactly why both loopback
 *  addresses are bound. */
export const OAUTH_REDIRECT_HOST = 'localhost'

const LOOPBACK_BASE = `http://${OAUTH_LOOPBACK_HOST}:${OAUTH_LOOPBACK_PORT}`

/** Redirect URL the provider sends the browser back to, carrying our CSRF state.
 *  Supabase sign-in only — Supabase tolerates the extra query param. */
export function loopbackRedirectUrl(state: string, port: number = OAUTH_LOOPBACK_PORT): string {
  return `http://${OAUTH_LOOPBACK_HOST}:${port}${OAUTH_CALLBACK_PATH}?solus_cb=${encodeURIComponent(state)}`
}

/**
 * Redirect URL for CONNECTOR OAuth (GitHub/GitLab/Onshape/…): constant, with no
 * query string. Strict providers — Onshape among them — match the registered
 * redirect URI exactly, so a per-flow nonce in the URL can never match and the
 * authorize call fails with `invalid_grant` / "invalid redirect URL". Register
 * this exact value in each provider's OAuth app. CSRF is carried instead by the
 * provider's `state` param, which is the backend's server-side OAuthState token.
 */
export function connectorRedirectUrl(port: number = OAUTH_LOOPBACK_PORT): string {
  return `http://${OAUTH_REDIRECT_HOST}:${port}${OAUTH_CALLBACK_PATH}`
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

/** Which query param carries the nonce: our own for sign-in, the provider's
 *  echoed `state` for connector OAuth (whose redirect URI carries no query). */
export type StateParam = 'solus_cb' | 'state'

/**
 * Parse a loopback callback request URL. Returns the PKCE `code` on success, or
 * a human-readable `error` from the provider, or null when the request should be
 * ignored — wrong path, or a state that doesn't match what we issued (a
 * forged/racing local request), so the genuine callback can still arrive.
 */
export function parseOAuthCallback(
  requestUrl: string,
  expectedState: string,
  base = LOOPBACK_BASE,
  stateParam: StateParam = 'solus_cb'
): OAuthCallbackResult | null {
  let url: URL
  try {
    url = new URL(requestUrl, base)
  } catch {
    return null
  }
  if (url.pathname !== OAUTH_CALLBACK_PATH) return null
  if (url.searchParams.get(stateParam) !== expectedState) return null

  const error = url.searchParams.get('error_description') ?? url.searchParams.get('error')
  if (error) return { error }

  const code = url.searchParams.get('code')
  if (code) return { code }

  return { error: 'No authorization code in callback' }
}
