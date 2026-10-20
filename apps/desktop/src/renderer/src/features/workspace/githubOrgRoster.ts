// SOLUSDEV-317: pure pieces of the GitHub org members roster — immutable row
// updates, the optimistic assignment, and how each refusal reads and what it
// should refetch. No React, no I/O: the hook (useGithubOrgRoster) wires them.
import type { TeamMemberApi } from '../../lib/api/resources'
import {
  githubErrorLogin,
  githubOrgErrorCode,
  type GithubAssignment,
  type GithubOrgMember,
  type SolusMemberStatus
} from '../../lib/api/resources.teamGithub'
import type { GithubCopyKey } from './githubOrgCopy'

export type CopyVars = Readonly<Record<string, string>>

/** A row's problem: a copy key (Guide/Expert at render) or a plan-limit message. */
export type RowProblem = { key: GithubCopyKey; vars: CopyVars } | { limit: string }

export interface RowAnnounce {
  key: GithubCopyKey
  vars: CopyVars
}

/** What a refusal makes stale: the team's members, the roster, or the link. */
export type StaleEffect = 'members' | 'roster' | 'link' | null

export interface Refusal {
  problem: RowProblem | null
  stale: StaleEffect
}

/** A teammate's display name: their name, else their email. */
export const teammateName = (m: Pick<TeamMemberApi, 'name' | 'email'>): string => m.name ?? m.email

/** Replace one row's assignment (and status) by GitHub id; others untouched. */
export function withAssignment(
  items: readonly GithubOrgMember[],
  githubId: number,
  assignment: GithubAssignment | null,
  status: SolusMemberStatus
): GithubOrgMember[] {
  return items.map((m) =>
    m.github_id === githubId ? { ...m, assignment, solus_status: status } : m
  )
}

/** Put a row back exactly as it was. */
export function restoreRow(
  items: readonly GithubOrgMember[],
  previous: GithubOrgMember
): GithubOrgMember[] {
  return items.map((m) => (m.github_id === previous.github_id ? previous : m))
}

/** The assignment shown before the server answers. */
export function optimisticAssignment(teammate: TeamMemberApi): GithubAssignment {
  return {
    user_id: teammate.user_id,
    name: teammate.name,
    email: teammate.email,
    source: 'admin',
    assigned_by: null,
    assigned_at: new Date().toISOString()
  }
}

const text = (key: GithubCopyKey, vars: CopyVars = {}): RowProblem => ({ key, vars })

/** How an assign refusal reads on its row, and what it makes stale. */
export function assignRefusal(
  error: unknown,
  row: GithubOrgMember,
  teammate: TeamMemberApi
): Refusal {
  const name = teammateName(teammate)
  const other = githubErrorLogin(error) ?? teammate.github?.github_login ?? '?'
  switch (githubOrgErrorCode(error)) {
    case 'not_a_team_member':
      return { problem: text('not_a_team_member'), stale: 'members' }
    case 'not_an_org_member':
      return { problem: text('assign_not_org_member'), stale: 'roster' }
    case 'github_identity_verified':
      return {
        problem: text('github_identity_verified', { login: row.github_login }),
        stale: 'roster'
      }
    case 'member_has_verified_github':
      return { problem: text('member_has_verified_github', { name, other }), stale: null }
    case 'member_already_assigned':
      return { problem: text('member_already_assigned', { name, other }), stale: null }
    default:
      return commonRefusal(error)
  }
}

/** Refusals shared by assign and unassign. */
export function commonRefusal(error: unknown): Refusal {
  switch (githubOrgErrorCode(error)) {
    case 'installation_suspended':
      return { problem: text('suspended'), stale: 'link' }
    case 'installation_missing':
      return { problem: text('assign_failed'), stale: 'link' }
    case 'assignment_missing':
      return { problem: null, stale: 'roster' }
    default:
      return { problem: text('assign_failed'), stale: null }
  }
}

/** Append a page, skipping GitHub ids already loaded. */
export function appendUnique(
  items: readonly GithubOrgMember[],
  more: readonly GithubOrgMember[]
): GithubOrgMember[] {
  const seen = new Set(items.map((m) => m.github_id))
  return [...items, ...more.filter((m) => !seen.has(m.github_id))]
}

interface RosterPage {
  items: GithubOrgMember[]
  total: number | null
  cursor: string | null
}

/** A refetched page, with every row still mid-mutation kept as it is on screen. */
export function keepPending(
  prev: RosterPage,
  next: RosterPage,
  rows: Readonly<Record<number, { pending: boolean }>>
): RosterPage {
  const items = next.items.map((m) =>
    rows[m.github_id]?.pending ? (prev.items.find((p) => p.github_id === m.github_id) ?? m) : m
  )
  return { ...next, items }
}
