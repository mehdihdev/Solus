// The active team's ⋯ menu and plan-limit line (SOLUSDEV-244 / HOME H5; on the team
// overview's header since SOLUSDEV-319's team rail): the account-level actions (Invite
// teammate for managers, Join team, New team) and Rename (admin+), Leave, and Delete
// (owner-only, never on the personal team); and where I stand against my plan's
// collaborative-team limit — stated honestly, with the upgrade path, never as a silent
// failure (ADR-023; the personal team never counts, ADR-025).
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import type { TeamRole, TeamSummary } from '../../lib/api/resources'
import type { TeamLimitPosition } from '../../lib/api/planLimit'
import { MANAGER_ROLES } from '../team/MembersPanel'
import { PlanLimitNotice } from './PlanLimitNotice'
import { AT_LIMIT_MESSAGE, teamLimitText } from './teamLabels'

interface MenuButtonProps {
  canInvite: boolean
  canRename: boolean
  canLeave: boolean
  canDelete: boolean
  onInvite: () => void
  onJoin: () => void
  onNewTeam: () => void
  onRename: () => void
  onLeave: () => void
  onDelete: () => void
}

function MenuButton(props: MenuButtonProps): React.JSX.Element {
  const { canInvite, canRename, canLeave, canDelete } = props
  const [open, setOpen] = useState(false)
  const pick = (action: () => void): void => {
    setOpen(false)
    action()
  }
  return (
    <div style={{ position: 'relative' }}>
      <Button kind="bare" size="sm" aria-label="Team menu" onClick={() => setOpen((v) => !v)}>
        ⋯
      </Button>
      {open && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 60 }} onClick={() => setOpen(false)} />
          <div
            role="menu"
            className="popover-in"
            style={{
              // Anchored to the ⋯'s right edge: the ⋯ sits at its container's
              // edge, so opening rightward ran past it (clipped + side scroll).
              position: 'absolute',
              right: 0,
              top: '100%',
              zIndex: 61,
              minWidth: 160,
              background: 'var(--sur)',
              border: '1px solid var(--bd)',
              borderRadius: 4,
              boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
              overflow: 'hidden'
            }}
          >
            {canInvite && <MenuItem onClick={() => pick(props.onInvite)}>Invite teammate</MenuItem>}
            <MenuItem onClick={() => pick(props.onJoin)}>Join team</MenuItem>
            <MenuItem onClick={() => pick(props.onNewTeam)}>New team</MenuItem>
            {(canRename || canLeave || canDelete) && (
              <div role="separator" style={{ height: 1, background: 'var(--bd)' }} />
            )}
            {canRename && <MenuItem onClick={() => pick(props.onRename)}>Rename team</MenuItem>}
            {canLeave && <MenuItem onClick={() => pick(props.onLeave)}>Leave team</MenuItem>}
            {canDelete && (
              <MenuItem danger onClick={() => pick(props.onDelete)}>
                Delete team
              </MenuItem>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function MenuItem({
  children,
  danger = false,
  onClick
}: {
  children: React.ReactNode
  danger?: boolean
  onClick: () => void
}): React.JSX.Element {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="interactive"
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        background: 'transparent',
        border: 'none',
        color: danger ? 'var(--err)' : 'var(--tx)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        fontSize: 12.5,
        padding: '9px 12px'
      }}
    >
      {children}
    </button>
  )
}

export function TeamLimitLine({
  teamLimit,
  onUpgrade
}: {
  teamLimit: TeamLimitPosition | null
  onUpgrade?: () => void
}): React.JSX.Element | null {
  const line = teamLimitText(teamLimit)
  if (!line) return null
  return (
    <div
      data-testid="team-limit"
      style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}
    >
      <span style={{ fontSize: 11, color: 'var(--mut)' }}>{line}</span>
      {teamLimit?.atLimit && (
        <PlanLimitNotice compact message={AT_LIMIT_MESSAGE} onUpgrade={onUpgrade} />
      )}
    </div>
  )
}

export interface TeamMenuProps {
  team: TeamSummary | null
  myRole: TeamRole | null
  onJoin: () => void
  onNewTeam: () => void
  onInvite: () => void
  onRename: () => void
  onLeave: () => void
  onDelete: () => void
}

/** The ⋯ for the active team, its items gated by my role and the team's kind. */
export function TeamMenu(props: TeamMenuProps): React.JSX.Element {
  const { team, myRole } = props
  const canManage = myRole !== null && MANAGER_ROLES.includes(myRole)
  const collaborative = team !== null && !team.is_personal
  return (
    <MenuButton
      canInvite={team !== null && canManage}
      canRename={team !== null && canManage}
      canLeave={collaborative}
      canDelete={collaborative && myRole === 'owner'}
      onInvite={props.onInvite}
      onJoin={props.onJoin}
      onNewTeam={props.onNewTeam}
      onRename={props.onRename}
      onLeave={props.onLeave}
      onDelete={props.onDelete}
    />
  )
}
