import { describe, it, expect } from 'vitest'
import {
  mergePresence,
  settingsStagger,
  SETTINGS_STAGGER_CAP,
  SETTINGS_STAGGER_MS
} from './settingsMotion'

const key = (s: string): string => s

describe('settingsStagger', () => {
  it('delays each row a little more, capped so long lists never drag', () => {
    expect(settingsStagger(0)).toEqual({ animationDelay: '0ms' })
    expect(settingsStagger(2)).toEqual({ animationDelay: `${2 * SETTINGS_STAGGER_MS}ms` })
    expect(settingsStagger(99)).toEqual({
      animationDelay: `${SETTINGS_STAGGER_CAP * SETTINGS_STAGGER_MS}ms`
    })
  })
})

describe('mergePresence', () => {
  it('shows new items as entering, none leaving', () => {
    expect(mergePresence([], ['a', 'b'], key)).toEqual([
      { key: 'a', item: 'a', leaving: false },
      { key: 'b', item: 'b', leaving: false }
    ])
  })

  it('keeps a removed item in place, marked leaving, so it can animate out', () => {
    const before = mergePresence([], ['a', 'b', 'c'], key)
    expect(mergePresence(before, ['a', 'c'], key)).toEqual([
      { key: 'a', item: 'a', leaving: false },
      { key: 'b', item: 'b', leaving: true },
      { key: 'c', item: 'c', leaving: false }
    ])
  })

  it('brings a leaving item back when it reappears', () => {
    const leaving = mergePresence(mergePresence([], ['a'], key), [], key)
    expect(mergePresence(leaving, ['a'], key)).toEqual([{ key: 'a', item: 'a', leaving: false }])
  })

  it('takes the latest value of an item that stays', () => {
    const before = mergePresence([], [{ id: 1, n: 'old' }], (x) => String(x.id))
    expect(mergePresence(before, [{ id: 1, n: 'new' }], (x) => String(x.id))[0].item.n).toBe('new')
  })
})
