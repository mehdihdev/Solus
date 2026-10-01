// The signed-in user's live channel: GET /users/me/events carries the user's
// own frames plus every team they belong to (ADR-037). Frames are invalidation
// hints; a fresh `ready` may arrive mid-stream when the team set changes.
import type {
  AccessRevoked,
  AccountFrame,
  AccountStreamReady,
  MembershipChanged,
  NotificationCreated,
  TeamActivity,
  TeamInvitesChanged,
  TeamMembersChanged,
  TeamProjectsChanged,
  TeamUpdated
} from '@solus/shared-types'
import { streamSse, type StreamSseOptions } from './liveStream'
import {
  isNullableString,
  isString,
  isStringArray,
  literal,
  matchesShape,
  type Shape
} from './liveStreamGuards'
import type { SolEvent } from './solStream'

export type AccountEvent = ({ type: 'ready' } & AccountStreamReady) | AccountFrame

const teamFrame = (
  type: string
): { type: ReturnType<typeof literal>; team_id: typeof isString; at: typeof isString } => ({
  type: literal(type),
  team_id: isString,
  at: isString
})

const READY_SHAPE = {
  user_id: isString,
  team_ids: isStringArray
} satisfies Shape<AccountStreamReady>
const SHAPES = {
  'team.updated': teamFrame('team.updated') satisfies Shape<TeamUpdated>,
  'team.members_changed': teamFrame('team.members_changed') satisfies Shape<TeamMembersChanged>,
  'team.invites_changed': teamFrame('team.invites_changed') satisfies Shape<TeamInvitesChanged>,
  'team.projects_changed': {
    ...teamFrame('team.projects_changed'),
    project_id: isNullableString
  } satisfies Shape<TeamProjectsChanged>,
  'team.activity': {
    ...teamFrame('team.activity'),
    project_id: isNullableString,
    actor_id: isNullableString
  } satisfies Shape<TeamActivity>,
  'notification.created': {
    type: literal('notification.created'),
    user_id: isString,
    at: isString
  } satisfies Shape<NotificationCreated>,
  'membership.changed': {
    type: literal('membership.changed'),
    user_id: isString,
    team_id: isNullableString,
    project_id: isNullableString,
    at: isString
  } satisfies Shape<MembershipChanged>,
  'access.revoked': {
    type: literal('access.revoked'),
    user_id: isNullableString,
    team_id: isNullableString,
    project_id: isNullableString,
    at: isString
  } satisfies Shape<AccessRevoked>
}

const namesAnId = (data: Record<string, unknown>): boolean =>
  data.user_id !== null || data.team_id !== null || data.project_id !== null

function decodeAccountEvent(event: SolEvent): AccountEvent | null {
  const { type, data } = event
  if (type === 'ready') {
    return matchesShape(data, READY_SHAPE)
      ? { type, ...(data as unknown as AccountStreamReady) }
      : null
  }
  if (!(type in SHAPES) || !matchesShape(data, SHAPES[type as keyof typeof SHAPES])) return null
  if (type === 'access.revoked' && !namesAnId(data)) return null
  return data as unknown as AccountFrame
}

type AccountStreamOptions = Pick<
  StreamSseOptions<never>,
  'baseUrl' | 'getToken' | 'fetchImpl' | 'maxFrameBytes'
>

export function streamAccountEvents(
  signal?: AbortSignal,
  options: AccountStreamOptions = {}
): AsyncGenerator<AccountEvent> {
  return streamSse({ ...options, path: '/users/me/events', signal, decode: decodeAccountEvent })
}
