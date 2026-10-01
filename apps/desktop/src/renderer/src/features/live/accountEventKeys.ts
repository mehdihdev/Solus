// Which live-revision keys an account-channel frame invalidates (ADR-037).
// Pure: frame in, keys out. A frame is a hint — the REST hook behind each key
// decides what to refetch, so nothing here reads frame content beyond ids.
import type { AccountEvent } from '../../lib/api/accountEvents'
import { liveKeys } from '../../store/liveRevisionStore'

/** Every per-team revision key for one team. */
export function teamKeys(teamId: string): string[] {
  return [
    liveKeys.team(teamId),
    liveKeys.teamMembers(teamId),
    liveKeys.teamInvites(teamId),
    liveKeys.teamProjects(teamId),
    liveKeys.teamActivity(teamId)
  ]
}

const optionalProject = (projectId: string | null): string[] =>
  projectId === null ? [] : [liveKeys.projectDetail(projectId)]

/** My membership moved or my access went: identity, team list, and that team's data. */
function accessKeys(teamId: string | null, projectId: string | null): string[] {
  return [
    liveKeys.me,
    liveKeys.teams,
    ...(teamId === null ? [] : teamKeys(teamId)),
    ...optionalProject(projectId)
  ]
}

export function keysForAccountEvent(event: AccountEvent): string[] {
  switch (event.type) {
    case 'ready':
      return [
        liveKeys.me,
        liveKeys.teams,
        liveKeys.notifications,
        ...event.team_ids.flatMap(teamKeys)
      ]
    case 'team.updated':
      return [liveKeys.team(event.team_id), liveKeys.teams]
    case 'team.members_changed':
      return [liveKeys.teamMembers(event.team_id)]
    case 'team.invites_changed':
      return [liveKeys.teamInvites(event.team_id)]
    case 'team.projects_changed':
      return [liveKeys.teamProjects(event.team_id), ...optionalProject(event.project_id)]
    case 'team.activity':
      return [liveKeys.teamActivity(event.team_id)]
    case 'notification.created':
      return [liveKeys.notifications]
    case 'membership.changed':
    case 'access.revoked':
      return accessKeys(event.team_id, event.project_id)
  }
}
