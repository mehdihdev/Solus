import { describe, it, expect } from 'vitest'
import {
  loopbackRedirectUrl,
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
})
