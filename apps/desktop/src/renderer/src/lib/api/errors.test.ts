// The distinction this file exists to protect: "the thing you asked for is gone"
// is not "we could not ask". Collapsing the two is what made the Team screen tell
// a user to go check their backend while that backend was answering every request.
import { describe, it, expect } from 'vitest'
import { ApiError } from './envelope.types'
import { classifyFetchError } from './errors'

describe('classifyFetchError', () => {
  it('calls a 404 gone — the resource is missing, not the server', () => {
    expect(classifyFetchError(new ApiError(404, 'not_found', 'No such team'))).toBe('gone')
  })

  it('calls 401 and 403 unauthorized', () => {
    expect(classifyFetchError(new ApiError(401, 'unauthorized', 'nope'))).toBe('unauthorized')
    expect(classifyFetchError(new ApiError(403, 'forbidden', 'nope'))).toBe('unauthorized')
  })

  it('calls a 5xx unreachable — the server answered, but told us nothing usable', () => {
    // Deliberately NOT 'gone': a 500 while fetching a project must never be read
    // as "this project was deleted", or a blip would discard a good reference.
    expect(classifyFetchError(new ApiError(500, 'server_error', 'boom'))).toBe('unreachable')
    expect(classifyFetchError(new ApiError(503, 'unavailable', 'boom'))).toBe('unreachable')
  })

  it('calls a network failure unreachable', () => {
    expect(classifyFetchError(new TypeError('Failed to fetch'))).toBe('unreachable')
  })

  it('defaults anything unrecognisable to unreachable, never to gone', () => {
    // The safe default is the one that changes nothing. "gone" causes the app to
    // DISCARD state, so an unknown error must never reach it.
    for (const junk of [undefined, null, 'a string', 42, {}, new Error('?')]) {
      expect(classifyFetchError(junk)).toBe('unreachable')
    }
  })

  it('treats other 4xx as unreachable rather than guessing', () => {
    // 400/409/422 mean we asked wrongly — that is a bug to fix, not a signal that
    // the resource vanished, and not a reason to claim the backend is down either.
    expect(classifyFetchError(new ApiError(409, 'conflict', 'x'))).toBe('unreachable')
  })

  it('is not fooled by a plain object that merely looks like an ApiError', () => {
    // Only a real ApiError carries a status the client actually parsed.
    expect(classifyFetchError({ status: 404, code: 'not_found' })).toBe('unreachable')
  })
})
