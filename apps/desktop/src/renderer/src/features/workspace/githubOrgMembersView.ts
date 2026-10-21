// SOLUSDEV-317: the options each GitHub link picker offers on the People table,
// derived purely from the loaded org roster and the team's members. Both sides
// are read, because a fresh assignment shows on the roster before the members
// list refetches.
import type { TeamMemberApi } from '../../lib/api/resources'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import { teammateName } from './githubOrgRoster'

export interface PickerOption {
  id: string
  label: string
  detail: string
  disabled: boolean
}

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

export const ROLE_LABEL: Record<TeamMemberApi['role'], string> = {
  owner: 'Owner',
  admin: 'Admin',
  member: 'Member',
  viewer: 'Viewer'
}

/** The line under a teammate's name: their email — unless the email already IS
 *  the label (no name), then their role, so nothing shows twice. */
const teammateDetail = (m: TeamMemberApi): string => (m.name ? m.email : ROLE_LABEL[m.role])

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
