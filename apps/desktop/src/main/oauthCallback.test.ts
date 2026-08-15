import { describe, it, expect } from 'vitest'
import {
  loopbackRedirectUrl,
  connectorRedirectUrl,
  isValidAuthorizeUrl,
  parseOAuthCallback,
  OAUTH_LOOPBACK_PORT
} from './oauthCallback'

const STATE = 'nonce-123'

describe('loopbackRedirectUrl', () => {
  it('builds the fixed 127.0.0.1 callback URL carrying the state', () => {
    expect(loopbackRedirectUrl(STATE)).toBe(
      `http://127.0.0.1:${OAUTH_LOOPBACK_PORT}/auth/callback?solus_cb=nonce-123`
    )
  })
})

describe('connectorRedirectUrl', () => {
  // Onshape (and any strict provider) matches the registered redirect URI
  // EXACTLY, so the connector flow's URI must be constant — no per-flow nonce.
  it('is constant and carries no query string', () => {
    expect(connectorRedirectUrl()).toBe(connectorRedirectUrl())
    expect(connectorRedirectUrl()).not.toContain('?')
  })

  // Onshape's OAuth app refuses a bare IP in a redirect URL, so this must read
  // `localhost`. The loopback server binds BOTH ::1 and 127.0.0.1 to match.
  it('uses localhost, not a bare IP', () => {
    expect(connectorRedirectUrl()).toBe(`http://localhost:${OAUTH_LOOPBACK_PORT}/auth/callback`)
    expect(connectorRedirectUrl()).not.toContain('127.0.0.1')
  })
})

describe('isValidAuthorizeUrl', () => {
  it('accepts https URLs', () => {
    expect(isValidAuthorizeUrl('https://abc.supabase.co/auth/v1/authorize?provider=github')).toBe(
      true
    )
  })

  it('rejects non-https schemes and garbage', () => {
    expect(isValidAuthorizeUrl('file:///etc/passwd')).toBe(false)
    expect(isValidAuthorizeUrl('http://evil.test')).toBe(false)
    expect(isValidAuthorizeUrl('javascript:alert(1)')).toBe(false)
    expect(isValidAuthorizeUrl('not a url')).toBe(false)
  })
})

describe('parseOAuthCallback', () => {
  it('extracts the PKCE code when the state matches', () => {
    expect(parseOAuthCallback(`/auth/callback?solus_cb=${STATE}&code=abc123`, STATE)).toEqual({
      code: 'abc123'
    })
  })

  it('ignores a callback whose state does not match (forged/racing request)', () => {
    expect(parseOAuthCallback('/auth/callback?solus_cb=wrong&code=abc123', STATE)).toBeNull()
    expect(parseOAuthCallback('/auth/callback?code=abc123', STATE)).toBeNull()
  })

  it('surfaces a provider error (preferring the description) when state matches', () => {
    expect(
      parseOAuthCallback(
        `/auth/callback?solus_cb=${STATE}&error=access_denied&error_description=User+denied`,
        STATE
      )
    ).toEqual({ error: 'User denied' })
    expect(
      parseOAuthCallback(`/auth/callback?solus_cb=${STATE}&error=access_denied`, STATE)
    ).toEqual({
      error: 'access_denied'
    })
  })

  it('reports a missing code when state matches but no code is present', () => {
    expect(parseOAuthCallback(`/auth/callback?solus_cb=${STATE}`, STATE)).toEqual({
      error: 'No authorization code in callback'
    })
  })

  it('ignores unrelated paths (e.g. favicon probes)', () => {
    expect(parseOAuthCallback('/favicon.ico', STATE)).toBeNull()
    expect(parseOAuthCallback('/', STATE)).toBeNull()
  })

  it('handles a full absolute callback URL', () => {
    const full = `http://127.0.0.1:${OAUTH_LOOPBACK_PORT}/auth/callback?solus_cb=${STATE}&code=xyz`
    expect(parseOAuthCallback(full, STATE)).toEqual({ code: 'xyz' })
  })

  // Connector OAuth carries no solus_cb (the redirect URI must stay constant),
  // so it matches on the provider's `state` — which is the backend's own
  // server-side OAuthState token, a stronger nonce than the local uuid.
  describe('matching on the provider state param', () => {
    it('extracts the code when the provider state matches', () => {
      expect(
        parseOAuthCallback(`/auth/callback?state=${STATE}&code=abc`, STATE, undefined, 'state')
      ).toEqual({ code: 'abc' })
    })

    it('ignores a mismatched or absent provider state', () => {
      expect(
        parseOAuthCallback('/auth/callback?state=wrong&code=abc', STATE, undefined, 'state')
      ).toBeNull()
      expect(parseOAuthCallback('/auth/callback?code=abc', STATE, undefined, 'state')).toBeNull()
    })

    it('does not accept a solus_cb match when matching on state', () => {
      expect(
        parseOAuthCallback(`/auth/callback?solus_cb=${STATE}&code=abc`, STATE, undefined, 'state')
      ).toBeNull()
    })

    it('surfaces a provider error when the provider state matches', () => {
      expect(
        parseOAuthCallback(
          `/auth/callback?state=${STATE}&error=invalid_grant&error_description=bad+redirect`,
          STATE,
          undefined,
          'state'
        )
      ).toEqual({ error: 'bad redirect' })
    })
  })
})
