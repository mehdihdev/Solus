import { describe, expect, test } from 'vitest'
import { DEFAULT_API_BASE_URL, apiOriginForCsp, widenConnectSrc } from './cspConnect'

describe('apiOriginForCsp', () => {
  test('returns the origin of a configured API base URL', () => {
    expect(apiOriginForCsp('http://127.0.0.1:8000/api/v1')).toBe('http://127.0.0.1:8000')
  })

  test('keeps the https origin (and port) of a packaged prod API', () => {
    expect(apiOriginForCsp('https://api.solus.dev/api/v1')).toBe('https://api.solus.dev')
    expect(apiOriginForCsp('https://api.solus.dev:8443/api/v1')).toBe('https://api.solus.dev:8443')
  })

  test('falls back to the client default origin when unset or blank', () => {
    const defaultOrigin = new URL(DEFAULT_API_BASE_URL).origin
    expect(apiOriginForCsp(undefined)).toBe(defaultOrigin)
    expect(apiOriginForCsp('   ')).toBe(defaultOrigin)
  })

  test('returns null for an unparseable value', () => {
    expect(apiOriginForCsp('not a url')).toBeNull()
  })
})

describe('widenConnectSrc', () => {
  const CSP =
    "content=\"default-src 'self'; " +
    "connect-src 'self' https://*.supabase.co wss://*.supabase.co\""

  test('adds the API origin to connect-src', () => {
    const out = widenConnectSrc(CSP, 'http://127.0.0.1:8000')
    expect(out).toContain(
      "connect-src 'self' https://*.supabase.co wss://*.supabase.co http://127.0.0.1:8000\""
    )
  })

  test('is idempotent — never double-adds an already-listed origin', () => {
    const once = widenConnectSrc(CSP, 'http://127.0.0.1:8000')
    const twice = widenConnectSrc(once, 'http://127.0.0.1:8000')
    expect(twice).toBe(once)
  })

  test('leaves other directives untouched', () => {
    const out = widenConnectSrc(CSP, 'http://127.0.0.1:8000')
    expect(out).toContain("default-src 'self';")
  })

  test('is a no-op when origin is null', () => {
    expect(widenConnectSrc(CSP, null)).toBe(CSP)
  })

  test('is a no-op when there is no connect-src directive', () => {
    const html = '<meta content="default-src \'self\'" />'
    expect(widenConnectSrc(html, 'http://127.0.0.1:8000')).toBe(html)
  })

  // Regression: index.html has an HTML comment that mentions "connect-src" BEFORE
  // the real directive. The match must anchor on content="..." and never corrupt
  // the comment or an unrelated attribute (SOLUSDEV-152).
  test('ignores a "connect-src" mention in a comment and widens only the directive', () => {
    const html = [
      '<!-- connect-src widened for Supabase Auth; add the API origin here -->',
      '<meta http-equiv="Content-Security-Policy"',
      "  content=\"default-src 'self'; connect-src 'self' https://*.supabase.co\" />"
    ].join('\n')
    const out = widenConnectSrc(html, 'http://127.0.0.1:8000')
    // Comment line is untouched; http-equiv attribute is untouched.
    expect(out).toContain('<!-- connect-src widened for Supabase Auth; add the API origin here -->')
    expect(out).toContain('http-equiv="Content-Security-Policy"')
    // Only the real directive gains the origin.
    expect(out).toContain("connect-src 'self' https://*.supabase.co http://127.0.0.1:8000\"")
  })
})
