// SOLUSDEV-311: nothing that leaves the renderer for a log line or Sentry may
// carry a token, an email, a query string or the user's home path.
import { describe, it, expect } from 'vitest'
import { scrubText, scrubReport } from './scrub'

const HOME = '/Users/ada'
// Token-shaped fixtures are assembled at runtime so the repo's secret scanner
// (hook H3 / CI) never sees a literal credential pattern in source.
const fake = (prefix: string, body = 'abcdefghijklmnopqrstuvwx0123'): string => prefix + body

describe('scrubText', () => {
  it.each([
    ['a JWT', `token ${fake('eyJ', 'hbGc.eyJzdWIi.sig-abc_1')} expired`, 'token [jwt] expired'],
    [
      'a bearer header',
      'Authorization: Bearer abc.def-123 failed',
      'Authorization: Bearer [redacted] failed'
    ],
    ['a Stripe key', `bad key ${fake('sk_' + 'live_')}`, 'bad key [secret]'],
    ['a Supabase key', `${fake('sb_' + 'secret_')} leaked`, '[secret] leaked'],
    ['a GitHub token', `${fake('gh' + 'p_')} used`, '[secret] used'],
    ['a GitLab token', `${fake('glp' + 'at-')} used`, '[secret] used'],
    ['an email', 'no user ada@example.com here', 'no user [email] here'],
    [
      'a URL query string',
      'GET https://api.solus.dev/v1/x?code=abc&y=1 failed',
      'GET https://api.solus.dev/v1/x?[redacted] failed'
    ],
    [
      'a URL fragment after the hash route',
      'at http://localhost:5173/#/login#code=zz',
      'at http://localhost:5173/#/login#[redacted]'
    ],
    ['the home path', `at ${HOME}/Solus/out/main/index.js:4`, 'at ~/Solus/out/main/index.js:4'],
    ['another macOS user dir', 'open /Users/bob/secret.kicad_pcb', 'open ~/secret.kicad_pcb'],
    ['a Windows user dir', 'C:\\Users\\bob\\Solus\\x.js', '~\\Solus\\x.js'],
    ['a Linux home dir', '/home/bob/solus/x.js', '~/solus/x.js']
  ])('redacts %s', (_label, input, expected) => {
    expect(scrubText(input, HOME)).toBe(expected)
  })

  it('keeps an ordinary error message intact', () => {
    const msg = "Cannot read properties of undefined (reading 'joints')"
    expect(scrubText(msg, HOME)).toBe(msg)
  })

  it('keeps the hash route of a plain URL (no secret after the #)', () => {
    expect(scrubText('at http://localhost:5173/#/', HOME)).toBe('at http://localhost:5173/#/')
  })
})

describe('scrubReport', () => {
  it('scrubs and truncates every free-text field, keeping the closed fields', () => {
    const out = scrubReport(
      {
        origin: 'render',
        surface: 'bench',
        name: 'TypeError',
        message: `boom ada@example.com ${'x'.repeat(2_000)}`,
        stack: `TypeError: boom\n    at ${HOME}/a.js:1:2`,
        componentStack: '\n    at BenchScreen'
      },
      HOME
    )
    expect(out.origin).toBe('render')
    expect(out.surface).toBe('bench')
    expect(out.message.startsWith('boom [email] ')).toBe(true)
    expect(out.message.length).toBeLessThanOrEqual(1_000)
    expect(out.stack).toBe('TypeError: boom\n    at ~/a.js:1:2')
    expect(out.componentStack).toBe('\n    at BenchScreen')
  })
})
