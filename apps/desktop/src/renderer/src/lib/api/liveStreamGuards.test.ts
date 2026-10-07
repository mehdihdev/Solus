import { describe, expect, it } from 'vitest'
import { hasExactKeys, isNonNegativeInt, isNullableString, isString } from './liveStreamGuards'

describe('liveStreamGuards', () => {
  it('hasExactKeys requires the same key set, no more and no fewer', () => {
    expect(hasExactKeys({ a: 1, b: 2 }, ['a', 'b'])).toBe(true)
    expect(hasExactKeys({ a: 1 }, ['a', 'b'])).toBe(false)
    expect(hasExactKeys({ a: 1, b: 2, c: 3 }, ['a', 'b'])).toBe(false)
  })
  it('string guards', () => {
    expect(isString('x')).toBe(true)
    expect(isString(1)).toBe(false)
    expect(isNullableString(null)).toBe(true)
    expect(isNullableString(undefined)).toBe(false)
  })
  it('isNonNegativeInt rejects floats, negatives, NaN and strings', () => {
    expect(isNonNegativeInt(0)).toBe(true)
    expect(isNonNegativeInt(7)).toBe(true)
    for (const bad of [-1, 1.5, Number.NaN, Infinity, '1', null])
      expect(isNonNegativeInt(bad)).toBe(false)
  })
})
