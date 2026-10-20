// SOLUSDEV-317: what the GITHUB ORG MEMBERS section shows — filters, search,
// the header counts, and who each picker offers.
import { describe, expect, it } from 'vitest'
import { ADA, ASSIGNED, FREE, INVITED, NOOR, SAM, VERIFIED } from './githubOrgRoster.fixtures'
import {
  filterOrgMembers,
  onTeamCount,
  orgMemberOptions,
  rowKind,
  teammateOptions,
  unassignedTeammates
} from './githubOrgMembersView'

const ROSTER = [FREE, ASSIGNED, VERIFIED, INVITED]
const TEAM = [ADA, NOOR, SAM]

describe('filterOrgMembers', () => {
  it.each([
    ['All', [7, 8, 9, 10]],
    ['On team', [8, 9]],
    ['Not on Solus', [7, 10]]
  ] as const)('%s', (filter, ids) => {
    expect(filterOrgMembers(ROSTER, filter, '').map((m) => m.github_id)).toEqual(ids)
  })

  it('searches logins case-insensitively over the loaded rows', () => {
    expect(filterOrgMembers(ROSTER, 'All', ' NOOR ').map((m) => m.github_id)).toEqual([8])
  })
})

describe('row kind and counts', () => {
  it('derives the chip from the assignment first, then the Solus status', () => {
    expect(ROSTER.map(rowKind)).toEqual(['not_on_solus', 'assigned', 'verified', 'invited'])
  })

  it('counts the loaded rows that are on the team', () => {
    expect(onTeamCount(ROSTER)).toBe(2)
  })
})

describe('teammateOptions (picker on an org row)', () => {
  it('offers free teammates, disables verified ones with their login, hides assigned ones', () => {
    const options = teammateOptions(TEAM, ROSTER, FREE)
    expect(options).toEqual([
      { id: 'u1', label: 'Ada', detail: 'ada@team.dev', disabled: false },
      { id: 'u3', label: 'Sam', detail: '@sam-v · verified', disabled: true }
    ])
  })

  it('never shows the email twice: a nameless teammate gets their role as the detail', () => {
    const nameless = { ...ADA, name: null }
    expect(teammateOptions([nameless], [], FREE)).toEqual([
      { id: 'u1', label: 'ada@team.dev', detail: 'Owner', disabled: false }
    ])
  })

  it('keeps the current assignee on the row being changed', () => {
    const ids = teammateOptions(TEAM, ROSTER, ASSIGNED).map((o) => o.id)
    expect(ids).toContain('u2')
  })

  it('hides a teammate the roster just assigned elsewhere (before members refetch)', () => {
    const roster = [{ ...FREE, assignment: { ...ASSIGNED.assignment!, user_id: 'u1' } }]
    expect(teammateOptions([ADA], roster, INVITED)).toEqual([])
  })
})

describe('teammate side', () => {
  it('lists teammates with no GitHub link', () => {
    expect(unassignedTeammates(TEAM, ROSTER, '').map((m) => m.user_id)).toEqual(['u1'])
  })

  it('searches teammates by name or email', () => {
    expect(unassignedTeammates(TEAM, ROSTER, 'zzz')).toEqual([])
    expect(unassignedTeammates(TEAM, ROSTER, 'ADA@')).toHaveLength(1)
  })

  it('offers only unlinked org members to a teammate', () => {
    expect(orgMemberOptions(ROSTER)).toEqual([
      { id: '7', label: '@octo', detail: 'Not on Solus', disabled: false },
      { id: '10', label: '@pending-pat', detail: 'Invited', disabled: false }
    ])
  })
})
