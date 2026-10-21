// The one-time join token of a GitHub-id invite (SOLUSDEV-216 → SOLUSDEV-317:
// the roster moved inline onto Home; only this reveal stays a modal). Shown
// ONCE; Escape and click-out never discard it — only Done, which asks twice
// while the token is uncopied. The token is never logged; the login is text.
import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { githubText } from './githubOrgCopy'
import { ModalShell } from './modals'

/** `github`: a GitHub-id invite (identity checked on accept); `email`: an email invite. */
export type InviteTokenKind = 'github' | 'email'

export interface GitHubInviteTokenModalProps {
  /** Who it is for: an @login or an email (text, never HTML). */
  invitee: string
  token: string | null
  kind?: InviteTokenKind
  onDone: () => void
}

const TOKEN_STYLE: React.CSSProperties = {
  marginTop: 10,
  padding: '9px 11px',
  background: 'var(--bg)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  wordBreak: 'break-all'
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

const noop = (): void => undefined

export function GitHubInviteTokenModal({
  invitee,
  token,
  kind = 'github',
  onDone
}: GitHubInviteTokenModalProps): React.JSX.Element {
  const mode = useSettingsStore((s) => s.solMode)
  const titleId = useId()
  return (
    <ModalShell onClose={noop} width={420} labelledBy={titleId} closeOnEscape>
      <div id={titleId} style={{ fontSize: 16, fontWeight: 600, wordBreak: 'break-all' }}>
        Invite {invitee}
      </div>
      <TokenView token={token} kind={kind} mode={mode} onDone={onDone} />
    </ModalShell>
  )
}

function TokenView({
  token,
  kind,
  mode,
  onDone
}: {
  token: string | null
  kind: InviteTokenKind
  mode: SolMode
  onDone: () => void
}): React.JSX.Element {
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const [armed, setArmed] = useState(false)
  const revealRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    revealRef.current?.focus()
  }, [])
  const done = (): void => {
    if (copied || armed || !token) onDone()
    else setArmed(true)
  }
  const copy = (value: string): void =>
    void copyToClipboard(value).then((ok) => {
      setCopied(ok)
      setCopyFailed(!ok)
    })
  return (
    <div style={{ marginTop: 12 }}>
      <div ref={revealRef} role="status" tabIndex={-1} style={{ outline: 'none' }}>
        <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
          {githubText(kind === 'email' ? 'invite_shown_email' : 'invite_shown', mode)}
        </div>
        <div data-testid="invite-token" style={TOKEN_STYLE}>
          {token ?? githubText('roster_token_missing', mode)}
        </div>
      </div>
      {copyFailed && <Line color="var(--err)" text={githubText('roster_copy_failed', mode)} />}
      {armed && <Line color="var(--warn)" text={githubText('roster_wont_see_again', mode)} />}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
        {token && (
          <Button kind="ghost" size="sm" onClick={() => copy(token)}>
            {copied ? 'Copied' : 'Copy token'}
          </Button>
        )}
        <Button kind="primary" size="sm" onClick={done}>
          Done
        </Button>
      </div>
    </div>
  )
}

function Line({ color, text }: { color: string; text: string }): React.JSX.Element {
  return (
    <div role="alert" style={{ marginTop: 8, fontSize: 11.5, color }}>
      {text}
    </div>
  )
}
