// Home's ACCOUNT card (SOLUSDEV-317, concept B): pinned at the foot of the
// sidebar, two rows that swap the pane to the Team & invites or Connected
// accounts view, each with a one-line status. A status that is not known yet
// is left out — never invented.
import { Mono } from '../../components/ui/Mono'

/** What Home's right pane shows: the current project, or an account-level card. */
export type HomePaneView = 'project' | 'members' | 'accounts'

/** The active team's roster position. */
export interface TeamPosition {
  members: number
  pending: number
}

/** Linked account grants by health (HOME H4): healthy vs. needs a look. */
export interface AccountsPosition {
  healthy: number
  attention: number
}

export interface HomeAccountNavProps {
  view: HomePaneView
  team: TeamPosition | null
  accounts: AccountsPosition | null
  onShow: (view: HomePaneView) => void
}

interface Status {
  text: string
  tone: string
}

function teamStatus(team: TeamPosition | null): Status | null {
  if (!team) return null
  if (team.members <= 1 && team.pending === 0) return { text: 'JUST YOU', tone: 'var(--mut)' }
  const members = `${team.members} ${team.members === 1 ? 'MEMBER' : 'MEMBERS'}`
  const text = team.pending > 0 ? `${members} · ${team.pending} PENDING` : members
  return { text, tone: 'var(--mut)' }
}

function accountsStatus(accounts: AccountsPosition | null): Status | null {
  if (!accounts) return null
  if (accounts.attention > 0)
    return { text: `${accounts.attention} NEED ATTENTION`, tone: 'var(--warn)' }
  if (accounts.healthy === 0) return { text: 'NONE LINKED', tone: 'var(--mut)' }
  return { text: `${accounts.healthy} HEALTHY`, tone: 'var(--ok)' }
}

export function HomeAccountNav({
  view,
  team,
  accounts,
  onShow
}: HomeAccountNavProps): React.JSX.Element {
  return (
    <div
      style={{
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 4,
        padding: '12px 12px 6px'
      }}
    >
      <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
        ACCOUNT
      </Mono>
      <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column' }}>
        <NavRow
          label="Connected accounts"
          status={accountsStatus(accounts)}
          active={view === 'accounts'}
          onClick={() => onShow('accounts')}
        />
        <NavRow
          label="Team & invites"
          status={teamStatus(team)}
          active={view === 'members'}
          onClick={() => onShow('members')}
        />
      </div>
    </div>
  )
}

function NavRow({
  label,
  status,
  active,
  onClick
}: {
  label: string
  status: Status | null
  active: boolean
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      aria-pressed={active}
      className="interactive"
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        width: '100%',
        textAlign: 'left',
        background: active ? 'var(--sur2)' : 'transparent',
        border: 'none',
        borderRadius: 4,
        color: active ? 'var(--acc)' : 'var(--tx)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 12.5,
        padding: '8px 6px'
      }}
    >
      <span style={{ flex: 1 }}>{label}</span>
      {status && (
        <Mono size={9} color={status.tone}>
          {status.text}
        </Mono>
      )}
    </button>
  )
}
