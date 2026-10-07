// Test-only wire fixtures for the ADR-037 live frames. Typed against the shared
// contract so a shape change fails the typecheck here; values mirror
// packages/shared-types/fixtures/live-events/*.json.
import type {
  AccessRevoked,
  AccountStreamReady,
  GraphChanged,
  JobUpdated,
  LayoutChanged,
  MembershipChanged,
  NotificationCreated,
  ProjectStreamReady,
  ProjectUpdated,
  SourcesChanged,
  TeamActivity,
  TeamInvitesChanged,
  TeamMembersChanged,
  TeamProjectsChanged,
  TeamUpdated
} from '@solus/shared-types'

export const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
export const TEAM_ID = '22222222-2222-4222-8222-222222222222'
export const USER_ID = '33333333-3333-4333-8333-333333333333'
const SOURCE_ID = '44444444-4444-4444-8444-444444444444'
const AT = '2026-09-30T12:00:00+00:00'

export const projectReady: ProjectStreamReady = { project_id: PROJECT_ID }
export const graphChanged: GraphChanged = {
  type: 'graph.changed',
  project_id: PROJECT_ID,
  source_id: SOURCE_ID,
  sync_id: null,
  counts: {
    entities_created: 1,
    entities_updated: 2,
    entities_deleted: 0,
    relations_created: 0,
    relations_deleted: 0
  },
  at: AT
}
export const layoutChanged: LayoutChanged = {
  type: 'layout.changed',
  project_id: PROJECT_ID,
  version: 7,
  at: AT
}
export const sourcesChanged: SourcesChanged = {
  type: 'sources.changed',
  project_id: PROJECT_ID,
  source_id: SOURCE_ID,
  at: AT
}
export const projectUpdated: ProjectUpdated = {
  type: 'project.updated',
  project_id: PROJECT_ID,
  team_id: TEAM_ID,
  at: AT
}
export const jobUpdated: JobUpdated = {
  type: 'job.updated',
  project_id: PROJECT_ID,
  job_id: '55555555-5555-4555-8555-555555555555',
  status: 'succeeded',
  at: AT
}
export const projectAccessRevoked: AccessRevoked = {
  type: 'access.revoked',
  user_id: USER_ID,
  team_id: null,
  project_id: PROJECT_ID,
  at: AT
}

export const accountReady: AccountStreamReady = { user_id: USER_ID, team_ids: [TEAM_ID] }
export const teamUpdated: TeamUpdated = { type: 'team.updated', team_id: TEAM_ID, at: AT }
export const teamMembersChanged: TeamMembersChanged = {
  type: 'team.members_changed',
  team_id: TEAM_ID,
  at: AT
}
export const teamInvitesChanged: TeamInvitesChanged = {
  type: 'team.invites_changed',
  team_id: TEAM_ID,
  at: AT
}
export const teamProjectsChanged: TeamProjectsChanged = {
  type: 'team.projects_changed',
  team_id: TEAM_ID,
  project_id: PROJECT_ID,
  at: AT
}
export const teamActivity: TeamActivity = {
  type: 'team.activity',
  team_id: TEAM_ID,
  project_id: null,
  actor_id: USER_ID,
  at: AT
}
export const notificationCreated: NotificationCreated = {
  type: 'notification.created',
  user_id: USER_ID,
  at: AT
}
export const membershipChanged: MembershipChanged = {
  type: 'membership.changed',
  user_id: USER_ID,
  team_id: TEAM_ID,
  project_id: null,
  at: AT
}
export const accountAccessRevoked: AccessRevoked = {
  type: 'access.revoked',
  user_id: USER_ID,
  team_id: TEAM_ID,
  project_id: null,
  at: AT
}

/** One SSE frame as the server writes it. */
export const sse = (event: string, data: unknown): string =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
