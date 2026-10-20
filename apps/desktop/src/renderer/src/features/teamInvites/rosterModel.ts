// SOLUSDEV-317 (design A, "one roster"): the Team & invites People table as
// pure data — teammates, then pending invites, then (for admins with a live
// Organization link) org members who are not on the team. Each teammate's
// GitHub link is read from the roster first (fresh, optimistic) and the members
// list second. A link is a display label only, never access.
import type { InviteApi, TeamMemberApi } from '../../lib/api/resources'
import type { GithubIdentitySource, GithubOrgMember } from '../../lib/api/resources.teamGithub'

export type RosterRow =
  | { kind: 'member'; key: string; member: TeamMemberApi }
  | { kind: 'invite'; key: string; invite: InviteApi }
  | { kind: 'org'; key: string; org: GithubOrgMember }

export interface MemberLink {
  githubId: number
  login: string
  avatarUrl: string | null
  source: GithubIdentitySource
  /** The admin who assigned it, when the roster says (null: verified or unknown). */
  assignedBy: string | null
  assignedAt: string | null
}

export const ROSTER_FILTERS = ['Everyone', 'Team', 'Invites', 'Not on Solus', 'No GitHub'] as const
export type RosterFilter = (typeof ROSTER_FILTERS)[number]

/** "Not on Solus" needs the org roster (admins with a live Organization link). */
export function rosterFilters(hasOrg: boolean): readonly RosterFilter[] {
  return hasOrg ? ROSTER_FILTERS : ROSTER_FILTERS.filter((f) => f !== 'Not on Solus')
}

/** People in the org with no teammate, minus those a GitHub invite row stands for. */
function outsiders(
  org: readonly GithubOrgMember[],
  invites: readonly InviteApi[]
): GithubOrgMember[] {
  const invited = new Set(invites.map((i) => i.github_user_id).filter((id) => id != null))
  return org.filter((m) => !m.assignment && !invited.has(m.github_id))
}

export function buildRoster(
  members: readonly TeamMemberApi[],
  invites: readonly InviteApi[],
  org: readonly GithubOrgMember[] | null
): RosterRow[] {
  return [
    ...members.map((member) => ({ kind: 'member' as const, key: member.user_id, member })),
    ...invites.map((invite) => ({ kind: 'invite' as const, key: invite.id, invite })),
    ...(org ? outsiders(org, invites) : []).map((m) => ({
      kind: 'org' as const,
      key: String(m.github_id),
      org: m
    }))
  ]
}

function fromRoster(row: GithubOrgMember): MemberLink | null {
  const a = row.assignment
  if (!a) return null
  return {
    githubId: row.github_id,
    login: row.github_login,
    avatarUrl: row.avatar_url,
    source: a.source,
    assignedBy: a.assigned_by?.name ?? null,
    assignedAt: a.assigned_at
  }
}

function fromMembers(gh: NonNullable<TeamMemberApi['github']>): MemberLink {
  return {
    githubId: gh.github_id,
    login: gh.github_login,
    avatarUrl: gh.avatar_url,
    source: gh.source,
    assignedBy: null,
    assignedAt: null
  }
}

/** A teammate's GitHub link: the roster's assignment of them, else theirs from GET /members. */
export function memberLink(
  member: TeamMemberApi,
  org: readonly GithubOrgMember[] | null
): MemberLink | null {
  const row = org?.find((m) => m.assignment?.user_id === member.user_id)
  if (row) return fromRoster(row)
  const gh = member.github
  if (!gh) return null
  // A LOADED roster row for that id is the truth (e.g. just unlinked); a row on a
  // page not loaded yet leaves the members list's answer standing.
  const loaded = org?.some((m) => m.github_id === gh.github_id)
  return loaded ? null : fromMembers(gh)
}

const matches = (query: string, fields: readonly (string | null | undefined)[]): boolean => {
  // A leading @ is how logins are written; the data has none.
  const q = query.trim().replace(/^@/, '').toLowerCase()
  return q === '' || fields.some((f) => f?.toLowerCase().includes(q))
}

function rowFields(row: RosterRow, org: readonly GithubOrgMember[] | null): (string | null)[] {
  if (row.kind === 'invite') return [row.invite.email, row.invite.github_login ?? null]
  if (row.kind === 'org') return [row.org.github_login]
  const link = memberLink(row.member, org)
  return [row.member.name, row.member.email, link?.login ?? null]
}

function inFilter(
  row: RosterRow,
  filter: RosterFilter,
  org: readonly GithubOrgMember[] | null
): boolean {
  switch (filter) {
    case 'Team':
      return row.kind === 'member'
    case 'Invites':
      return row.kind === 'invite'
    case 'Not on Solus':
      return row.kind === 'org'
    case 'No GitHub':
      return row.kind === 'member' && memberLink(row.member, org) === null
    default:
      return true
  }
}

export function filterRoster(
  rows: readonly RosterRow[],
  filter: RosterFilter,
  query: string,
  org: readonly GithubOrgMember[] | null
): RosterRow[] {
  return rows.filter((r) => inFilter(r, filter, org) && matches(query, rowFields(r, org)))
}

export function summaryCounts(rows: readonly RosterRow[]): {
  members: number
  invites: number
  outside: number
} {
  const count = (kind: RosterRow['kind']): number => rows.filter((r) => r.kind === kind).length
  return { members: count('member'), invites: count('invite'), outside: count('org') }
}
