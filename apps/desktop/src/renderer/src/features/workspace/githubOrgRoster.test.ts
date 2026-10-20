// SOLUSDEV-317: the roster's pure row updates and refusal mapping.
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import { ADA, ASSIGNED, FREE, NOOR, SERVER_ASSIGNMENT } from './githubOrgRoster.fixtures'
import {
  assignRefusal,
  commonRefusal,
  optimisticAssignment,
  restoreRow,
  teammateName,
  withAssignment
} from './githubOrgRoster'

describe('githubOrgRoster', () => {
  it('replaces one row immutably', () => {
    const items = [FREE, ASSIGNED]
    const next = withAssignment(items, 7, SERVER_ASSIGNMENT, 'member')
    expect(next[0]).toEqual({ ...FREE, assignment: SERVER_ASSIGNMENT, solus_status: 'member' })
    expect(next[1]).toBe(ASSIGNED)
    expect(items[0]).toEqual(FREE)
    expect(restoreRow(next, FREE)[0]).toBe(FREE)
  })

  it('builds an admin assignment for the teammate', () => {
    expect(optimisticAssignment(NOOR)).toMatchObject({
      user_id: 'u2',
      name: 'Noor',
      source: 'admin',
      assigned_by: null
    })
  })

  it('names a teammate by email when they have no name', () => {
    expect(teammateName({ ...ADA, name: null })).toBe('ada@team.dev')
  })

  it('falls back to the teammate’s own login when the refusal names none', () => {
    const err = new ApiError(409, 'member_has_verified_github', 'm')
    expect(assignRefusal(err, FREE, NOOR).problem).toEqual({
      key: 'member_has_verified_github',
      vars: { name: 'Noor', other: 'noor-a' }
    })
  })

  it('treats a missing assignment as a quiet roster refetch', () => {
    expect(commonRefusal(new ApiError(404, 'assignment_missing', 'm'))).toEqual({
      problem: null,
      stale: 'roster'
    })
  })
})
