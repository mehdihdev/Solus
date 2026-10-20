// Member-management pieces shared by Home (SOLUSDEV-244 / HOME H5): the invite
// dialog, the remove / revoke confirmations, and the refusal wording. The roster
// itself is the People table in features/teamInvites (SOLUSDEV-317, design A).
// The invite modal shows the one-time token ONCE, offers Copy, and guards Done
// so the token is not lost by a reflex click.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import type { InviteApi, TeamMemberApi, TeamRole } from '../../lib/api/resources'
import { ConfirmModal, ModalShell } from '../workspace/modals'
import { PlanLimitNotice } from '../workspace/PlanLimitNotice'
import type { InviteOutcome, MemberOutcome } from '../workspace/useHomeTeam'

export type InviteFn = (email: string) => Promise<InviteOutcome>

/** Why a member mutation was refused — shown inline, never swallowed
 *  (HOME H5 security review H3: a silent 403 read as "done"). */
export const MEMBER_FAILURE: Record<Exclude<MemberOutcome, { ok: true }>['reason'], string> = {
  forbidden: "You don't have permission to do that on this team.",
  last_owner: 'A team must keep at least one owner. Make someone else an owner first.',
  failed: "That didn't work. Check your role and try again."
}

export function memberFailureText(outcome: MemberOutcome): string | null {
  return outcome.ok ? null : MEMBER_FAILURE[outcome.reason]
}

export type PendingConfirm =
  | { kind: 'remove'; member: TeamMemberApi }
  | { kind: 'revoke'; invite: InviteApi }
  | null

export const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
export const MANAGER_ROLES: readonly TeamRole[] = ['owner', 'admin']

export const INVITE_FAILURE: Record<Exclude<InviteOutcome, { ok: true }>['reason'], string> = {
  plan_limit: '',
  already_member: 'That person is already on this team.',
  invite_pending: 'An invite for that email is already pending — revoke it to send a new one.',
  invalid_email: 'Enter a valid email address.',
  failed: 'Could not send the invite. Check your role and try again.'
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

/** The one-time token, shown ONCE: Copy, and a Done that asks twice while the
 *  token has not been copied (a reflex click must not lose it). Never logged. */
function TokenReveal({
  token,
  movedToTeamId,
  onClose
}: {
  token: string | null
  movedToTeamId: string | null
  onClose: () => void
}): React.JSX.Element {
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const [armed, setArmed] = useState(false)
  const done = (): void => {
    if (copied || armed || !token) {
      onClose()
      return
    }
    setArmed(true)
  }
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
        {movedToTeamId
          ? 'Invite sent from your new team — Home has switched to it. '
          : 'Invite sent. '}
        Share this one-time join token — it&apos;s shown only now:
      </div>
      <div
        data-testid="invite-token"
        style={{
          marginTop: 10,
          padding: '9px 11px',
          background: 'var(--bg)',
          border: '1px solid var(--bd)',
          borderRadius: 3,
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          wordBreak: 'break-all'
        }}
      >
        {token ?? 'The token was not returned. Revoke this invite and send a new one.'}
      </div>
      {copyFailed && (
        <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>
          Copy failed — select the token above and copy it by hand.
        </div>
      )}
      {armed && (
        <div role="alert" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--warn)' }}>
          You won&apos;t see this token again. Copy it, or click Done once more to close anyway.
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
        {token && (
          <Button
            kind="ghost"
            size="sm"
            onClick={() =>
              void copyToClipboard(token).then((ok) => {
                setCopied(ok)
                setCopyFailed(!ok)
              })
            }
          >
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

/** Invite-a-teammate modal. Validates the email, names a refusal (a plan limit
 *  with the upgrade path), then shows the one-time join token. */
export function InviteModal({
  onClose,
  onInvite,
  onUpgrade,
  isPersonal = false
}: {
  onClose: () => void
  onInvite: InviteFn
  onUpgrade?: () => void
  /** Inviting from the PERSONAL team creates a collaborative team that counts
   *  against the plan (ADR-025/023) — said BEFORE Send, not after. */
  isPersonal?: boolean
}): React.JSX.Element {
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [limit, setLimit] = useState<string | null>(null)
  const [sent, setSent] = useState<{ token: string | null; movedToTeamId: string | null } | null>(
    null
  )

  const send = async (): Promise<void> => {
    if (!EMAIL_PATTERN.test(email)) {
      setError(INVITE_FAILURE.invalid_email)
      return
    }
    setSending(true)
    setError(null)
    setLimit(null)
    const outcome = await onInvite(email)
    setSending(false)
    if (!outcome.ok) {
      if (outcome.reason === 'plan_limit') setLimit(outcome.limit.message)
      else setError(INVITE_FAILURE[outcome.reason])
      return
    }
    setSent({ token: outcome.token, movedToTeamId: outcome.movedToTeamId })
    setEmail('')
  }

  return (
    <ModalShell onClose={onClose} width={380}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Invite a teammate</div>
      {sent ? (
        <TokenReveal token={sent.token} movedToTeamId={sent.movedToTeamId} onClose={onClose} />
      ) : (
        <>
          <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
            {isPersonal
              ? 'Your personal workspace stays yours alone: sending this invite creates a new collaborative team (it counts against your plan) and Home switches to it.'
              : "They'll join with access to this team's projects."}
          </div>
          <InviteEmail email={email} setEmail={setEmail} send={send} />
          {error && (
            <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>{error}</div>
          )}
          {limit && <PlanLimitNotice message={limit} onUpgrade={onUpgrade} />}
          <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
            <Button kind="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button kind="primary" size="sm" onClick={() => void send()}>
              {sending ? (
                <>
                  <Spinner size={11} color="var(--acc-ink)" /> Sending…
                </>
              ) : (
                'Send invite'
              )}
            </Button>
          </div>
        </>
      )}
    </ModalShell>
  )
}

function InviteEmail({
  email,
  setEmail,
  send
}: {
  email: string
  setEmail: (email: string) => void
  send: () => Promise<void>
}): React.JSX.Element {
  return (
    <input
      aria-label="Teammate email"
      value={email}
      onChange={(e) => setEmail(e.target.value)}
      placeholder="teammate@team.dev"
      autoFocus
      onKeyDown={(e) => e.key === 'Enter' && void send()}
      style={{
        width: '100%',
        boxSizing: 'border-box',
        marginTop: 16,
        background: 'var(--bg)',
        color: 'var(--tx)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '10px 12px',
        fontSize: 13,
        fontFamily: 'var(--font-ui)',
        outline: 'none'
      }}
    />
  )
}

export function MembershipConfirmation({
  confirm,
  onClose,
  confirmed
}: {
  confirm: PendingConfirm
  onClose: () => void
  confirmed: () => Promise<boolean | { message: string }>
}): React.JSX.Element {
  return (
    <>
      {confirm?.kind === 'remove' && (
        <ConfirmModal
          title="Remove member"
          body={
            <>
              Remove <strong style={{ color: 'var(--tx)' }}>{confirm.member.email}</strong> from
              this team? They lose access to every project in it.
            </>
          }
          confirmLabel="Remove"
          onClose={() => onClose()}
          onConfirm={confirmed}
        />
      )}
      {confirm?.kind === 'revoke' && (
        <ConfirmModal
          title="Revoke invite"
          body={
            <>
              Revoke the invite for{' '}
              <strong style={{ color: 'var(--tx)' }}>{confirm.invite.email}</strong>? Its token
              stops working; you can send a new one.
            </>
          }
          confirmLabel="Revoke"
          onClose={() => onClose()}
          onConfirm={confirmed}
        />
      )}
    </>
  )
}
