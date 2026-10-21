// SOLUSDEV-317: who each GitHub link picker on the People table offers.
import { describe, expect, it } from 'vitest'
import { ADA, ASSIGNED, FREE, INVITED, NOOR, SAM, VERIFIED } from './githubOrgRoster.fixtures'
import { orgMemberOptions, teammateOptions } from './githubOrgMembersView'

const ROSTER = [FREE, ASSIGNED, VERIFIED, INVITED]
const TEAM = [ADA, NOOR, SAM]

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

describe('orgMemberOptions', () => {
  it('offers only unlinked org members to a teammate', () => {
    expect(orgMemberOptions(ROSTER)).toEqual([
      { id: '7', label: '@octo', detail: 'Not on Solus', disabled: false },
      { id: '10', label: '@pending-pat', detail: 'Invited', disabled: false }
    ])
  })
})
