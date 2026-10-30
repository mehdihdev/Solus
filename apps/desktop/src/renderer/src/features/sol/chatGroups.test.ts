import { describe, expect, it } from 'vitest'
import { groupChats } from './chatGroups'
import type { SolConversation } from './solApi'

const at = (id: string, updated: string, created = updated): SolConversation => ({
  id,
  project_id: 'p1',
  title: id,
  created_by: 'u1',
  created_at: created,
  updated_at: updated
})

// Noon local time, so "same calendar day" is unambiguous across zones.
const NOW = new Date(2026, 9, 24, 12, 0, 0).getTime()
const hoursAgo = (h: number): string => new Date(NOW - h * 3600_000).toISOString()

describe('groupChats', () => {
  it('buckets by last activity: same day, under a week, earlier — in that order, no empties', () => {
    const groups = groupChats(
      [
        at('a', hoursAgo(1)),
        at('b', hoursAgo(9 * 24)),
        at('c', hoursAgo(3 * 24)),
        at('d', hoursAgo(11))
      ],
      NOW
    )
    expect(groups.map((g) => g.label)).toEqual(['TODAY', 'THIS WEEK', 'EARLIER'])
    expect(groups[0].items.map((c) => c.id)).toEqual(['a', 'd'])
    expect(groups[1].items.map((c) => c.id)).toEqual(['c'])
    expect(groups[2].items.map((c) => c.id)).toEqual(['b'])
  })

  it('late last night is yesterday, not today; 6 days is this week, 8 is earlier', () => {
    const lastNight = new Date(2026, 9, 23, 23, 30).toISOString()
    const groups = groupChats(
      [at('x', lastNight), at('y', hoursAgo(6 * 24)), at('z', hoursAgo(8 * 24))],
      NOW
    )
    expect(groups.map((g) => g.label)).toEqual(['THIS WEEK', 'EARLIER'])
    expect(groups[0].items.map((c) => c.id)).toEqual(['x', 'y'])
  })

  it('falls back to created_at when updated_at is empty, and handles an empty list', () => {
    expect(groupChats([at('a', '', hoursAgo(2))], NOW)[0].label).toBe('TODAY')
    expect(groupChats([], NOW)).toEqual([])
  })
})
