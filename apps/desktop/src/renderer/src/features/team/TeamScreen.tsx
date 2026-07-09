// Team screen. When the workspace is linked to the API it renders live team
// data (roster, cross-domain activity, pending invites) with working invite /
// revoke / role-change / remove actions via useTeamData. When offline (dev
// bypass / unreachable API) it falls back to the prototype mock, ported from
// TeamScreen in TestDesign/app/team-settings.jsx, so the demo still works.
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { dcol } from '../../theme/tokens.constants'
import { relativeTime } from '../../lib/relativeTime'
import type { InviteApi, TeamMemberApi, TeamRole } from '../../lib/api/resources'
import { ACTIVITY, TEAM } from '../workspace/workspaceData.constants'
import { activityText, actorName } from './activityText'
import { useTeamData, type TeamData } from './useTeamData'

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const INVITE_SEND_DELAY_MS = 1100
const MANAGER_ROLES: readonly TeamRole[] = ['owner', 'admin']

interface TeamScreenProps {
  onOpenAlert: (id: string) => void
}

/** Route between live and demo rendering by connection status. */
export function TeamScreen({ onOpenAlert }: TeamScreenProps): React.JSX.Element {
  const data = useTeamData()
  if (data.status === 'loading') {
    return (
      <div
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        data-testid="team-loading"
      >
        <Spinner size={20} />
      </div>
    )
  }
  if (data.status === 'offline') return <TeamScreenDemo onOpenAlert={onOpenAlert} />
  return <TeamScreenLive data={data} />
}

/* ============================ LIVE (API-backed) ============================ */

function TeamScreenLive({ data }: { data: TeamData }): React.JSX.Element {
  const { team, members, invites, activity, myRole, actions } = data
  const canManage = myRole !== null && MANAGER_ROLES.includes(myRole)
  const [inviteOpen, setInviteOpen] = useState(false)

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 920, margin: '0 auto', padding: '22px 24px 48px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
              {team?.name ?? 'Team'}
            </h1>
            <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
              {members.length} {members.length === 1 ? 'member' : 'members'}
              {team && !team.is_personal ? '' : ' · personal workspace'}
            </div>
          </div>
          {canManage && (
            <Button id="btn-invite" kind="primary" size="sm" onClick={() => setInviteOpen(true)}>
              <Icons.plus size={13} /> Invite teammate
            </Button>
          )}
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0,1fr) 380px',
            gap: 16,
            marginTop: 20,
            alignItems: 'start'
          }}
        >
          <LiveActivity activity={activity} members={members} />
          <LiveMembers
            members={members}
            invites={invites}
            myRole={myRole}
            canManage={canManage}
            onChangeRole={actions.changeRole}
            onRemove={actions.remove}
            onRevoke={actions.revoke}
          />
        </div>
      </div>
      {inviteOpen && <InviteModal onClose={() => setInviteOpen(false)} onInvite={actions.invite} />}
    </div>
  )
}

function LiveActivity({
  activity,
  members
}: {
  activity: TeamData['activity']
  members: readonly TeamMemberApi[]
}): React.JSX.Element {
  return (
    <Card pad={0}>
      <div
        style={{
          padding: '13px 16px',
          borderBottom: '1px solid var(--bd)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}
      >
        <Mono size={9.5}>TEAM ACTIVITY</Mono>
        <Mono size={9}>RECENT</Mono>
      </div>
      {activity.length === 0 && (
        <div style={{ padding: '18px 16px', fontSize: 12, color: 'var(--mut)' }}>
          No activity yet. Syncs, invites, and project changes will show up here.
        </div>
      )}
      {activity.map((a) => (
        <div
          key={a.id}
          style={{
            display: 'flex',
            gap: 12,
            padding: '12px 16px',
            borderBottom: '1px solid var(--bd)'
          }}
        >
          <Avatar name={actorName(a.actor_id, members)} size={26} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
              <strong style={{ fontWeight: 600 }}>{actorName(a.actor_id, members)}</strong>{' '}
              {activityText(a)}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
              <span style={{ fontSize: 10, color: 'var(--mut)' }}>
                {relativeTime(a.created_at)}
              </span>
            </div>
          </div>
        </div>
      ))}
    </Card>
  )
}

function LiveMembers({
  members,
  invites,
  myRole,
  canManage,
  onChangeRole,
  onRemove,
  onRevoke
}: {
  members: readonly TeamMemberApi[]
  invites: readonly InviteApi[]
  myRole: TeamRole | null
  canManage: boolean
  onChangeRole: TeamData['actions']['changeRole']
  onRemove: TeamData['actions']['remove']
  onRevoke: TeamData['actions']['revoke']
}): React.JSX.Element {
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
        <div
          key={inv.id}
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
            <div style={{ fontSize: 12.5 }}>{inv.email}</div>
            <Mono size={8.5} color="var(--warn)">
              INVITE PENDING · {inv.role.toUpperCase()}
            </Mono>
          </div>
          {canManage && (
            <button
              type="button"
              aria-label={`Revoke invite for ${inv.email}`}
              onClick={() => void onRevoke(inv.id)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--mut)',
                cursor: 'pointer',
                padding: 4
              }}
            >
              <Icons.x size={13} />
            </button>
          )}
        </div>
      ))}
      <div style={{ padding: '12px 16px', fontSize: 11, color: 'var(--mut)', lineHeight: 1.55 }}>
        {myRole === 'viewer'
          ? 'You have view access to this team.'
          : 'Teammates are notified when their changes cross into your domains.'}
      </div>
    </Card>
  )
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
            style={{
              background: 'var(--bg)',
              color: 'var(--tx)',
              border: '1px solid var(--bd)',
              borderRadius: 3,
              padding: '4px 6px',
              fontSize: 11,
              fontFamily: 'var(--font-ui)'
            }}
          >
            {(['admin', 'member', 'viewer'] as const).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            type="button"
            aria-label={`Remove ${member.email}`}
            onClick={() => void onRemove(member.user_id)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--mut)',
              cursor: 'pointer',
              padding: 4
            }}
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

function InviteModal({
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
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        zIndex: 70,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}
      onClick={onClose}
    >
      <div onClick={(e) => e.stopPropagation()}>
        <Card pad={24} style={{ width: 380, boxShadow: '0 18px 60px rgba(0,0,0,0.5)' }}>
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
        </Card>
      </div>
    </div>
  )
}

/* ============================ DEMO (offline) ============================ */

function TeamScreenDemo({ onOpenAlert }: TeamScreenProps): React.JSX.Element {
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [pending, setPending] = useState<readonly string[]>([])
  const [sent, setSent] = useState(false)

  const sendInvite = (): void => {
    if (!EMAIL_PATTERN.test(inviteEmail)) return
    setSent(true)
    setTimeout(() => {
      setPending((p) => [...p, inviteEmail])
      setInviteOpen(false)
      setSent(false)
      setInviteEmail('')
    }, INVITE_SEND_DELAY_MS)
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 920, margin: '0 auto', padding: '22px 24px 48px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
              Team
            </h1>
            <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
              strider-qd12 · 4 members across 4 domains
            </div>
          </div>
          <Button id="btn-invite" kind="primary" size="sm" onClick={() => setInviteOpen(true)}>
            <Icons.plus size={13} /> Invite teammate
          </Button>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0,1fr) 380px',
            gap: 16,
            marginTop: 20,
            alignItems: 'start'
          }}
        >
          {/* activity feed */}
          <Card pad={0}>
            <div
              style={{
                padding: '13px 16px',
                borderBottom: '1px solid var(--bd)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}
            >
              <Mono size={9.5}>CROSS-DOMAIN ACTIVITY</Mono>
              <Mono size={9}>LAST 7 DAYS</Mono>
            </div>
            {ACTIVITY.map((a, i) => (
              <div
                key={i}
                onClick={a.alert ? () => onOpenAlert(a.alert as string) : undefined}
                style={{
                  display: 'flex',
                  gap: 12,
                  padding: '12px 16px',
                  borderBottom: '1px solid var(--bd)',
                  cursor: a.alert ? 'pointer' : 'default',
                  background: a.affects
                    ? 'color-mix(in srgb, var(--warn) 4%, transparent)'
                    : 'transparent'
                }}
              >
                <Avatar name={a.who} size={26} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                    <strong style={{ fontWeight: 600 }}>{a.who.split(' ')[0]}</strong> {a.what}
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
                    <span
                      style={{ width: 5, height: 5, borderRadius: 99, background: dcol(a.d) }}
                    ></span>
                    <span
                      style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--mut)' }}
                    >
                      {a.where}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--mut)' }}>· {a.time}</span>
                    {a.affects && (
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 8.5,
                          letterSpacing: '0.08em',
                          color: 'var(--warn)',
                          border: '1px solid color-mix(in srgb, var(--warn) 40%, transparent)',
                          borderRadius: 99,
                          padding: '2px 7px'
                        }}
                      >
                        AFFECTS YOUR CODE
                      </span>
                    )}
                    {a.you && (
                      <Mono size={8.5} color="var(--mut)">
                        YOU
                      </Mono>
                    )}
                  </div>
                </div>
                {a.alert && (
                  <span style={{ color: 'var(--mut)', alignSelf: 'center' }}>
                    <Icons.arrowR size={12} />
                  </span>
                )}
              </div>
            ))}
          </Card>

          {/* members */}
          <Card pad={0}>
            <div style={{ padding: '13px 16px', borderBottom: '1px solid var(--bd)' }}>
              <Mono size={9.5}>MEMBERS</Mono>
            </div>
            {TEAM.map((m) => (
              <div
                key={m.name}
                style={{
                  display: 'flex',
                  gap: 11,
                  alignItems: 'center',
                  padding: '11px 16px',
                  borderBottom: '1px solid var(--bd)'
                }}
              >
                <Avatar name={m.name} size={28} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600 }}>
                    {m.name}{' '}
                    {m.you && (
                      <span style={{ fontWeight: 400, color: 'var(--mut)', fontSize: 11 }}>
                        (you)
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 10.5, color: 'var(--mut)' }}>{m.email}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <Mono size={8.5} color={dcol(m.d)}>
                    ● {m.role.toUpperCase()}
                  </Mono>
                  <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 3 }}>{m.last}</div>
                </div>
              </div>
            ))}
            {pending.map((e) => (
              <div
                key={e}
                style={{
                  display: 'flex',
                  gap: 11,
                  alignItems: 'center',
                  padding: '11px 16px',
                  borderBottom: '1px solid var(--bd)',
                  opacity: 0.7
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
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12.5 }}>{e}</div>
                  <Mono size={8.5} color="var(--warn)">
                    INVITE PENDING
                  </Mono>
                </div>
              </div>
            ))}
            <div
              style={{ padding: '12px 16px', fontSize: 11, color: 'var(--mut)', lineHeight: 1.55 }}
            >
              Teammates get notified when their changes affect each other&apos;s domains — like the
              U4 swap above.
            </div>
          </Card>
        </div>
      </div>

      {/* invite modal */}
      {inviteOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.55)',
            zIndex: 70,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          onClick={() => setInviteOpen(false)}
        >
          <div onClick={(e) => e.stopPropagation()}>
            <Card pad={24} style={{ width: 380, boxShadow: '0 18px 60px rgba(0,0,0,0.5)' }}>
              <div style={{ fontSize: 16, fontWeight: 600 }}>Invite a teammate</div>
              <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 4, lineHeight: 1.5 }}>
                They&apos;ll join strider-qd12 with access to all four domains.
              </div>
              <input
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="teammate@team.dev"
                autoFocus
                onKeyDown={(e) => e.key === 'Enter' && sendInvite()}
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
              <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
                <Button kind="ghost" size="sm" onClick={() => setInviteOpen(false)}>
                  Cancel
                </Button>
                <Button kind="primary" size="sm" onClick={sendInvite}>
                  {sent ? (
                    <>
                      <Spinner size={11} color="var(--acc-ink)" /> Sending…
                    </>
                  ) : (
                    'Send invite'
                  )}
                </Button>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
