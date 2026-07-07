import { describe, it, expect } from 'vitest'
import { relativeTime } from './relativeTime'

const NOW = new Date('2026-07-07T12:00:00Z').getTime()

describe('relativeTime', () => {
  it('formats recent instants', () => {
    expect(relativeTime('2026-07-07T11:59:40Z', NOW)).toBe('now')
    expect(relativeTime('2026-07-07T11:48:00Z', NOW)).toBe('12 min ago')
    expect(relativeTime('2026-07-07T09:00:00Z', NOW)).toBe('3h ago')
    expect(relativeTime('2026-07-04T12:00:00Z', NOW)).toBe('3d ago')
    expect(relativeTime('2026-05-07T12:00:00Z', NOW)).toBe('May 7')
  })

  it('is defensive about garbage', () => {
    expect(relativeTime('not-a-date', NOW)).toBe('')
  })
})
