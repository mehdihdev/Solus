// SOLUSDEV-319: the words and order Home's team rail and overview share.
import { describe, expect, it } from 'vitest'
import type { TeamSummary } from '../../lib/api/resources'
import { railOrder, roleLabel, teamInitials, teamLimitText, withArticle } from './teamLabels'

const team = (id: string, personal = false): TeamSummary => ({
  team_id: id,
  name: id,
  role: 'member',
  is_personal: personal,
  plan_status: 'active',
  trial_ends_at: ''
})

describe('teamLabels', () => {
  it('puts collaborative teams first, in API order, and the personal workspace last', () => {
    expect(railOrder([team('me', true), team('a'), team('b')]).map((t) => t.team_id)).toEqual([
      'a',
      'b',
      'me'
    ])
  })

  it('capitalises a role', () => {
    expect(roleLabel('owner')).toBe('Owner')
    expect(roleLabel('viewer')).toBe('Viewer')
  })

  it('picks the article a role needs', () => {
    expect(withArticle('Member')).toBe('a Member')
    expect(withArticle('Admin')).toBe('an Admin')
    expect(withArticle('Owner')).toBe('an Owner')
    expect(withArticle('Viewer')).toBe('a Viewer')
  })

  it('takes two initials from a team name', () => {
    expect(teamInitials('Arm Lab')).toBe('AL')
    expect(teamInitials('FSAE Robotics Club')).toBe('FR')
    expect(teamInitials('strider')).toBe('ST')
    expect(teamInitials('  ')).toBe('?')
  })

  it('states the plan position only when the limit is known', () => {
    expect(teamLimitText({ current: 1, max: 2, atLimit: false })).toBe(
      '1 of 2 collaborative teams on your plan · your personal team never counts'
    )
    expect(teamLimitText(null)).toBeNull()
    expect(teamLimitText({ current: 5, max: null, atLimit: false })).toBeNull()
  })
})
