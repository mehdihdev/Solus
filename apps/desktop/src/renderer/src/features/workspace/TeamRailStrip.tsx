// SOLUSDEV-328 (design P2, docs/wireflows/home.md "Project page"): Home's team rail folded to a
// 64px initials strip while the project page is open, so the projects list fits beside the
// project. Every team (collaborative first, the active one current), Create and Join, a count when
// invitations wait (it opens the overview, where the full rail answers them), and the two ACCOUNT
// views as icon buttons.
import type { TeamSummary } from '../../lib/api/resources'
import { Icons } from '../../components/ui/icons.constants'
import type { HomePaneView } from './HomeAccountNav'
import { railOrder, teamInitials } from './teamLabels'

export const TEAM_STRIP_WIDTH = 64

export interface TeamRailStripProps {
  teams: readonly TeamSummary[]
  activeTeamId: string | null
  /** Pending invitations addressed to me. */
  invitations: number
  view: HomePaneView
  onSwitch: (teamId: string) => void
  onNewTeam: () => void
  onJoin: () => void
  onShow: (view: HomePaneView) => void
}

export function TeamRailStrip(props: TeamRailStripProps): React.JSX.Element {
  const { invitations, view, onShow } = props
  return (
    <aside aria-label="Teams" style={STRIP}>
      <ul aria-label="Your teams" style={LIST}>
        {railOrder(props.teams).map((team) => (
          <li key={team.team_id}>
            <TeamTile
              team={team}
              active={team.team_id === props.activeTeamId}
              onSwitch={props.onSwitch}
            />
          </li>
        ))}
      </ul>
      <IconButton label="Create a team" onClick={props.onNewTeam} dashed>
        <Icons.plus size={14} />
      </IconButton>
      <IconButton label="Join with an invite code" onClick={props.onJoin} dashed>
        <Icons.mail size={14} />
      </IconButton>
      {invitations > 0 && (
        <button
          type="button"
          className="interactive"
          aria-label={`${invitations} ${invitations === 1 ? 'invitation' : 'invitations'} waiting`}
          onClick={() => onShow('team')}
          style={BADGE}
        >
          {invitations}
        </button>
      )}
      <div style={{ flex: 1 }} />
      <IconButton
        label="Connected accounts"
        pressed={view === 'accounts'}
        onClick={() => onShow('accounts')}
      >
        <Icons.link size={14} />
      </IconButton>
      <IconButton
        label="Team & invites"
        pressed={view === 'members'}
        onClick={() => onShow('members')}
      >
        <Icons.team size={14} />
      </IconButton>
    </aside>
  )
}

function TeamTile({
  team,
  active,
  onSwitch
}: {
  team: TeamSummary
  active: boolean
  onSwitch: (teamId: string) => void
}): React.JSX.Element {
  const name = team.is_personal ? 'Personal workspace' : team.name
  return (
    <button
      type="button"
      aria-label={name}
      title={name}
      aria-current={active ? 'true' : undefined}
      className="interactive home-card"
      onClick={() => onSwitch(team.team_id)}
      style={{
        ...TILE,
        color: active ? 'var(--acc)' : 'var(--tx)',
        border: `1px solid ${active ? 'var(--acc)' : 'var(--bd)'}`
      }}
    >
      {teamInitials(team.is_personal ? 'Personal' : team.name)}
    </button>
  )
}

function IconButton({
  label,
  onClick,
  pressed,
  dashed = false,
  children
}: {
  label: string
  onClick: () => void
  pressed?: boolean
  dashed?: boolean
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className="interactive"
      onClick={onClick}
      style={{
        ...TILE,
        color: pressed ? 'var(--acc)' : 'var(--mut)',
        background: pressed ? 'var(--sur2)' : 'transparent',
        border: dashed ? '1px dashed var(--bd)' : '1px solid transparent'
      }}
    >
      {children}
    </button>
  )
}

const STRIP: React.CSSProperties = {
  flex: `0 0 ${TEAM_STRIP_WIDTH}px`,
  width: TEAM_STRIP_WIDTH,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: 8,
  padding: '16px 0 14px',
  boxSizing: 'border-box',
  borderRight: '1px solid var(--bd)',
  overflowY: 'auto',
  minHeight: 0
}

const LIST: React.CSSProperties = {
  listStyle: 'none',
  margin: 0,
  padding: 0,
  display: 'grid',
  gap: 8
}

const TILE: React.CSSProperties = {
  width: 36,
  height: 36,
  borderRadius: 6,
  background: 'var(--sur2)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  cursor: 'pointer',
  fontFamily: 'var(--font-mono)',
  fontSize: 11
}

const BADGE: React.CSSProperties = {
  minWidth: 20,
  height: 20,
  padding: '0 6px',
  borderRadius: 10,
  border: 'none',
  background: 'var(--acc)',
  color: 'var(--acc-ink)',
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  cursor: 'pointer'
}
