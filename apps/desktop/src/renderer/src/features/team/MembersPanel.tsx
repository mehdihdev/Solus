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
import { integrationLogo, logoClass } from '../onboarding/integrationLogos'
import { ConfirmModal, ModalShell } from '../workspace/modals'
import { PlanLimitNotice } from '../workspace/PlanLimitNotice'
import type { InviteOutcome, MemberOutcome } from '../workspace/useHomeTeam'

export type ChangeRoleFn = (userId: string, role: TeamRole) => Promise<MemberOutcome>
export type RemoveMemberFn = (userId: string) => Promise<MemberOutcome>
export type RevokeInviteFn = (inviteId: string) => Promise<MemberOutcome>
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

type PendingConfirm =
  | { kind: 'remove'; member: TeamMemberApi }
  | { kind: 'revoke'; invite: InviteApi }
  | null

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

/** SOLUSDEV-317: the GitHub account a teammate is linked to — a display label
 *  (ADR-039 amendment), never access. The login is text, never HTML. */
function MemberGithub({ member }: { member: TeamMemberApi }): React.JSX.Element | null {
  const link = member.github
  if (!link) return null
  const logo = integrationLogo('github')
  return (
    <span
      data-testid={`member-github-${link.github_login}`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginTop: 3 }}
    >
      {logo && (
        <img
          src={logo}
          alt=""
          className={logoClass('github')}
          style={{ width: 11, height: 11, objectFit: 'contain' }}
        />
      )}
      <span style={{ fontSize: 10.5, color: 'var(--tx)', wordBreak: 'break-all' }}>
        @{link.github_login}
      </span>
      <Mono size={8.5} color={link.source === 'verified' ? 'var(--ok)' : 'var(--mut)'}>
        {link.source === 'verified' ? 'verified' : 'assigned'}
      </Mono>
    </span>
  )
}

function MemberRow({
  member,
  canManage,
  onChangeRole,
  onRemove,
  onAssignGithub
}: {
  member: TeamMemberApi
  canManage: boolean
  onChangeRole: (userId: string, role: TeamRole) => void
  onRemove: (member: TeamMemberApi) => void
  /** Admin-only, unlinked members only (SOLUSDEV-317). */
  onAssignGithub?: () => void
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
        <MemberGithub member={member} />
      </div>
      {onAssignGithub && (
        <Button
          kind="bare"
          size="sm"
          aria-label={`Assign GitHub to ${member.email}`}
          onClick={onAssignGithub}
        >
          Assign GitHub…
        </Button>
      )}
      {canManage ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select
            aria-label={`Role for ${member.email}`}
            value={member.role}
            onChange={(e) => onChangeRole(member.user_id, e.target.value as TeamRole)}
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
            onClick={() => onRemove(member)}
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
  onRevoke: (invite: InviteApi) => void
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
          onClick={() => onRevoke(invite)}
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
  /** SOLUSDEV-317: set only while GITHUB ORG MEMBERS is on screen. Offered to
   *  managers on members with no GitHub link; it opens that section's picker. */
  onAssignGithub?: (member: TeamMemberApi) => void
}

/** The MEMBERS card: roster + pending invites. Removing a member and revoking
 *  an invite are CONFIRMED with the person named (§7: an irreversible access
 *  change never runs on a reflex click); every refusal is shown inline. */
export function LiveMembers({
  members,
  invites,
  myRole,
  canManage,
  onChangeRole,
  onRemove,
  onRevoke,
  onInvite,
  onAssignGithub
}: LiveMembersProps): React.JSX.Element {
  const [confirm, setConfirm] = useState<PendingConfirm>(null)
  const [error, setError] = useState<string | null>(null)
  const report = (outcome: MemberOutcome): boolean => {
    setError(memberFailureText(outcome))
    return outcome.ok
  }
  const changeRole = (userId: string, role: TeamRole): void => {
    void onChangeRole(userId, role).then(report)
  }
  const confirmed = async (): Promise<boolean | { message: string }> => {
    if (!confirm) return false
    const outcome =
      confirm.kind === 'remove'
        ? await onRemove(confirm.member.user_id)
        : await onRevoke(confirm.invite.id)
    return outcome.ok ? true : { message: MEMBER_FAILURE[outcome.reason] }
  }
  return (
    <Card pad={0}>
      <MembersHeader
        members={members}
        invites={invites}
        canManage={canManage}
        onInvite={onInvite}
      />
      {members.map((m) => (
        <MemberRow
          key={m.user_id}
          member={m}
          canManage={canManage && m.role !== 'owner'}
          onChangeRole={changeRole}
          onRemove={(member) => setConfirm({ kind: 'remove', member })}
          onAssignGithub={
            canManage && onAssignGithub && !m.github ? () => onAssignGithub(m) : undefined
          }
        />
      ))}
      {invites.map((inv) => (
        <PendingInviteRow
          key={inv.id}
          invite={inv}
          canManage={canManage}
          onRevoke={(invite) => setConfirm({ kind: 'revoke', invite })}
        />
      ))}
      {error && (
        <div role="alert" style={{ padding: '10px 16px', fontSize: 11.5, color: 'var(--err)' }}>
          {error}
        </div>
      )}
      <div style={{ padding: '12px 16px', fontSize: 11, color: 'var(--mut)', lineHeight: 1.55 }}>
        {myRole === 'viewer'
          ? 'You have view access to this team.'
          : 'Teammates are notified when their changes cross into your domains.'}
      </div>
      <MembershipConfirmation
        confirm={confirm}
        onClose={() => setConfirm(null)}
        confirmed={confirmed}
      />
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

function MembersHeader({
  members,
  invites,
  canManage,
  onInvite
}: Pick<LiveMembersProps, 'members' | 'invites' | 'canManage' | 'onInvite'>): React.JSX.Element {
  return (
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

function MembershipConfirmation({
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
