// Team screen — roster + cross-domain activity feed, ported verbatim from
// TeamScreen in TestDesign/app/team-settings.jsx. The invite flow is visual
// only (no backend call), exactly as the prototype behaves.
import { useState } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { dcol } from '../../theme/tokens.constants'
import { ACTIVITY, TEAM } from '../workspace/workspaceData.constants'

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const INVITE_SEND_DELAY_MS = 1100

interface TeamScreenProps {
  onOpenAlert: (id: string) => void
}

export function TeamScreen({ onOpenAlert }: TeamScreenProps): React.JSX.Element {
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
