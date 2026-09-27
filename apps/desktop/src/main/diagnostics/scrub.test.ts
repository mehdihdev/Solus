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

describe('scrubText — formats the first pass missed (security review H3)', () => {
  it.each([
    [
      'a truncated two-segment JWT',
      `token=${fake('eyJ', 'hbGciOiJI')}.${fake('eyJ', 'zdWIiOiIx')}`,
      'token=[jwt]'
    ],
    ['a JWT glued to a word', `x_${fake('eyJ', 'hbGc.eyJzdWIi.sig')}`, 'x_[jwt]'],
    ['a GitHub fine-grained PAT', `${fake('github_' + 'pat_')} used`, '[secret] used'],
    ['a GitLab deploy token', `${fake('gl' + 'dt-')} used`, '[secret] used'],
    ['a GitLab runner token', `${fake('gl' + 'rt-')} used`, '[secret] used'],
    ['a Stripe webhook secret', `${fake('wh' + 'sec_')} bad`, '[secret] bad'],
    ['an Anthropic key', `${fake('sk-' + 'ant-')} bad`, '[secret] bad'],
    ['an OpenAI project key', `${fake('sk-' + 'proj-')} bad`, '[secret] bad'],
    ['an AWS access key id', `key ${'AK' + 'IA'}ABCDEFGHIJKLMNOP`, 'key [secret]'],
    ['a Basic auth header', 'Authorization: Basic dXNlcjpwYXNz', 'Authorization: Basic [redacted]'],
    ['a Supabase key with a hyphen', `${fake('sb_' + 'secret_', 'abc-def_ghi')} x`, '[secret] x'],
    [
      'a relative URL query',
      'GET /api/v1/projects?access_token=abc123 failed',
      'GET /api/v1/projects?[redacted] failed'
    ],
    ['a schemeless hash fragment', 'at #/login#access_token=zz', 'at #/login#[redacted]'],
    ['a JSON refresh token', '{"refresh_token":"f9Xk2LmQpR7s"}', '{"refresh_token":"[redacted]"}'],
    ['a password assignment', 'password=hunter2 rejected', 'password=[redacted] rejected'],
    ['an api key assignment', "api_key: 'k-123'", "api_key: '[redacted]'"],
    ['a percent-encoded email', 'user=john%40example.com', 'user=[email]'],
    ['a percent-encoded home path', 'file=%2FUsers%2Fjdoe%2Fx.step', 'file=~%2Fx.step'],
    ['a JSON-escaped Windows home', '"C:\\\\Users\\\\jdoe\\\\x"', '"~\\\\x"'],
    ['the root home', 'open /root/.ssh/id', 'open ~/.ssh/id']
  ])('redacts %s', (_label, input, expected) => {
    expect(scrubText(input, HOME)).toBe(expected)
  })

  it('keeps diagnostic codes that are not secrets', () => {
    const msg = 'connect ECONNREFUSED 127.0.0.1:8000 (code=ECONNREFUSED, status 503)'
    expect(scrubText(msg, HOME)).toBe(msg)
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
