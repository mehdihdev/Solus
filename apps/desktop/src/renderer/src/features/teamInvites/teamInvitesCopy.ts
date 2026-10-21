// SOLUSDEV-317 (design A): the Team & invites view's own sentences, in Guide
// and Expert (ADR-016 — SOL mode is universal). GitHub wording stays in
// githubOrgCopy. Placeholders: `{team}`.
import type { SolMode } from '../../store/settingsStore'

const COPY = {
  setup_intro: {
    Guide: 'Just you so far. Two optional steps make this a working team.',
    Expert: 'Just you. Optional setup:'
  },
  setup_invite: {
    Guide:
      "They get access to this team's projects. You share a one-time join token with them; they paste it under Join team.",
    Expert: "Access to this team's projects, via a one-time token."
  },
  people_note: {
    Guide: 'Teammates are notified when their changes cross into your domains.',
    Expert: 'Teammates are notified of cross-domain changes.'
  },
  viewer_note: {
    Guide: 'You have view access to this team. Ask an admin to change roles or invite people.',
    Expert: 'View access.'
  }
} satisfies Record<string, { Guide: string; Expert: string }>

export type TeamInvitesCopyKey = keyof typeof COPY

export const TEAM_INVITES_COPY_KEYS = Object.keys(COPY) as readonly TeamInvitesCopyKey[]

export function teamText(key: TeamInvitesCopyKey, mode: SolMode): string {
  return COPY[key][mode]
}
