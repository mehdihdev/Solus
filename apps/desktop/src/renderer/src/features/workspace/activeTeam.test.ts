import { describe, it, expect } from 'vitest'
import { resolveTeam, resolveTeamId } from './activeTeam'
import type { Me, TeamSummary } from '../../lib/api/resources'

function team(id: string, is_personal = false): TeamSummary {
  return {
    team_id: id,
    name: id,
    role: 'owner',
    is_personal,
    plan_status: 'trial',
    trial_ends_at: ''
  }
}
const ME: Me = {
  id: 'u1',
  email: 'maya@example.dev',
  name: 'Maya',
  avatar_url: null,
  created_at: '',
  teams: [team('t-personal', true), team('t-lab')]
}

describe('resolveTeamId', () => {
  it('keeps a stored id that is still one of my teams', () => {
    expect(resolveTeamId(ME, 't-lab')).toBe('t-lab')
  })
  it('falls back to the personal team when the stored id is not mine', () => {
    expect(resolveTeamId(ME, 't-ghost')).toBe('t-personal')
  })
  it('falls back to the personal team when nothing is stored', () => {
    expect(resolveTeamId(ME, null)).toBe('t-personal')
  })
  it('falls back to the first team when there is no personal team', () => {
    expect(resolveTeamId({ ...ME, teams: [team('t-lab')] }, null)).toBe('t-lab')
  })
  it('is null without a profile or without teams', () => {
    expect(resolveTeamId(null, 't-lab')).toBe(null)
    expect(resolveTeamId({ ...ME, teams: [] }, 't-lab')).toBe(null)
  })
})

describe('resolveTeam', () => {
  it('returns the summary of the resolved team', () => {
    expect(resolveTeam(ME, 't-lab')?.name).toBe('t-lab')
    expect(resolveTeam(ME, 'nope')?.name).toBe('t-personal')
    expect(resolveTeam(null, 't-lab')).toBe(null)
  })
})
