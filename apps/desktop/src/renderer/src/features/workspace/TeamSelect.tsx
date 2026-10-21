// The active-team switcher (SOLUSDEV-242; the team title itself since
// SOLUSDEV-317): the team's name is the control — with more than one team it
// is a button whose menu lists every team, the active one checked. Picking one
// writes `workspaceStore.teamId` through `onSwitch`, so Home and the project
// switcher re-resolve off it (activeTeam.ts). With a single team the name is
// plain text: there is nothing to choose.
import { useRef, useState } from 'react'
import type { TeamSummary } from '../../lib/api/resources'

export interface TeamSelectProps {
  teams: readonly TeamSummary[]
  /** The active team, or null when the user is on none. */
  team: TeamSummary | null
  onSwitch: (teamId: string) => void
}

export function TeamSelect({ teams, team, onSwitch }: TeamSelectProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const name = (
    <span data-testid="team-name" style={NAME}>
      {team?.name ?? 'No team'}
    </span>
  )
  if (teams.length < 2) return <h2 style={TITLE}>{name}</h2>
  const pick = (teamId: string): void => {
    setOpen(false)
    if (teamId !== team?.team_id) onSwitch(teamId)
  }
  return (
    <div
      style={{ position: 'relative', minWidth: 0, flex: '1 1 auto' }}
      onKeyDown={(e) => {
        if (e.key !== 'Escape' || !open) return
        setOpen(false)
        trigger.current?.focus()
      }}
    >
      <h2 style={TITLE}>
        <button
          ref={trigger}
          type="button"
          aria-label={`${team?.name ?? 'No team'}, switch team`}
          aria-haspopup="menu"
          aria-expanded={open}
          className="interactive"
          onClick={() => setOpen((v) => !v)}
          style={TRIGGER}
        >
          {name}
          <Chevron open={open} />
        </button>
      </h2>
      {open && (
        <TeamMenu
          teams={teams}
          activeId={team?.team_id}
          onPick={pick}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  )
}

/** The title's chevron; it turns while the menu is open. */
function Chevron({ open }: { open: boolean }): React.JSX.Element {
  return (
    <svg
      data-chevron
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--mut)"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        flexShrink: 0,
        transform: open ? 'rotate(180deg)' : undefined,
        transition: 'transform 0.12s'
      }}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  )
}

/** Every team as a radio item, the active one checked, personal ones marked. */
function TeamMenu({
  teams,
  activeId,
  onPick,
  onClose
}: {
  teams: readonly TeamSummary[]
  activeId: string | undefined
  onPick: (teamId: string) => void
  onClose: () => void
}): React.JSX.Element {
  return (
    <>
      <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onClick={onClose} />
      <div role="menu" aria-label="Teams" className="popover-in" style={MENU}>
        {teams.map((t) => (
          <button
            key={t.team_id}
            type="button"
            role="menuitemradio"
            aria-checked={t.team_id === activeId}
            className="interactive"
            onClick={() => onPick(t.team_id)}
            style={ITEM}
          >
            <span style={{ width: 12, color: 'var(--acc)' }} aria-hidden="true">
              {t.team_id === activeId ? '✓' : ''}
            </span>
            <span style={{ flex: 1, ...NAME }}>{t.name}</span>
            {t.is_personal && <span style={{ fontSize: 11, color: 'var(--mut)' }}>personal</span>}
          </button>
        ))}
      </div>
    </>
  )
}

const TITLE: React.CSSProperties = { margin: 0, fontSize: 13.5, fontWeight: 600, minWidth: 0 }

const NAME: React.CSSProperties = {
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
}

const TRIGGER: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  maxWidth: '100%',
  background: 'transparent',
  border: 'none',
  borderRadius: 4,
  color: 'var(--tx)',
  cursor: 'pointer',
  font: 'inherit',
  padding: '2px 4px',
  margin: '0 -4px'
}

const MENU: React.CSSProperties = {
  position: 'absolute',
  left: 0,
  top: '100%',
  zIndex: 61,
  minWidth: 220,
  marginTop: 4,
  background: 'var(--sur)',
  border: '1px solid var(--bd)',
  borderRadius: 4,
  boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
  overflow: 'hidden'
}

const ITEM: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  width: '100%',
  textAlign: 'left',
  background: 'transparent',
  border: 'none',
  color: 'var(--tx)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 12.5,
  padding: '9px 12px'
}
