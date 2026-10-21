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

/** Fixed sentences of the team picker, in both SOL modes (ADR-016). */
const PICKER_COPY = {
  suspended: {
    Guide:
      "This organization is suspended on GitHub, so Solus can't list its repositories. An organization owner can unsuspend the Solus app.",
    Expert: 'Suspended on GitHub.'
  },
  no_team_repos: {
    Guide:
      "No repositories are shared with this installation yet. An organization owner can add some under the Solus app's repository access on GitHub.",
    Expert: 'No repos shared with this installation.'
  },
  use_own_account: {
    Guide: 'Use my own GitHub account',
    Expert: 'Use my account'
  },
  lookup_failed: {
    Guide:
      "Couldn't check whether your team has a GitHub organization linked, so you can connect with your own account instead. Reopen this to try again.",
    Expert: 'Team org lookup failed. Connect with your account, or reopen to retry.'
  },
  load_failed: {
    Guide:
      "Couldn't load the organization's repositories. Try your search again, or use your own GitHub account.",
    Expert: 'Repo list failed to load.'
  }
} as const satisfies Record<string, Readonly<Record<SolMode, string>>>

export type PickerCopyKey = keyof typeof PICKER_COPY
export const PICKER_COPY_KEYS = Object.keys(PICKER_COPY) as readonly PickerCopyKey[]

export function pickerText(key: PickerCopyKey, mode: SolMode): string {
  return PICKER_COPY[key][mode]
}

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
  /** SOL mode: the notices and the sign-in entry read in the user's mode. */
  mode: SolMode
}

// Headers keep their natural case; the picker uppercases them with CSS.
function teamSection(
  installation: TeamInstallation,
  repos: readonly SelectableItem[],
  mode: SolMode
): PickerSection {
  const header = `From ${installation.account_login} (team)`
  if (installation.status === 'suspended') {
    return { header, items: [], notice: pickerText('suspended', mode) }
  }
  return repos.length === 0
    ? { header, items: [], notice: pickerText('no_team_repos', mode) }
    : { header, items: repos }
}

function accountSection(linkedLogin: string | null, mode: SolMode): PickerSection {
  if (linkedLogin === null) {
    return {
      header: 'Your account',
      items: [{ id: SIGN_IN_ENTRY_ID, name: pickerText('use_own_account', mode) }]
    }
  }
  return {
    header: `Your account · ${linkedLogin}`,
    items: [{ id: ACCOUNT_ENTRY_ID, name: 'Pick from my repositories' }]
  }
}

/** The picker sections, or null when there is no installation (legacy wizard). */
export function teamRepoSections(input: TeamRepoInput): readonly PickerSection[] | null {
  if (!input.installation) return null
  return [
    teamSection(input.installation, input.repos, input.mode),
    accountSection(input.linkedLogin, input.mode)
  ]
}

type BindCode = Extract<
  GithubOrgErrorCode,
  | 'installation_missing'
  | 'installation_suspended'
  | 'repo_not_in_installation'
  | 'credential_conflict'
>

function isBindCode(code: string): code is BindCode {
  return Object.hasOwn(BIND_ERRORS, code)
}

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
  return isBindCode(code) ? BIND_ERRORS[code][mode] : null
}
