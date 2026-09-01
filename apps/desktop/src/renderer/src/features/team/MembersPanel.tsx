// Reusable member-management surface (roster, roles, invite/revoke/remove),
// extracted from TeamScreen so both the Team screen and the Settings > Members
// section render one implementation (DRY). Driven by useTeamData actions.
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { InviteApi, TeamMemberApi, TeamRole } from '../../lib/api/resources'
import { ModalShell } from '../workspace/modals'
import type { TeamData } from './useTeamData'

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
  onChangeRole: TeamData['actions']['changeRole']
  onRemove: TeamData['actions']['remove']
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
  onRevoke: TeamData['actions']['revoke']
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
  onChangeRole: TeamData['actions']['changeRole']
  onRemove: TeamData['actions']['remove']
  onRevoke: TeamData['actions']['revoke']
}

/** The MEMBERS card: roster + pending invites, with inline role/remove/revoke. */
export function LiveMembers({
  members,
  invites,
  myRole,
  canManage,
  onChangeRole,
  onRemove,
  onRevoke
}: LiveMembersProps): React.JSX.Element {
  return (
    <Card pad={0}>
      <div style={{ padding: '13px 16px', borderBottom: '1px solid var(--bd)' }}>
        <Mono size={9.5}>MEMBERS</Mono>
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

/** Invite-a-teammate modal. Validates the email, shows the one-time join token. */
export function InviteModal({
  onClose,
  onInvite
}: {
  onClose: () => void
  onInvite: TeamData['actions']['invite']
}): React.JSX.Element {
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [token, setToken] = useState<string | null>(null)

  const send = async (): Promise<void> => {
    if (!EMAIL_PATTERN.test(email)) {
      setError('Enter a valid email address.')
      return
    }
    setSending(true)
    setError(null)
    const invite = await onInvite(email)
    setSending(false)
    if (!invite) {
      setError('Could not send the invite. Check your role and try again.')
      return
    }
    setToken(invite.token ?? null)
    setEmail('')
  }

  return (
    <ModalShell onClose={onClose} width={380}>
      <div style={{ fontSize: 16, fontWeight: 600 }}>Invite a teammate</div>
      {token ? (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
            Invite sent. Share this one-time join link — it&apos;s shown only now:
          </div>
          <div
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
            {token}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
            <Button kind="primary" size="sm" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      ) : (
        <>
          <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
            They&apos;ll join with access to this team&apos;s projects.
          </div>
          <input
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

/** Self-contained members manager for the Settings > Members section: a header
 *  with the count + invite affordance, the roster card, and the invite modal. */
export function MembersManager({ data }: { data: TeamData }): React.JSX.Element {
  const { members, invites, myRole, actions } = data
  const canManage = myRole !== null && MANAGER_ROLES.includes(myRole)
  const [inviteOpen, setInviteOpen] = useState(false)

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12
        }}
      >
        <span style={{ fontSize: 12.5, color: 'var(--mut)' }}>
          {members.length} {members.length === 1 ? 'member' : 'members'}
          {invites.length > 0 ? ` · ${invites.length} pending` : ''}
        </span>
        {canManage && (
          <Button kind="ghost" size="sm" onClick={() => setInviteOpen(true)}>
            <Icons.plus size={13} /> Invite teammate
          </Button>
        )}
      </div>
      <LiveMembers
        members={members}
        invites={invites}
        myRole={myRole}
        canManage={canManage}
        onChangeRole={actions.changeRole}
        onRemove={actions.remove}
        onRevoke={actions.revoke}
      />
      {inviteOpen && <InviteModal onClose={() => setInviteOpen(false)} onInvite={actions.invite} />}
    </div>
  )
}
