// SOLUSDEV-244 / HOME H5: the server's plan-limit refusal carries everything
// the UI needs to be honest — the limit, the count, the cap, the upgrade path.
// Before H5 every field was discarded and the user was told to "try again".
import { describe, expect, it } from 'vitest'
import { ApiError } from './envelope.types'
import { planLimitFromError, teamLimitPosition } from './planLimit'

const LIMIT_409 = new ApiError(
  409,
  'plan_limit_reached',
  "You're at your collaborative-team limit.",
  [
    {
      limit: 'max_teams',
      current: 2,
      max: 2,
      upgrade: '/settings/billing',
      manage_teams: '/settings/teams'
    }
  ]
)

describe('planLimitFromError', () => {
  it('reads the limit block from a 409 plan_limit_reached', () => {
    expect(planLimitFromError(LIMIT_409)).toEqual({
      limit: 'max_teams',
      current: 2,
      max: 2,
      message: "You're at your collaborative-team limit."
    })
  })

  it('is null for anything else, including a 409 with another code', () => {
    expect(planLimitFromError(new ApiError(409, 'already_member', 'x'))).toBeNull()
    expect(planLimitFromError(new ApiError(402, 'subscription_required', 'x'))).toBeNull()
    expect(planLimitFromError(new Error('boom'))).toBeNull()
    expect(planLimitFromError({ status: 409, code: 'plan_limit_reached' })).toBeNull()
  })

  it('tolerates a malformed details block (only the code is trusted)', () => {
    expect(planLimitFromError(new ApiError(409, 'plan_limit_reached', 'm', [{ nope: 1 }]))).toEqual(
      {
        limit: null,
        current: null,
        max: null,
        message: 'm'
      }
    )
    expect(planLimitFromError(new ApiError(409, 'plan_limit_reached', 'm'))).toEqual({
      limit: null,
      current: null,
      max: null,
      message: 'm'
    })
  })
})

describe('teamLimitPosition', () => {
  const teams = [
    {
      team_id: 'p',
      name: 'Me',
      role: 'owner',
      is_personal: true,
      plan_status: '',
      trial_ends_at: ''
    },
    {
      team_id: 'a',
      name: 'A',
      role: 'owner',
      is_personal: false,
      plan_status: '',
      trial_ends_at: ''
    },
    {
      team_id: 'b',
      name: 'B',
      role: 'member',
      is_personal: false,
      plan_status: '',
      trial_ends_at: ''
    }
  ]

  it('counts collaborative teams only — the personal team never counts (ADR-025)', () => {
    expect(teamLimitPosition(teams, { max_teams: 2 })).toEqual({
      current: 2,
      max: 2,
      atLimit: true
    })
    expect(teamLimitPosition(teams.slice(0, 2), { max_teams: 2 })).toEqual({
      current: 1,
      max: 2,
      atLimit: false
    })
  })

  it('is unlimited when the limit is null or absent', () => {
    expect(teamLimitPosition(teams, { max_teams: null })).toEqual({
      current: 2,
      max: null,
      atLimit: false
    })
    expect(teamLimitPosition(teams, {})).toEqual({ current: 2, max: null, atLimit: false })
    expect(teamLimitPosition(teams, null)).toBeNull()
  })
})
