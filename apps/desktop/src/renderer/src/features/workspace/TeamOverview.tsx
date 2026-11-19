// The active team's overview, Home's default pane (SOLUSDEV-319 design D; SOLUSDEV-328 A2 —
// docs/wireflows/home.md "Team overview" and "Fills the window"). A header bar names the team, its
// plan and size, with the ⋯ menu and a role-aware Invite. Beneath, full-height columns that each
// scroll on their own, picked from the overview's OWN width (so the docked SOL sidebar reflows it
// like a narrower window): projects │ team when split; projects │ current project │ team when
// wide; one scroll with the team column under the projects when narrow.
import { useRef } from 'react'
import { Avatar } from '../../components/ui/Avatar'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { TeamMemberApi, TeamSummary } from '../../lib/api/resources'
import { useHomeLayout, type HomeLayout } from './homeLayout'
import { TeamColumn, canManageTeam } from './TeamColumn'
import { roleLabel, teamInitials } from './teamLabels'
import { TeamMenu, type TeamMenuProps } from './TeamMenu'
import type { HomeTeam } from './useHomeTeam'

/** The team column's fixed width beside the fluid columns (sol-page.md's context column, +20). */
export const TEAM_COLUMN_WIDTH = 340

export interface TeamOverviewProps {
  team: TeamSummary
  homeTeam: HomeTeam
  /** The projects table, composed by Home for the layout on show. */
  projects: (layout: HomeLayout) => React.ReactNode
  /** The current project's column, shown only when the overview is wide. */
  projectColumn: React.ReactNode
  menu: Omit<TeamMenuProps, 'team' | 'myRole'>
  onInvite: () => void
  onManageMembers: () => void
  /** Overrides the measured layout (tests, stories). */
  layout?: HomeLayout
}

export function TeamOverview(props: TeamOverviewProps): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  const measured = useHomeLayout(ref)
  const layout = props.layout ?? measured
  const stacked = layout === 'stack'
  return (
    <div ref={ref} data-testid="team-overview" data-layout={layout} style={ROOT[layout]}>
      <Header {...props} />
      <div data-testid="team-overview-body" style={BODY[layout]}>
        <div data-testid="home-col-projects" className="home-vt-projects" style={column(stacked)}>
          <div style={{ padding: '18px 24px 24px' }}>{props.projects(layout)}</div>
        </div>
        {layout === 'wide' && (
          <div data-testid="home-col-project" style={{ ...column(false), ...DIVIDER }}>
            {props.projectColumn}
          </div>
        )}
        <div data-testid="home-col-team" style={stacked ? STACKED_TEAM : TEAM_COLUMN}>
          <TeamColumn
            team={props.team}
            homeTeam={props.homeTeam}
            onManageMembers={props.onManageMembers}
            stacked={stacked}
          />
        </div>
      </div>
    </div>
  )
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
      <div style={{ display: 'grid', gap: 3, flex: '1 1 240px', minWidth: 0 }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{name}</h2>
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
  if (canManageTeam(homeTeam))
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
            border: '2px solid var(--bg)',
            display: 'inline-flex'
          }}
        >
          <Avatar name={m.name ?? m.email} size={24} />
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

/** A column scrolls on its own unless the overview is one stacked scroll. */
function column(stacked: boolean): React.CSSProperties {
  return stacked
    ? { minWidth: 0 }
    : { minWidth: 0, minHeight: 0, overflowY: 'auto', overflowX: 'hidden' }
}

const FILL: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column'
}

const ROOT: Record<HomeLayout, React.CSSProperties> = {
  stack: { ...FILL, overflowY: 'auto' },
  split: { ...FILL, overflow: 'hidden' },
  wide: { ...FILL, overflow: 'hidden' }
}

const GRID: React.CSSProperties = { flex: 1, minHeight: 0, display: 'grid' }

const BODY: Record<HomeLayout, React.CSSProperties> = {
  stack: { display: 'block' },
  split: { ...GRID, gridTemplateColumns: `minmax(0, 1fr) ${TEAM_COLUMN_WIDTH}px` },
  wide: {
    ...GRID,
    gridTemplateColumns: `minmax(360px, 0.85fr) minmax(0, 1.3fr) ${TEAM_COLUMN_WIDTH}px`
  }
}

const DIVIDER: React.CSSProperties = { borderLeft: '1px solid var(--bd)' }

/** Its sections scroll on their own (TeamColumn), so the column itself never does. */
const TEAM_COLUMN: React.CSSProperties = {
  ...DIVIDER,
  minWidth: 0,
  minHeight: 0,
  overflow: 'hidden',
  background: 'var(--sur)'
}

const STACKED_TEAM: React.CSSProperties = { minWidth: 0, borderTop: '1px solid var(--bd)' }

const HEADER_STYLE: React.CSSProperties = {
  flex: 'none',
  display: 'flex',
  flexWrap: 'wrap',
  alignItems: 'center',
  gap: 14,
  padding: '12px 24px',
  minHeight: 56,
  boxSizing: 'border-box',
  borderBottom: '1px solid var(--bd)'
}

const TILE: React.CSSProperties = {
  width: 32,
  height: 32,
  borderRadius: 5,
  background: 'var(--sur2)',
  border: '1px solid var(--bd)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--acc)'
}
