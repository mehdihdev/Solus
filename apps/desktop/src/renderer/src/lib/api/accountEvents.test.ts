import { describe, expect, it, vi } from 'vitest'
import { streamAccountEvents, type AccountEvent } from './accountEvents'
import {
  TEAM_ID,
  accountAccessRevoked,
  accountReady,
  membershipChanged,
  notificationCreated,
  sse,
  teamActivity,
  teamInvitesChanged,
  teamMembersChanged,
  teamProjectsChanged,
  teamUpdated
} from './liveStreamFixtures'
import { LiveStreamHttpError } from './liveStream'

function response(chunks: string[]): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
        controller.close()
      }
    })
  )
}
async function collect(frames: string[], fetchImpl?: typeof fetch): Promise<AccountEvent[]> {
  const out: AccountEvent[] = []
  for await (const event of streamAccountEvents(undefined, {
    baseUrl: 'https://api.test',
    getToken: () => 'tok',
    fetchImpl: fetchImpl ?? vi.fn().mockResolvedValue(response(frames))
  }))
    out.push(event)
  return out
}

describe('streamAccountEvents', () => {
  it('connects to /users/me/events with a Bearer header', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response([]))
    await collect([], fetchImpl)
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://api.test/users/me/events',
      expect.objectContaining({
        headers: { Accept: 'text/event-stream', Authorization: 'Bearer tok' }
      })
    )
  })

  it('decodes ready and every account frame, keeping the wire shape', async () => {
    const events = await collect([
      sse('ready', accountReady),
      sse('team.updated', teamUpdated),
      sse('team.members_changed', teamMembersChanged),
      sse('team.invites_changed', teamInvitesChanged),
      sse('team.projects_changed', teamProjectsChanged),
      sse('team.activity', teamActivity),
      sse('notification.created', notificationCreated),
      sse('membership.changed', membershipChanged),
      sse('access.revoked', accountAccessRevoked)
    ])
    expect(events).toEqual([
      { type: 'ready', ...accountReady },
      teamUpdated,
      teamMembersChanged,
      teamInvitesChanged,
      teamProjectsChanged,
      teamActivity,
      notificationCreated,
      membershipChanged,
      accountAccessRevoked
    ])
  })

  it.each([
    ['ready without team_ids', 'ready', { user_id: 'u' }],
    ['ready with non-string team id', 'ready', { user_id: 'u', team_ids: [1] }],
    ['ready with extra field', 'ready', { ...accountReady, extra: 1 }],
    ['unknown type', 'team.exploded', { type: 'team.exploded', team_id: TEAM_ID, at: 'x' }],
    ['extra content', 'team.updated', { ...teamUpdated, name: 'leak' }],
    ['non-string team id', 'team.updated', { ...teamUpdated, team_id: 5 }],
    ['missing at', 'team.updated', { type: 'team.updated', team_id: TEAM_ID }],
    ['type/event mismatch', 'team.updated', teamMembersChanged],
    [
      'null team id on team frame',
      'team.members_changed',
      { ...teamMembersChanged, team_id: null }
    ],
    ['non-string project id', 'team.projects_changed', { ...teamProjectsChanged, project_id: 3 }],
    ['non-string actor', 'team.activity', { ...teamActivity, actor_id: 3 }],
    ['non-string user', 'notification.created', { ...notificationCreated, user_id: null }],
    ['membership bad team', 'membership.changed', { ...membershipChanged, team_id: 2 }],
    [
      'unscoped revoke',
      'access.revoked',
      { ...accountAccessRevoked, user_id: null, team_id: null, project_id: null }
    ],
    ['project-only frame', 'layout.changed', { type: 'layout.changed' }]
  ])('drops %s without throwing', async (_name, event, data) => {
    expect(await collect([sse(event, data), sse('team.updated', teamUpdated)])).toEqual([
      teamUpdated
    ])
  })

  it('drops malformed JSON and comments', async () => {
    expect(
      await collect([
        ': keepalive\n\nevent: team.updated\ndata: {oops\n\n',
        sse('team.updated', teamUpdated)
      ])
    ).toEqual([teamUpdated])
  })

  it('surfaces rate_limited as a typed 429', async () => {
    await expect(
      collect([], vi.fn().mockResolvedValue(new Response(null, { status: 429 })))
    ).rejects.toBeInstanceOf(LiveStreamHttpError)
  })
})
