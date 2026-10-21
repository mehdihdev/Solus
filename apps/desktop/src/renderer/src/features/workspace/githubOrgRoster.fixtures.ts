// SOLUSDEV-317: shared test fixtures for the GitHub org members roster.
import type { TeamMemberApi } from '../../lib/api/resources'
import type { GithubAssignment, GithubOrgMember } from '../../lib/api/resources.teamGithub'

export const ADA: TeamMemberApi = {
  user_id: 'u1',
  email: 'ada@team.dev',
  name: 'Ada',
  role: 'owner',
  joined_at: '2026-10-01T00:00:00Z',
  github: null
}
export const NOOR: TeamMemberApi = {
  user_id: 'u2',
  email: 'noor@team.dev',
  name: 'Noor',
  role: 'member',
  joined_at: '2026-10-01T00:00:00Z',
  github: { github_id: 8, github_login: 'noor-a', avatar_url: null, source: 'admin' }
}
export const SAM: TeamMemberApi = {
  user_id: 'u3',
  email: 'sam@team.dev',
  name: 'Sam',
  role: 'member',
  joined_at: '2026-10-01T00:00:00Z',
  github: { github_id: 9, github_login: 'sam-v', avatar_url: null, source: 'verified' }
}
export const FREE: GithubOrgMember = {
  github_id: 7,
  github_login: 'octo',
  avatar_url: null,
  solus_status: 'not_on_solus',
  assignment: null
}
export const ASSIGNED: GithubOrgMember = {
  github_id: 8,
  github_login: 'noor-a',
  avatar_url: null,
  solus_status: 'member',
  assignment: {
    user_id: 'u2',
    name: 'Noor',
    email: 'noor@team.dev',
    source: 'admin',
    assigned_by: { user_id: 'u1', name: 'Ada' },
    assigned_at: '2026-10-18T00:00:00Z'
  }
}
export const VERIFIED: GithubOrgMember = {
  github_id: 9,
  github_login: 'sam-v',
  avatar_url: 'https://avatars.githubusercontent.com/u/9',
  solus_status: 'member',
  assignment: {
    user_id: 'u3',
    name: 'Sam',
    email: 'sam@team.dev',
    source: 'verified',
    assigned_by: null,
    assigned_at: null
  }
}
export const INVITED: GithubOrgMember = {
  github_id: 10,
  github_login: 'pending-pat',
  avatar_url: null,
  solus_status: 'invited',
  assignment: null
}
export const SERVER_ASSIGNMENT: GithubAssignment = {
  user_id: 'u2',
  name: 'Noor',
  email: 'noor@team.dev',
  source: 'admin',
  assigned_by: { user_id: 'u1', name: 'Ada' },
  assigned_at: '2026-10-19T00:00:00Z'
}
