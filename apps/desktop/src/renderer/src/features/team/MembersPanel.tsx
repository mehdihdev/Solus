// Member-management surface (roster, roles, invite/revoke/remove) — hosted by
// Home since SOLUSDEV-244 / HOME H5 (the Team screen and Settings > Members
// were retired; this is the one implementation). Callback types are its own,
// so any hook can drive it. The invite modal shows the one-time token ONCE,
// offers Copy, and guards Done so the token is not lost by a reflex click.
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { InviteApi, TeamMemberApi, TeamRole } from '../../lib/api/resources'
import { ModalShell } from '../workspace/modals'
import { PlanLimitNotice } from '../workspace/PlanLimitNotice'
import type { InviteOutcome } from '../workspace/useHomeTeam'

export type ChangeRoleFn = (userId: string, role: TeamRole) => Promise<boolean>
export type RemoveMemberFn = (userId: string) => Promise<boolean>
export type RevokeInviteFn = (inviteId: string) => Promise<boolean>
export type InviteFn = (email: string) => Promise<InviteOutcome>

export const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
export const MANAGER_ROLES: readonly TeamRole[] = ['owner', 'admin']

/** Assignable roles (owner is transferred, not picked from a dropdown). */
const ASSIGNABLE_ROLES = ['admin', 'member', 'viewer'] as const

const selectStyle: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '4px 6px',
  fontSize: 11,
  fontFamily: 'var(--font-ui)'
}

const iconButtonStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: 'var(--mut)',
  cursor: 'pointer',
  padding: 4
}

function MemberRow({
  member,
  canManage,
  onChangeRole,
  onRemove
}: {
  member: TeamMemberApi
  canManage: boolean
  onChangeRole: ChangeRoleFn
  onRemove: RemoveMemberFn
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        gap: 11,
        alignItems: 'center',
        padding: '11px 16px',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <Avatar name={member.name ?? member.email} size={28} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{member.name ?? member.email}</div>
        <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{member.email}</div>
      </div>
      {canManage ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select
            aria-label={`Role for ${member.email}`}
            value={member.role}
            onChange={(e) => void onChangeRole(member.user_id, e.target.value as TeamRole)}
            style={selectStyle}
          >
            {ASSIGNABLE_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            type="button"
            aria-label={`Remove ${member.email}`}
            onClick={() => void onRemove(member.user_id)}
            style={iconButtonStyle}
          >
            <Icons.x size={13} />
          </button>
        </div>
      ) : (
        <Mono size={8.5} color="var(--mut)">
          ● {member.role.toUpperCase()}
        </Mono>
      )}
    </div>
  )
}

function PendingInviteRow({
  invite,
  canManage,
  onRevoke
}: {
  invite: InviteApi
  canManage: boolean
  onRevoke: RevokeInviteFn
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        gap: 11,
        alignItems: 'center',
        padding: '11px 16px',
        borderBottom: '1px solid var(--bd)',
        opacity: 0.75
      }}
    >
      <span
        style={{
          width: 28,
          height: 28,
          borderRadius: 99,
          border: '1px dashed var(--bd)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--mut)'
        }}
      >
        <Icons.team size={13} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5 }}>{invite.email}</div>
        <Mono size={8.5} color="var(--warn)">
          INVITE PENDING · {invite.role.toUpperCase()}
        </Mono>
      </div>
      {canManage && (
        <button
          type="button"
          aria-label={`Revoke invite for ${invite.email}`}
          onClick={() => void onRevoke(invite.id)}
          style={iconButtonStyle}
        >
          <Icons.x size={13} />
        </button>
      )}
    </div>
  )
}

export interface LiveMembersProps {
  members: readonly TeamMemberApi[]
  invites: readonly InviteApi[]
  myRole: TeamRole | null
  canManage: boolean
  onChangeRole: ChangeRoleFn
  onRemove: RemoveMemberFn
  onRevoke: RevokeInviteFn
  /** Header action (Home's Invite teammate lives here for managers). */
  onInvite?: () => void
}

/** The MEMBERS card: roster + pending invites, with inline role/remove/revoke. */
export function LiveMembers({
  members,
  invites,
  myRole,
  canManage,
  onChangeRole,
  onRemove,
  onRevoke,
  onInvite
}: LiveMembersProps): React.JSX.Element {
  return (
    <Card pad={0}>
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--bd)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}
      >
        <Mono size={9.5}>
          MEMBERS · {members.length}
          {invites.length > 0 ? ` · ${invites.length} PENDING` : ''}
        </Mono>
        {canManage && onInvite && (
          <Button kind="bare" size="sm" onClick={onInvite}>
            <Icons.plus size={12} /> Invite
          </Button>
        )}
      </div>
      {members.map((m) => (
        <MemberRow
          key={m.user_id}
          member={m}
          canManage={canManage && m.role !== 'owner'}
          onChangeRole={onChangeRole}
          onRemove={onRemove}
        />
      ))}
      {invites.map((inv) => (
        <PendingInviteRow key={inv.id} invite={inv} canManage={canManage} onRevoke={onRevoke} />
      ))}
      <div style={{ padding: '12px 16px', fontSize: 11, color: 'var(--mut)', lineHeight: 1.55 }}>
        {myRole === 'viewer'
          ? 'You have view access to this team.'
          : 'Teammates are notified when their changes cross into your domains.'}
      </div>
    </Card>
  )
}

const INVITE_FAILURE: Record<Exclude<InviteOutcome, { ok: true }>['reason'], string> = {
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
            onClick={() => void copyToClipboard(token).then((ok) => setCopied(ok))}
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
  onUpgrade
}: {
  onClose: () => void
  onInvite: InviteFn
  onUpgrade?: () => void
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
            They&apos;ll join with access to this team&apos;s projects.
          </div>
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
