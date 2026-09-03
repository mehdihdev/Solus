// SOLUSDEV-235 / EXT-12 — net.fetch body codecs (§6.5 text vs base64).
import { describe, it, expect } from 'vitest'
import { base64ToBytes, decodeNetBody, utf8ToBase64 } from './net'

describe('net body codecs', () => {
  it('round-trips UTF-8 through base64', () => {
    const text = 'héllo — 😀 {"k":1}'
    const b64 = utf8ToBase64(text)
    expect(new TextDecoder().decode(base64ToBytes(b64))).toBe(text)
  })

  it('handles bodies larger than the chunking stride', () => {
    const text = 'x'.repeat(100_000)
    expect(new TextDecoder().decode(base64ToBytes(utf8ToBase64(text)))).toBe(text)
  })

  it.each([
    'application/json',
    'application/json; charset=utf-8',
    'text/plain',
    'text/html',
    'application/vnd.api+json',
    'application/xml',
    'application/problem+xml',
    'application/x-www-form-urlencoded',
    'application/javascript'
  ])('decodes %s as text', (contentType) => {
    expect(decodeNetBody(btoa('abc'), contentType)).toEqual({ body: 'abc', encoding: 'text' })
  })

  it.each(['image/png', 'application/octet-stream', 'application/zip', undefined])(
    'returns %s as base64',
    (contentType) => {
      expect(decodeNetBody('YWJj', contentType)).toEqual({ body: 'YWJj', encoding: 'base64' })
    }
  )
})
