// SOLUSDEV-216 / ADR-039: every string the GitHub organization card and its
// roster show, in Guide and Expert variants (ADR-016 — SOL mode is universal).
// Guide explains what an org link does and why the owner approves on GitHub;
// Expert is terse. `{n}` is the only placeholder.
import type { GithubOrgErrorCode } from '../../lib/api/resources.teamGithub'
import type { SolMode } from '../../store/settingsStore'

interface Variants {
  Guide: string
  Expert: string
}

const COPY = {
  unlinked_admin: {
    Guide:
      'Link your GitHub organization so everyone on the team can add its repos — no personal sign-in. An organization owner approves the install on GitHub, so Solus only ever sees what they grant.',
    Expert: 'Link the GitHub org: team-wide repo access, no personal tokens.'
  },
  unlinked_member: {
    Guide:
      'No GitHub organization is linked to this team yet. Ask a team admin to link one; once they do, you can add its repos without signing in to GitHub yourself.',
    Expert: 'No GitHub organization linked — ask a team admin.'
  },
  unconfigured: {
    Guide:
      "GitHub organizations aren't set up on this server, so there is nothing to link here. Personal GitHub sign-in still works.",
    Expert: "GitHub organizations aren't set up on this server."
  },
  linking: {
    Guide:
      'Finish in your browser: the organization owner approves Solus on GitHub. If you are not an owner, GitHub asks one for you. This can take a few minutes.',
    Expert: 'Waiting for GitHub approval in the browser…'
  },
  requested: {
    Guide:
      'Waiting for an org owner to approve Solus on GitHub. Nothing is linked yet — link again once they have approved.',
    Expert: 'Waiting for an org owner to approve Solus on GitHub — link again once they do.'
  },
  suspended: {
    Guide:
      'Suspended on GitHub — syncs are paused until an org owner unsuspends Solus. Nothing is lost; sources resume on their own.',
    Expert: 'Suspended on GitHub — syncs paused until an org owner unsuspends Solus.'
  },
  cancelled: {
    Guide: 'The GitHub install was cancelled, so nothing was linked. You can try again any time.',
    Expert: 'Install cancelled — nothing linked.'
  },
  failed: {
    Guide: "Couldn't finish linking the organization. Check your connection and try again.",
    Expert: 'Link failed. Retry.'
  },
  no_bridge: {
    Guide: 'Linking a GitHub organization needs the Solus desktop app, which opens your browser.',
    Expert: 'Linking needs the desktop app.'
  },
  former_member: { Guide: 'a former member', Expert: 'a former member' },
  scope_all: { Guide: 'all repositories', Expert: 'all repos' },
  scope_selected: { Guide: 'selected repositories', Expert: 'selected repos' },
  unlink_confirm: {
    Guide:
      'Unlinking disconnects every project source that reads through this organization. Your repositories and the GitHub App itself are untouched, and you can relink later.',
    Expert: 'Unlink: disconnects every project source using this org.'
  },
  unlink_confirm_count: {
    Guide:
      'Unlinking disconnects {n} project sources that read through this organization. Your repositories and the GitHub App itself are untouched, and you can relink later.',
    Expert: 'Unlink: disconnects {n} project sources using this org.'
  },
  unlink_done: {
    Guide:
      'Unlinked — {n} project sources were disconnected. To fully remove Solus from the organization, uninstall the app on GitHub too.',
    Expert: 'Unlinked, {n} sources disconnected. Uninstall on GitHub to finish.'
  },
  unlink_failed: {
    Guide: "Couldn't unlink the organization. Please try again.",
    Expert: 'Unlink failed.'
  },
  roster_intro: {
    Guide:
      'These are the organization members on GitHub. Inviting someone creates a one-time join token you share with them; they join Solus themselves and nobody is added automatically.',
    Expert: 'Org members. Invite creates a one-time token; no auto-join.'
  },
  roster_empty: {
    Guide: 'GitHub reports no members for this organization.',
    Expert: 'No members.'
  },
  roster_failed: {
    Guide: "Couldn't load the organization's members. Please try again.",
    Expert: 'Roster failed to load.'
  },
  invite_shown: {
    Guide:
      "Share this one-time join token with them — it's shown only now. When they accept, Solus checks that their GitHub identity matches.",
    Expert: 'One-time token, shown once. GitHub identity is checked on accept.'
  },
  not_an_org_member: {
    Guide:
      'That person is no longer a member of the GitHub organization, so they cannot be invited.',
    Expert: 'Not an org member any more.'
  },
  invite_failed: {
    Guide: "Couldn't create that invite. Please try again.",
    Expert: 'Invite failed.'
  },
  plan_limit_reached: {
    Guide: 'Your plan has reached its limit, so this organization cannot be linked yet.',
    Expert: 'Plan limit reached.'
  },
  already_linked: {
    Guide: 'This team already has a GitHub organization linked. Unlink it first to link another.',
    Expert: 'A GitHub organization is already linked.'
  },
  installation_linked_elsewhere: {
    Guide:
      'This organization is linked to another Solus team — unlink it there first, then link it here.',
    Expert: 'Linked to another Solus team — unlink it there first.'
  },
  installation_not_accessible: {
    Guide:
      "Solus couldn't see that installation with your GitHub account. Make sure you finished the install in the organization you meant, then try again.",
    Expert: 'Installation not accessible to your GitHub account.'
  },
  install_state_invalid: {
    Guide: 'That install attempt expired or was already used. Start the link again.',
    Expert: 'Install state expired — restart.'
  }
} satisfies Record<string, Variants>

export type GithubCopyKey = keyof typeof COPY

export const GITHUB_COPY_KEYS = Object.keys(COPY) as readonly GithubCopyKey[]

/** The copy for `key` in the user's SOL mode, with `{n}` filled when given. */
export function githubText(key: GithubCopyKey, mode: SolMode, vars?: { n?: number }): string {
  const text: string = COPY[key][mode]
  return vars?.n === undefined ? text : text.replaceAll('{n}', String(vars.n))
}

const REFUSAL_KEYS: ReadonlySet<string> = new Set([
  'plan_limit_reached',
  'already_linked',
  'installation_linked_elsewhere',
  'installation_not_accessible',
  'install_state_invalid'
])

/** The copy key naming an install refusal, or null for a code with no inline copy. */
export function refusalCopyKey(code: GithubOrgErrorCode): GithubCopyKey | null {
  return REFUSAL_KEYS.has(code) ? (code as GithubCopyKey) : null
}
