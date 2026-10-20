// SOLUSDEV-317: what the GITHUB ORG MEMBERS section shows, derived purely from
// the loaded roster and the team's members — filters, search, header counts,
// and the options each picker offers. Both sides are read, because a fresh
// assignment shows on the roster before the members list refetches.
import type { TeamMemberApi } from '../../lib/api/resources'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import { teammateName } from './githubOrgRoster'

export const ORG_FILTERS = ['All', 'On team', 'Not on Solus', 'Unassigned teammates'] as const
export type OrgFilter = (typeof ORG_FILTERS)[number]

export type RowKind = 'verified' | 'assigned' | 'invited' | 'not_on_solus'

export interface PickerOption {
  id: string
  label: string
  detail: string
  disabled: boolean
}

export function rowKind(member: GithubOrgMember): RowKind {
  if (member.assignment) return member.assignment.source === 'verified' ? 'verified' : 'assigned'
  return member.solus_status === 'invited' ? 'invited' : 'not_on_solus'
}

const matches = (query: string, ...fields: readonly string[]): boolean => {
  const q = query.trim().toLowerCase()
  return q === '' || fields.some((f) => f.toLowerCase().includes(q))
}

/** The org rows for a filter (not "Unassigned teammates"), searched by login. */
export function filterOrgMembers(
  items: readonly GithubOrgMember[],
  filter: OrgFilter,
  query: string
): GithubOrgMember[] {
  return items.filter((m) => {
    if (filter === 'On team' && !m.assignment) return false
    if (filter === 'Not on Solus' && m.assignment) return false
    return matches(query, m.github_login)
  })
}

export const onTeamCount = (items: readonly GithubOrgMember[]): number =>
  items.filter((m) => m.assignment).length

/** The teammate each loaded org row is linked to, by user id. */
function linkedUsers(items: readonly GithubOrgMember[]): Map<string, number> {
  const linked = new Map<string, number>()
  for (const m of items) if (m.assignment) linked.set(m.assignment.user_id, m.github_id)
  return linked
}

/** Teammates an org row's picker offers. A teammate linked to a DIFFERENT org
 *  member is left out; one who verified their own GitHub is shown, disabled,
 *  with that login (the server would refuse `member_has_verified_github`). */
export function teammateOptions(
  members: readonly TeamMemberApi[],
  items: readonly GithubOrgMember[],
  row: GithubOrgMember
): PickerOption[] {
  const linked = linkedUsers(items)
  return members.flatMap<PickerOption>((m) => {
    const elsewhere = linked.get(m.user_id) ?? m.github?.github_id
    if (elsewhere !== undefined && elsewhere !== row.github_id) {
      if (m.github?.source !== 'verified') return []
      const detail = `@${m.github.github_login} · verified`
      return [{ id: m.user_id, label: teammateName(m), detail, disabled: true }]
    }
    return [{ id: m.user_id, label: teammateName(m), detail: teammateDetail(m), disabled: false }]
  })
}

const ROLE_LABEL: Record<TeamMemberApi['role'], string> = {
  owner: 'Owner',
  admin: 'Admin',
  member: 'Member',
  viewer: 'Viewer'
}

/** The line under a teammate's name: their email — unless the email already IS
 *  the label (no name), then their role, so nothing shows twice. */
const teammateDetail = (m: TeamMemberApi): string => (m.name ? m.email : ROLE_LABEL[m.role])

/** "Unassigned teammates": live members with no GitHub link on either side. */
export function unassignedTeammates(
  members: readonly TeamMemberApi[],
  items: readonly GithubOrgMember[],
  query: string
): TeamMemberApi[] {
  const linked = linkedUsers(items)
  return members.filter(
    (m) => !m.github && !linked.has(m.user_id) && matches(query, m.name ?? '', m.email)
  )
}

/** Org members a teammate's picker offers: the loaded rows nobody is linked to. */
export function orgMemberOptions(items: readonly GithubOrgMember[]): PickerOption[] {
  return items
    .filter((m) => !m.assignment)
    .map((m) => ({
      id: String(m.github_id),
      label: `@${m.github_login}`,
      detail: m.solus_status === 'invited' ? 'Invited' : 'Not on Solus',
      disabled: false
    }))
}
