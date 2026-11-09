// The active team's overview, Home's default pane (SOLUSDEV-319, multi-team Home, design D —
// docs/wireflows/home.md "Team overview"): a header naming the team, its plan and size, with
// the ⋯ menu and a role-aware Invite; the projects (passed in); a preview of the members that
// links to the full roster (Team & invites); "You in <team>"; and, for managers, the team's
// pending invites. The personal workspace has no roster: it offers a way to work with others
// instead (inviting from it creates a new team, ADR-025 — the workspace itself stays solo).
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { InviteApi, TeamMemberApi, TeamSummary } from '../../lib/api/resources'
import { relativeTime } from '../../lib/relativeTime'
import { MANAGER_ROLES } from '../team/MembersPanel'
import { roleLabel, teamInitials } from './teamLabels'
import { TeamMenu, type TeamMenuProps } from './TeamMenu'
import type { HomeTeam } from './useHomeTeam'

/** How many members the overview previews before linking to the full roster. */
export const MEMBER_PREVIEW = 6

export interface TeamOverviewProps {
  team: TeamSummary
  homeTeam: HomeTeam
  /** My user id, to find my own membership row. */
  meId: string | null
  projectCount: number
  /** The projects table, composed by Home. */
  projects: React.ReactNode
  menu: Omit<TeamMenuProps, 'team' | 'myRole'>
  onInvite: () => void
  onJoin: () => void
  onManageMembers: () => void
}

export function TeamOverview(props: TeamOverviewProps): React.JSX.Element {
  const personal = props.team.is_personal
  return (
    <div style={{ display: 'grid', gap: 22 }}>
      <Header {...props} />
      {props.projects}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
        {!personal && <MembersPreview {...props} />}
        <div style={{ flex: '1 1 280px', display: 'grid', gap: 12 }}>
          {personal ? <WorkWithOthers {...props} /> : <YouInTeam {...props} />}
          {!personal && <PendingInvites {...props} />}
        </div>
      </div>
    </div>
  )
}

function canManage(homeTeam: HomeTeam): boolean {
  return homeTeam.myRole !== null && MANAGER_ROLES.includes(homeTeam.myRole)
}

function headerLine(team: TeamSummary, homeTeam: HomeTeam): string {
  if (team.is_personal) return 'ONLY YOU'
  const plan = team.plan_status.replace(/_/g, ' ').toUpperCase()
  if (homeTeam.status !== 'ready') return plan
  const n = homeTeam.members.length
  return `${plan} · ${n} ${n === 1 ? 'MEMBER' : 'MEMBERS'}`
}

function Header(props: TeamOverviewProps): React.JSX.Element {
  const { team, homeTeam } = props
  const name = team.is_personal ? 'Personal workspace' : team.name
  return (
    <section style={HEADER_STYLE}>
      <span aria-hidden="true" style={TILE}>
        {teamInitials(team.is_personal ? 'Personal' : team.name)}
      </span>
      <div style={{ display: 'grid', gap: 4, flex: '1 1 240px', minWidth: 0 }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>{name}</h2>
        <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
          {headerLine(team, homeTeam)}
        </Mono>
      </div>
      {!team.is_personal && homeTeam.status === 'ready' && <Faces members={homeTeam.members} />}
      <InviteSlot {...props} />
      <TeamMenu team={team} myRole={homeTeam.myRole} {...props.menu} />
    </section>
  )
}

function InviteSlot({ team, homeTeam, onInvite }: TeamOverviewProps): React.JSX.Element | null {
  if (team.is_personal) return null
  if (canManage(homeTeam))
    return (
      <Button kind="primary" size="sm" onClick={onInvite}>
        Invite to {team.name}
      </Button>
    )
  if (homeTeam.myRole === null) return null
  return (
    <span style={{ fontSize: 12, color: 'var(--mut)' }}>
      You&apos;re a {roleLabel(homeTeam.myRole)} here · ask an owner or admin to invite
    </span>
  )
}

function Faces({ members }: { members: readonly TeamMemberApi[] }): React.JSX.Element {
  const shown = members.slice(0, 4)
  return (
    <span aria-hidden="true" style={{ display: 'flex', alignItems: 'center' }}>
      {shown.map((m, i) => (
        <span
          key={m.user_id}
          style={{
            marginLeft: i === 0 ? 0 : -6,
            borderRadius: '50%',
            border: '2px solid var(--sur)',
            display: 'inline-flex'
          }}
        >
          <Avatar name={m.name ?? m.email} size={26} />
        </span>
      ))}
      {members.length > shown.length && (
        <Mono size={10} style={{ marginLeft: 8 }}>
          +{members.length - shown.length}
        </Mono>
      )}
    </span>
  )
}

function MembersPreview({ homeTeam, onManageMembers }: TeamOverviewProps): React.JSX.Element {
  const { members } = homeTeam
  return (
    <section aria-label="Members preview" style={{ flex: '2 1 460px', display: 'grid', gap: 10 }}>
      <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
        MEMBERS{homeTeam.status === 'ready' ? ` · ${members.length}` : ''}
      </Mono>
      <div style={{ border: '1px solid var(--bd)', borderRadius: 4 }}>
        {homeTeam.status === 'ready' ? (
          <ul aria-label="Members" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {members.slice(0, MEMBER_PREVIEW).map((m) => (
              <MemberRow key={m.user_id} member={m} />
            ))}
          </ul>
        ) : (
          <div style={{ fontSize: 12.5, color: 'var(--mut)', padding: 14 }}>Loading the team…</div>
        )}
        {homeTeam.status === 'ready' && (
          <div style={{ padding: '8px 14px' }}>
            <button type="button" className="interactive" onClick={onManageMembers} style={LINK}>
              All {members.length} {members.length === 1 ? 'member' : 'members'} and invites
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

function MemberRow({ member }: { member: TeamMemberApi }): React.JSX.Element {
  return (
    <li
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 14px',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <Avatar name={member.name ?? member.email} size={24} />
      <span style={{ display: 'grid', gap: 2, flex: '1 1 160px', minWidth: 0 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{member.name ?? member.email}</span>
        <span style={{ fontSize: 11, color: 'var(--mut)' }}>{member.email}</span>
      </span>
      <span style={ROLE_PILL}>{roleLabel(member.role)}</span>
    </li>
  )
}

function YouInTeam({ team, homeTeam, meId, projectCount }: TeamOverviewProps): React.JSX.Element {
  const mine = homeTeam.members.find((m) => m.user_id === meId)
  const label = `You in ${team.name}`
  return (
    <section aria-label={label} style={CARD}>
      <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
        {label.toUpperCase()}
      </Mono>
      <Fact name="Role" value={homeTeam.myRole ? roleLabel(homeTeam.myRole) : '—'} />
      <Fact name="Joined" value={mine ? relativeTime(mine.joined_at) : '—'} />
      <Fact name="Projects" value={String(projectCount)} />
    </section>
  )
}

function Fact({ name, value }: { name: string; value: string }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
      <span style={{ color: 'var(--mut)' }}>{name}</span>
      <span>{value}</span>
    </div>
  )
}

function inviteeLabel(invite: InviteApi): string {
  return invite.email ?? (invite.github_login ? `@${invite.github_login}` : 'Invitee')
}

function PendingInvites({
  homeTeam,
  onManageMembers
}: TeamOverviewProps): React.JSX.Element | null {
  if (!canManage(homeTeam) || homeTeam.invites.length === 0) return null
  return (
    <section
      aria-label="Pending invites"
      style={{ ...CARD, borderStyle: 'dashed', background: 'transparent' }}
    >
      <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
        PENDING INVITES · {homeTeam.invites.length}
      </Mono>
      {homeTeam.invites.slice(0, 4).map((invite) => (
        <span key={invite.id} style={{ fontSize: 12, color: 'var(--mut)' }}>
          {inviteeLabel(invite)} · {roleLabel(invite.role)} · sent {relativeTime(invite.created_at)}
        </span>
      ))}
      <button type="button" className="interactive" onClick={onManageMembers} style={LINK}>
        Manage invites
      </button>
    </section>
  )
}

function WorkWithOthers({ onInvite, onJoin }: TeamOverviewProps): React.JSX.Element {
  return (
    <section aria-label="Work with others" style={CARD}>
      <Mono size={9.5} style={{ letterSpacing: '0.08em' }}>
        WORK WITH OTHERS
      </Mono>
      <span style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
        Inviting someone starts a new team for the two of you — your personal workspace stays yours
        alone. Or join a team you were invited to.
      </span>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        <Button kind="primary" size="sm" onClick={onInvite}>
          Invite a teammate
        </Button>
        <Button kind="ghost" size="sm" onClick={onJoin}>
          Join with an invite code
        </Button>
      </div>
    </section>
  )
}

const HEADER_STYLE: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  alignItems: 'center',
  gap: 16,
  padding: 18,
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)'
}

const TILE: React.CSSProperties = {
  width: 44,
  height: 44,
  borderRadius: 6,
  background: 'var(--sur2)',
  border: '1px solid var(--bd)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontFamily: 'var(--font-mono)',
  fontSize: 14,
  color: 'var(--acc)'
}

const CARD: React.CSSProperties = {
  display: 'grid',
  gap: 9,
  padding: 14,
  border: '1px solid var(--bd)',
  borderRadius: 4,
  background: 'var(--sur)'
}

const ROLE_PILL: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.06em',
  padding: '2px 8px',
  border: '1px solid var(--bd)',
  borderRadius: 3
}

const LINK: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  padding: 0,
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12,
  textAlign: 'left'
}
