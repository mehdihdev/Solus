// SOLUSDEV-311: one bug, one fingerprint — across rebuilds and changing numbers.
import { describe, it, expect } from 'vitest'
import { fingerprintOf } from './fingerprint'

const VALID = {
  surface: 'bench',
  name: 'TypeError',
  message: 'boom',
  stack: 'TypeError: boom\n    at BenchScreen (bench.tsx:10:5)'
}

describe('fingerprintOf', () => {
  it('is 16 lowercase hex chars', () => {
    expect(fingerprintOf(VALID)).toMatch(/^[0-9a-f]{16}$/)
  })

  it('is stable across line/column drift and message numbers (same bug, same print)', () => {
    const a = fingerprintOf({
      ...VALID,
      message: 'index 3 out of range',
      stack: 'E\n    at f (a.js:10:5)'
    })
    const b = fingerprintOf({
      ...VALID,
      message: 'index 7 out of range',
      stack: 'E\n    at f (a.js:12:9)'
    })
    expect(a).toBe(b)
  })

  it('differs by error name, surface and throwing function', () => {
    const base = fingerprintOf(VALID)
    expect(fingerprintOf({ ...VALID, name: 'RangeError' })).not.toBe(base)
    expect(fingerprintOf({ ...VALID, surface: 'sol' })).not.toBe(base)
    expect(
      fingerprintOf({ ...VALID, stack: 'TypeError: boom\n    at SolScreen (sol.tsx:1:1)' })
    ).not.toBe(base)
  })
})
