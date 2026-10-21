// SOLUSDEV-317: the one-time join token of a GitHub-id invite, held OUTSIDE the
// org members section. The section can unmount at any time (team switch, a
// demotion or a suspension refetched live); the token must survive that — only
// Done discards it. Home renders the host once. Never persisted, never logged.
import { create } from 'zustand'
import { GitHubInviteTokenModal, type InviteTokenKind } from './GitHubInviteTokenModal'

export interface InviteReveal {
  /** An @login or an email. */
  invitee: string
  token: string | null
  kind: InviteTokenKind
}

interface GithubInviteTokenState {
  reveal: InviteReveal | null
  show: (reveal: InviteReveal) => void
  dismiss: () => void
}

export const useGithubInviteTokenStore = create<GithubInviteTokenState>((set) => ({
  reveal: null,
  show: (reveal) => set({ reveal }),
  dismiss: () => set({ reveal: null })
}))

export function GitHubInviteTokenHost(): React.JSX.Element | null {
  const reveal = useGithubInviteTokenStore((s) => s.reveal)
  const dismiss = useGithubInviteTokenStore((s) => s.dismiss)
  if (!reveal) return null
  return (
    <GitHubInviteTokenModal
      invitee={reveal.invitee}
      token={reveal.token}
      kind={reveal.kind}
      onDone={dismiss}
    />
  )
}
