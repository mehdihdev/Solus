// SOL sidebar chat switcher — pure list logic (sol-sidebar.md §3, Chat switcher).
import { describe, expect, it } from 'vitest'
import type { SolConversation } from '../solApi'
import { chatTitle, filterChats, stepHighlight } from './chatSwitcherModel'

const NOW = Date.parse('2026-11-21T12:00:00Z')

function chat(id: string, title: string | null, updated_at: string): SolConversation {
  return { id, project_id: 'p1', title, created_by: 'u1', created_at: updated_at, updated_at }
}

const CHATS = [
  chat('a', 'IMU drops out with ToF', '2026-11-21T11:58:00Z'),
  chat('b', 'Gripper torque', '2026-11-18T09:00:00Z'),
  chat('c', null, '2026-11-01T09:00:00Z')
]

describe('chatTitle', () => {
  it('falls back to New chat for an empty or blank title', () => {
    expect(chatTitle(CHATS[0])).toBe('IMU drops out with ToF')
    expect(chatTitle(CHATS[2])).toBe('New chat')
    expect(chatTitle(chat('d', '   ', CHATS[0].updated_at))).toBe('New chat')
  })
})

describe('filterChats', () => {
  it('groups every chat by day when the query is empty', () => {
    const { groups, order } = filterChats(CHATS, '  ', NOW)
    expect(groups.map((g) => g.label)).toEqual(['TODAY', 'THIS WEEK', 'EARLIER'])
    expect(order.map((c) => c.id)).toEqual(['a', 'b', 'c'])
  })

  it('matches titles case-insensitively, including the fallback title', () => {
    expect(filterChats(CHATS, 'TORQUE', NOW).order.map((c) => c.id)).toEqual(['b'])
    expect(filterChats(CHATS, 'new', NOW).order.map((c) => c.id)).toEqual(['c'])
  })

  it('returns no groups when nothing matches', () => {
    expect(filterChats(CHATS, 'zzz', NOW)).toEqual({ groups: [], order: [] })
  })
})

describe('stepHighlight', () => {
  it('wraps around both ends', () => {
    expect(stepHighlight(0, 1, 3)).toBe(1)
    expect(stepHighlight(2, 1, 3)).toBe(0)
    expect(stepHighlight(0, -1, 3)).toBe(2)
  })

  it('starts from the first or last row when nothing is highlighted', () => {
    expect(stepHighlight(-1, 1, 3)).toBe(0)
    expect(stepHighlight(-1, -1, 3)).toBe(2)
  })

  it('stays at -1 on an empty list', () => {
    expect(stepHighlight(0, 1, 0)).toBe(-1)
  })
})
