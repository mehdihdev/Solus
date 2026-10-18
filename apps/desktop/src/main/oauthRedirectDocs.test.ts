import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { connectorRedirectUrl } from './oauthCallback'

const CALLBACK_URL_PATTERN = /https?:\/\/[^\s`|)]+:53682\/auth\/callback/g

function extractCallbackUrls(text: string): string[] {
  return text.match(CALLBACK_URL_PATTERN) ?? []
}

const DOC_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../../../docs/integrations/github-setup.md'
)

describe('github-setup.md connector redirect URL', () => {
  const doc = readFileSync(DOC_PATH, 'utf8')

  it('documents at least one callback URL', () => {
    expect(extractCallbackUrls(doc).length).toBeGreaterThan(0)
  })

  it('only documents the exact URL connectorRedirectUrl() returns', () => {
    for (const url of extractCallbackUrls(doc)) {
      expect(url).toBe(connectorRedirectUrl())
    }
  })

  it('never mentions the 127.0.0.1 loopback host', () => {
    expect(doc).not.toContain('127.0.0.1:53682')
  })
})

describe('extractCallbackUrls', () => {
  it('catches a 127.0.0.1 URL so the equality check would fail', () => {
    const urls = extractCallbackUrls('| URL | `http://127.0.0.1:53682/auth/callback` |')
    expect(urls).toEqual(['http://127.0.0.1:53682/auth/callback'])
    expect(urls[0]).not.toBe(connectorRedirectUrl())
  })
})
