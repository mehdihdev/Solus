// SOLUSDEV-317 (design A, "one roster"): who the People table lists, how each
// teammate's GitHub link reads, and what the filters and search keep.
import { describe, expect, it } from 'vitest'
import type { InviteApi, TeamMemberApi } from '../../lib/api/resources'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import {
  ADA,
  ASSIGNED,
  FREE,
  INVITED,
  NOOR,
  SAM,
  VERIFIED
} from '../workspace/githubOrgRoster.fixtures'
import { buildRoster, filterRoster, memberLink, rosterFilters, summaryCounts } from './rosterModel'

const EMAIL_INVITE: InviteApi = {
  id: 'i1',
  team_id: 't1',
  email: 'dev@team.dev',
  role: 'member',
  status: 'pending',
  created_at: '2026-10-17T00:00:00Z',
  expires_at: '2026-10-24T00:00:00Z'
}
const GH_INVITE: InviteApi = {
  ...EMAIL_INVITE,
  id: 'i2',
  email: null,
  github_user_id: 10,
  github_login: 'pending-pat'
}
const OTHER_INVITED: GithubOrgMember = { ...INVITED, github_id: 11, github_login: 'other-inv' }
const ROSTER = [FREE, ASSIGNED, VERIFIED, INVITED, OTHER_INVITED]
const TEAM = [ADA, NOOR, SAM]

describe('buildRoster', () => {
  it('lists teammates, then invites, then org members not on the team', () => {
    const rows = buildRoster(TEAM, [EMAIL_INVITE, GH_INVITE], ROSTER)
    expect(rows.map((r) => `${r.kind}:${r.key}`)).toEqual([
      'member:u1',
      'member:u2',
      'member:u3',
      'invite:i1',
      'invite:i2',
      'org:7',
      'org:11'
    ])
  })

  it('never lists an org member twice: a GitHub invite row stands for them', () => {
    const rows = buildRoster(TEAM, [GH_INVITE], ROSTER)
    expect(rows.filter((r) => r.kind === 'org').map((r) => r.key)).toEqual(['7', '11'])
  })

  it('has no org rows without a roster (non-managers, no link)', () => {
    expect(buildRoster(TEAM, [], null).some((r) => r.kind === 'org')).toBe(false)
  })
})

describe('memberLink', () => {
  it('prefers the roster (fresh, optimistic) over the members list', () => {
    const stale: TeamMemberApi = { ...ADA, github: null }
    const roster = [{ ...FREE, assignment: { ...ASSIGNED.assignment!, user_id: 'u1' } }]
    expect(memberLink(stale, roster)).toMatchObject({ githubId: 7, login: 'octo', source: 'admin' })
  })

  it('falls back to the members list, then to none', () => {
    expect(memberLink(SAM, null)).toMatchObject({ githubId: 9, login: 'sam-v', source: 'verified' })
    expect(memberLink(ADA, null)).toBeNull()
  })

  it('drops a link the loaded roster no longer has, keeps one on an unloaded page', () => {
    const unlinked = [{ ...ASSIGNED, assignment: null, solus_status: 'not_on_solus' as const }]
    expect(memberLink(NOOR, unlinked)).toBeNull()
    expect(memberLink(NOOR, [FREE])).toMatchObject({ githubId: 8, source: 'admin' })
  })

  it('carries who assigned it when the roster knows', () => {
    expect(memberLink(NOOR, ROSTER)?.assignedBy).toBe('Ada')
  })
})

describe('filterRoster', () => {
  const rows = buildRoster(TEAM, [EMAIL_INVITE], ROSTER)
  it.each([
    ['Team', ['u1', 'u2', 'u3']],
    ['Invites', ['i1']],
    ['Not on Solus', ['7', '10', '11']],
    ['No GitHub', ['u1']]
  ] as const)('%s', (filter, keys) => {
    expect(filterRoster(rows, filter, '', ROSTER).map((r) => r.key)).toEqual(keys)
  })

  it('a leading @ searches logins as written', () => {
    expect(filterRoster(rows, 'Everyone', '@oct', ROSTER).map((r) => r.key)).toEqual(['7'])
  })

  it('searches names, emails and logins', () => {
    expect(filterRoster(rows, 'Everyone', 'NOOR', ROSTER).map((r) => r.key)).toEqual(['u2'])
    expect(filterRoster(rows, 'Everyone', 'oct', ROSTER).map((r) => r.key)).toEqual(['7'])
    expect(filterRoster(rows, 'Everyone', 'dev@', ROSTER).map((r) => r.key)).toEqual(['i1'])
  })
})

describe('filters and counts', () => {
  it('offers "Not on Solus" only with a roster', () => {
    expect(rosterFilters(true)).toContain('Not on Solus')
    expect(rosterFilters(false)).not.toContain('Not on Solus')
  })

  it('counts members, pending invites and org members not on the team', () => {
    const rows = buildRoster(TEAM, [EMAIL_INVITE, GH_INVITE], ROSTER)
    expect(summaryCounts(rows)).toEqual({ members: 3, invites: 2, outside: 2 })
  })
})
