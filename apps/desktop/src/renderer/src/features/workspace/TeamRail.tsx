// Home's team rail (SOLUSDEV-319, multi-team Home, design D — docs/wireflows/home.md
// "Team rail"): every team I belong to, with my role and the team's size, the active one
// marked, my personal workspace last; switching is one click. Beneath: Create a team, Join
// with an invite code, the plan-limit line, and the invitations waiting for me (accept or
// decline in place). The ACCOUNT card rides at the foot as `footer`.
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { TeamSummary } from '../../lib/api/resources'
import type { TeamLimitPosition } from '../../lib/api/planLimit'
import type { MyInvite, MyInviteRefusal } from '../../lib/api/resources.myInvites'
import { PlanLimitNotice } from './PlanLimitNotice'
import { TeamLimitLine } from './TeamMenu'
import { AT_LIMIT_MESSAGE, railOrder, roleLabel, teamInitials, withArticle } from './teamLabels'
import type { TeamSizes } from './useTeamSizes'
import type { MyInvites } from './useMyInvites'

export interface TeamRailProps {
  greeting: string
  teams: readonly TeamSummary[]
  activeTeamId: string | null
  sizes: TeamSizes
  invites: MyInvites
  teamLimit: TeamLimitPosition | null
  onSwitch: (teamId: string) => void
  onNewTeam: () => void
  onJoin: () => void
  onUpgrade?: () => void
  /** The ACCOUNT card, pinned at the rail's foot. */
  footer?: React.ReactNode
}

const RAIL_STYLE: React.CSSProperties = {
  flex: '0 0 280px',
  width: 280,
  display: 'flex',
  flexDirection: 'column',
  gap: 18,
  padding: '26px 16px 20px',
  borderRight: '1px solid var(--bd)',
  overflowY: 'auto',
  overflowX: 'hidden',
  minHeight: 0
}

export function TeamRail(props: TeamRailProps): React.JSX.Element {
  return (
    <aside aria-label="Teams" style={RAIL_STYLE}>
      <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, letterSpacing: '-0.015em' }}>
        {props.greeting}
      </h1>
      <TeamList {...props} />
      <div style={{ display: 'grid', gap: 6 }}>
        <DashedButton onClick={props.onNewTeam}>Create a team</DashedButton>
        <DashedButton onClick={props.onJoin}>Join with an invite code</DashedButton>
      </div>
      <TeamLimitLine teamLimit={props.teamLimit} onUpgrade={props.onUpgrade} />
      <Invitations invites={props.invites} onUpgrade={props.onUpgrade} />
      <div style={{ flex: 1 }} />
      {props.footer}
    </aside>
  )
}

function TeamList({ teams, activeTeamId, sizes, onSwitch }: TeamRailProps): React.JSX.Element {
  const ordered = railOrder(teams)
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
        YOUR TEAMS · {ordered.length}
      </Mono>
      <ul
        aria-label="Your teams"
        style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4 }}
      >
        {ordered.map((team) => (
          <li key={team.team_id}>
            <TeamRow
              team={team}
              size={sizes[team.team_id]}
              active={team.team_id === activeTeamId}
              onSwitch={onSwitch}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}

function rowSubtitle(team: TeamSummary, size: number | undefined): string {
  if (team.is_personal) return 'Only you'
  const role = roleLabel(team.role)
  return size === undefined ? role : `${role} · ${size} ${size === 1 ? 'member' : 'members'}`
}

function TeamRow({
  team,
  size,
  active,
  onSwitch
}: {
  team: TeamSummary
  size: number | undefined
  active: boolean
  onSwitch: (teamId: string) => void
}): React.JSX.Element {
  const name = team.is_personal ? 'Personal workspace' : team.name
  return (
    <button
      type="button"
      aria-current={active ? 'true' : undefined}
      className="interactive home-card"
      onClick={() => onSwitch(team.team_id)}
      style={{
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 10px',
        borderRadius: 4,
        textAlign: 'left',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        color: 'var(--tx)',
        background: active ? 'var(--sur2)' : 'transparent',
        border: `1px solid ${active ? 'var(--acc)' : 'transparent'}`
      }}
    >
      <span aria-hidden="true" style={TILE_STYLE(active)}>
        {teamInitials(team.is_personal ? 'Personal' : team.name)}
      </span>
      <span style={{ display: 'grid', gap: 2, minWidth: 0 }}>
        <span style={ELLIPSIS}>{name}</span>
        <span style={{ ...ELLIPSIS, fontSize: 11, color: 'var(--mut)', fontWeight: 400 }}>
          {rowSubtitle(team, size)}
        </span>
      </span>
    </button>
  )
}

const ELLIPSIS: React.CSSProperties = {
  fontSize: 12.5,
  fontWeight: 600,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
}

function TILE_STYLE(active: boolean): React.CSSProperties {
  return {
    flex: '0 0 30px',
    height: 30,
    borderRadius: 5,
    background: 'var(--sur2)',
    border: '1px solid var(--bd)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    color: active ? 'var(--acc)' : 'var(--mut)'
  }
}

function DashedButton({
  children,
  onClick
}: {
  children: string
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      className="interactive"
      onClick={onClick}
      style={{
        background: 'transparent',
        border: '1px dashed var(--bd)',
        borderRadius: 4,
        color: 'var(--mut)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 12,
        padding: '8px 10px',
        textAlign: 'left'
      }}
    >
      {children}
    </button>
  )
}

const REFUSAL_TEXT: Record<Exclude<MyInviteRefusal, 'at_limit'>, string> = {
  unverified: 'Verify your email to answer invitations sent to it.',
  gone: 'That invitation is no longer open.',
  already_member: "You're already on that team.",
  failed: "That didn't work. Try again."
}

function Invitations({
  invites,
  onUpgrade
}: {
  invites: MyInvites
  onUpgrade?: () => void
}): React.JSX.Element | null {
  const { status, notice } = invites
  const rows = invites.invites
  if (status !== 'unverified' && rows.length === 0 && notice === null) return null
  return (
    <section aria-label="Invitations" style={CARD_STYLE}>
      <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
        INVITATIONS{rows.length > 0 ? ` · ${rows.length}` : ''}
      </Mono>
      {status === 'unverified' && (
        <span style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
          Verify your email to see the invitations sent to it.
        </span>
      )}
      {rows.map((invite) => (
        <InvitationRow
          key={invite.id}
          invite={invite}
          busy={invites.busyId !== null}
          onAccept={() => void invites.accept(invite.id)}
          onDecline={() => void invites.decline(invite.id)}
        />
      ))}
      {notice?.refusal === 'at_limit' && (
        <PlanLimitNotice compact message={AT_LIMIT_MESSAGE} onUpgrade={onUpgrade} />
      )}
      {notice && notice.refusal !== 'at_limit' && (
        <span role="status" style={{ fontSize: 11.5, color: 'var(--warn)' }}>
          {REFUSAL_TEXT[notice.refusal]}
        </span>
      )}
    </section>
  )
}

const CARD_STYLE: React.CSSProperties = {
  display: 'grid',
  gap: 10,
  padding: 12,
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)'
}

function InvitationRow({
  invite,
  busy,
  onAccept,
  onDecline
}: {
  invite: MyInvite
  busy: boolean
  onAccept: () => void
  onDecline: () => void
}): React.JSX.Element {
  const by = invite.invited_by ? `${invite.invited_by.name} invited you` : 'You were invited'
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{invite.team.name}</span>
      <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>
        {by} as {withArticle(roleLabel(invite.role))}
      </span>
      <div style={{ display: 'flex', gap: 6 }}>
        <Button
          kind="soft"
          size="sm"
          disabled={busy}
          aria-label={`Accept invite to ${invite.team.name}`}
          onClick={onAccept}
        >
          Accept
        </Button>
        <Button
          kind="bare"
          size="sm"
          disabled={busy}
          aria-label={`Decline invite to ${invite.team.name}`}
          onClick={onDecline}
        >
          Decline
        </Button>
      </div>
    </div>
  )
}
