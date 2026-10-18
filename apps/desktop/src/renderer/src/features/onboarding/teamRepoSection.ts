// SOLUSDEV-216 / ADR-039: the pure model behind the GitHub wizard's two-section
// picker. Given the team's installation, a page of its repositories and the
// caller's linked GitHub login, it produces the sections the picker renders —
// or null when the team has no installation, which means "legacy wizard,
// unchanged". No fetching, no store: graph-style pure function.
import type { SelectableItem } from '../../lib/api/resources'
import type { GithubOrgErrorCode, TeamInstallation } from '../../lib/api/resources.teamGithub'
import type { SolMode } from '../../store/settingsStore'

/** Sentinel ids for the account section's entries (never real repo ids: a repo
 *  id is always `owner/name`). */
export const ACCOUNT_ENTRY_ID = 'solus:account'
export const SIGN_IN_ENTRY_ID = 'solus:sign-in'

export const SUSPENDED_NOTICE = 'Suspended on GitHub'
export const NO_TEAM_REPOS_NOTICE = 'No repositories are shared with this installation.'

export interface PickerSection {
  readonly header: string
  readonly items: readonly SelectableItem[]
  /** Honest status line shown instead of / above the items. */
  readonly notice?: string
}

export interface TeamRepoInput {
  installation: TeamInstallation | null
  repos: readonly SelectableItem[]
  /** The caller's linked GitHub account, or null when none is connected. */
  linkedLogin: string | null
}

function teamSection(installation: TeamInstallation, repos: readonly SelectableItem[]) {
  const header = `FROM ${installation.account_login.toUpperCase()} (TEAM)`
  if (installation.status === 'suspended') {
    return { header, items: [], notice: SUSPENDED_NOTICE }
  }
  return repos.length === 0
    ? { header, items: [], notice: NO_TEAM_REPOS_NOTICE }
    : { header, items: repos }
}

function accountSection(linkedLogin: string | null): PickerSection {
  if (linkedLogin === null) {
    return {
      header: 'YOUR ACCOUNT',
      items: [{ id: SIGN_IN_ENTRY_ID, name: 'Use my own GitHub account' }]
    }
  }
  return {
    header: `YOUR ACCOUNT · ${linkedLogin}`,
    items: [{ id: ACCOUNT_ENTRY_ID, name: 'Pick from my repositories' }]
  }
}

/** The picker sections, or null when there is no installation (legacy wizard). */
export function teamRepoSections(input: TeamRepoInput): readonly PickerSection[] | null {
  if (!input.installation) return null
  return [teamSection(input.installation, input.repos), accountSection(input.linkedLogin)]
}

type BindCode = Extract<
  GithubOrgErrorCode,
  | 'installation_missing'
  | 'installation_suspended'
  | 'repo_not_in_installation'
  | 'credential_conflict'
>

const BIND_ERRORS: Readonly<Record<BindCode, Readonly<Record<SolMode, string>>>> = {
  installation_missing: {
    Guide:
      "This team's GitHub organization is no longer linked, so Solus can't read its repositories. " +
      'A team admin can reconnect it from the Team page, or you can use your own GitHub account.',
    Expert: 'No GitHub installation on this team. Relink it in Team, or use your account.'
  },
  installation_suspended: {
    Guide:
      "This team's GitHub organization is suspended on GitHub, so Solus can't read its " +
      'repositories right now. An organization owner has to unsuspend the Solus app in GitHub.',
    Expert: 'Installation suspended on GitHub. Unsuspend it there.'
  },
  repo_not_in_installation: {
    Guide:
      "That repository isn't shared with the Solus GitHub App. An organization owner can add it " +
      "under the app's repository access on GitHub; then pick it again.",
    Expert: 'Repo not in the installation. Grant it on GitHub.'
  },
  credential_conflict: {
    Guide:
      'Solus sent two different ways of signing in for this connection, so GitHub was not ' +
      'contacted. Try again; if it keeps happening, please report it.',
    Expert: 'Conflicting credentials on bind. Retry; report if it persists.'
  }
}

/** The named, mode-aware message for a team-bind failure, or null for a code
 *  this bind does not own (the caller then shows the API's own message). */
export function teamBindErrorMessage(code: GithubOrgErrorCode, mode: SolMode): string | null {
  return code in BIND_ERRORS ? BIND_ERRORS[code as BindCode][mode] : null
}
