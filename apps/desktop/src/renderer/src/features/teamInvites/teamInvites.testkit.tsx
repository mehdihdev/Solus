// SOLUSDEV-317: shared fixtures for the Team & invites view tests.
import { vi } from 'vitest'
import { render } from '@testing-library/react'
import type { InviteApi, TeamMemberApi, TeamSummary } from '../../lib/api/resources'
import type { TeamInstallation } from '../../lib/api/resources.teamGithub'
import type { HomeTeam } from '../workspace/useHomeTeam'
import type { TeamGithub } from '../workspace/useTeamGithub'
import { GitHubInviteTokenHost } from '../workspace/githubInviteTokenStore'
import { TeamInvitesView, type TeamInvitesViewProps } from './TeamInvitesView'

export const TEAM: TeamSummary = {
  team_id: 't1',
  name: 'Strider',
  role: 'owner',
  is_personal: false,
  plan_status: 'active',
  trial_ends_at: ''
}

export const ORG: TeamInstallation = {
  id: 'i1',
  provider: 'github',
  account_login: 'strider-robotics',
  account_type: 'Organization',
  account_avatar_url: null,
  repository_selection: 'all',
  status: 'active',
  linked_by: { user_id: 'u1', name: 'Ada' },
  linked_at: '2026-10-16T00:00:00Z',
  html_url: 'https://github.com/strider-robotics',
  manage_url: 'https://github.com/organizations/strider-robotics/settings/installations/1'
}

export const EMAIL_INVITE: InviteApi = {
  id: 'inv1',
  team_id: 't1',
  email: 'dev@team.dev',
  role: 'member',
  status: 'pending',
  created_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
  expires_at: new Date(Date.now() + 5 * 86_400_000).toISOString()
}

export function github(
  installation: TeamInstallation | null,
  over: Partial<TeamGithub> = {}
): TeamGithub {
  return {
    status: 'ready',
    installation,
    repoCount: 14,
    unconfigured: false,
    linking: false,
    notice: null,
    actions: {
      link: vi.fn(async () => undefined),
      unlink: vi.fn(),
      inviteMember: vi.fn(async () => ({ ok: true as const, token: 'one-time-token' })),
      refresh: vi.fn(async () => undefined)
    },
    ...over
  }
}

export function homeTeam(
  members: TeamMemberApi[],
  invites: InviteApi[] = [],
  over: Partial<HomeTeam> = {}
): HomeTeam {
  return {
    status: 'ready',
    detail: null,
    members,
    invites,
    activity: [],
    activityTotal: 0,
    activityHasMore: false,
    myRole: 'owner',
    teamLimit: null,
    actions: {
      invite: vi.fn(async () => ({ ok: true as const, token: 'email-token', movedToTeamId: null })),
      revoke: vi.fn(async () => ({ ok: true as const })),
      changeRole: vi.fn(async () => ({ ok: true as const })),
      remove: vi.fn(async () => ({ ok: true as const })),
      leave: vi.fn(),
      rename: vi.fn(),
      deleteTeam: vi.fn(),
      loadMoreActivity: vi.fn(async () => undefined),
      refresh: vi.fn(async () => undefined)
    },
    ...over
  }
}

export function renderView(
  over: Partial<TeamInvitesViewProps> & { homeTeam: HomeTeam }
): ReturnType<typeof render> & { props: TeamInvitesViewProps } {
  const props: TeamInvitesViewProps = {
    team: TEAM,
    canManage: true,
    onInvite: vi.fn(),
    onUpgrade: vi.fn(),
    ...over
  }
  const utils = render(
    <>
      <TeamInvitesView {...props} />
      <GitHubInviteTokenHost />
    </>
  )
  return { props, ...utils }
}
