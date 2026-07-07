import { describe, it, expect } from 'vitest'
import { activityText, actorName } from './activityText'
import type { ActivityApi, TeamMemberApi } from '../../lib/api/resources'

const MEMBERS: TeamMemberApi[] = [
  { user_id: 'u1', email: 'maya@strider.dev', name: 'Maya Krishnan', role: 'owner', joined_at: '' },
  { user_id: 'u2', email: 'priya@strider.dev', name: null, role: 'member', joined_at: '' }
]

function row(type: string, payload: Record<string, unknown> = {}, actor = 'u1'): ActivityApi {
  return {
    id: 'a1',
    type,
    domain: null,
    actor_id: actor,
    project_id: null,
    payload,
    created_at: '2026-07-07T10:00:00Z'
  }
}

describe('actorName', () => {
  it('prefers the member name, falls back to the email handle, then Someone', () => {
    expect(actorName('u1', MEMBERS)).toBe('Maya Krishnan')
    expect(actorName('u2', MEMBERS)).toBe('priya')
    expect(actorName('gone', MEMBERS)).toBe('Someone')
    expect(actorName(null, MEMBERS)).toBe('Someone')
  })
})

describe('activityText', () => {
  it('humanizes the known activity types', () => {
    expect(activityText(row('project.created', { name: 'Rover' }))).toBe(
      'created the project "Rover"'
    )
    expect(activityText(row('invite.created', { email: 'x@y.dev', role: 'member' }))).toBe(
      'invited x@y.dev as member'
    )
    expect(activityText(row('invite.accepted', { email: 'x@y.dev' }))).toBe(
      'joined the team (x@y.dev)'
    )
    expect(activityText(row('member.role_changed', { role: 'admin' }))).toBe(
      'changed a member role to admin'
    )
    expect(activityText(row('source.connected', { type: 'github', name: 'octo/fw' }))).toBe(
      'connected github source "octo/fw"'
    )
    expect(activityText(row('team.renamed', { name: 'Strider' }))).toBe(
      'renamed the team to "Strider"'
    )
    expect(activityText(row('project.archived', { name: 'Old' }))).toBe(
      'archived the project "Old"'
    )
  })

  it('falls back to a readable form of the type', () => {
    expect(activityText(row('future.event_kind'))).toBe('future: event kind')
  })
})
