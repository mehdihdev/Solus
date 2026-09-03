// SOLUSDEV-235 / EXT-12 — §6.4 error mapping: fixed host messages, never a server body.
import { describe, it, expect } from 'vitest'
import { ApiError } from '../../../lib/api/envelope.types'
import { BRIDGE_MESSAGES, BridgeFault, bridgeError, toBridgeError } from './bridgeErrors'

describe('toBridgeError', () => {
  it.each([
    [403, 'scope_denied', 'scope_denied'],
    [403, 'extension_blocked', 'blocked'],
    [413, 'storage_quota_exceeded', 'storage_quota'],
    [413, 'payload_too_large', 'invalid_params'],
    [422, 'validation_error', 'invalid_params'],
    [429, 'rate_limited', 'rate_limited'],
    [404, 'not_found', 'invalid_params'],
    [403, 'forbidden', 'blocked'],
    [401, 'unauthorized', 'unavailable'],
    [500, 'internal_error', 'unavailable'],
    [402, 'insufficient_credits', 'unavailable']
  ])('maps HTTP %s %s → %s', (status, apiCode, expected) => {
    const mapped = toBridgeError(new ApiError(status, apiCode, 'SERVER SAID: secret detail'))
    expect(mapped.code).toBe(expected)
    expect(mapped.message).not.toContain('secret')
  })

  it('never echoes the server message', () => {
    const mapped = toBridgeError(
      new ApiError(422, 'validation_error', 'projectId 019e… is invalid')
    )
    expect(mapped.message).toBe(BRIDGE_MESSAGES.invalid_params)
  })

  it('a transport failure is unavailable; an unknown throw is internal', () => {
    expect(toBridgeError(new TypeError('Failed to fetch')).code).toBe('unavailable')
    expect(toBridgeError(new DOMException('aborted', 'AbortError')).code).toBe('unavailable')
    expect(toBridgeError(new Error('boom')).code).toBe('internal')
    expect(toBridgeError('string').code).toBe('internal')
    expect(toBridgeError(new Error('boom')).message).not.toContain('boom')
  })

  it('a BridgeFault carries its own code and fixed message', () => {
    expect(toBridgeError(new BridgeFault('network_denied', 'response too large'))).toEqual({
      code: 'network_denied',
      message: 'response too large'
    })
    expect(toBridgeError(new BridgeFault('storage_quota'))).toEqual(bridgeError('storage_quota'))
  })
})
