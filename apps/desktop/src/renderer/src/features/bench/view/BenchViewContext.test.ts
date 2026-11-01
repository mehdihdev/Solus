import { describe, expect, it } from 'vitest'
import type { Me } from '../../../lib/api/resources'
import { canEditBenchView } from './BenchViewContext'

const me = (role: string): Me => ({
  id: 'u1',
  email: 'u@example.test',
  name: null,
  avatar_url: null,
  created_at: '2026-01-01T00:00:00Z',
  teams: [
    {
      team_id: 't1',
      name: 'T',
      role,
      is_personal: false,
      plan_status: 'active',
      trial_ends_at: ''
    }
  ]
})

describe('canEditBenchView', () => {
  it.each(['owner', 'admin', 'member'])('lets a %s edit', (role) => {
    expect(canEditBenchView(me(role), 't1')).toBe(true)
  })

  it('keeps a viewer read-only', () => {
    expect(canEditBenchView(me('viewer'), 't1')).toBe(false)
  })

  it('is read-only until the role is known, and for another team', () => {
    expect(canEditBenchView(null, 't1')).toBe(false)
    expect(canEditBenchView(me('owner'), 't2')).toBe(false)
  })
})
