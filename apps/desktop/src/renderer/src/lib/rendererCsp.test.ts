// SOLUSDEV-317: the renderer CSP (index.html) lets GitHub avatars load — the org
// card, GITHUB ORG MEMBERS and member badges — and nothing wider. Enterprise
// avatars stay blocked (the API sends avatar_url = null for those).
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, test } from 'vitest'

const html = readFileSync(resolve(__dirname, '../../index.html'), 'utf8')

function directive(name: string): string[] {
  const policy = /content="([^"]*)"/.exec(html.slice(html.indexOf('Content-Security-Policy')))
  const part = policy?.[1]
    .split(';')
    .map((d) => d.trim())
    .find((d) => d.startsWith(`${name} `))
  return part ? part.split(/\s+/).slice(1) : []
}

describe('renderer CSP', () => {
  test('img-src allows exactly self, data: and GitHub avatars', () => {
    expect(directive('img-src')).toEqual([
      "'self'",
      'data:',
      'https://avatars.githubusercontent.com'
    ])
  })

  test('scripts stay self-only', () => {
    expect(directive('script-src')).toEqual(["'self'"])
  })
})
