// The team block atop Home's sidebar (SOLUSDEV-244 / HOME H5; stacked for the
// SOLUSDEV-317 sidebar): the active team, always visible; the switcher only
// with more than one team; one ⋯ menu carrying the account-level actions
// (Invite teammate for managers, Join team, New team) and Rename (admin+),
// Leave, and Delete (owner-only, never on the personal team); and where I stand
// against my plan's collaborative-team limit — stated honestly, with the
// upgrade path, never as a silent failure (ADR-023; the personal team never
// counts, ADR-025).
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import type { TeamRole, TeamSummary } from '../../lib/api/resources'
import type { TeamLimitPosition } from '../../lib/api/planLimit'
import { MANAGER_ROLES } from '../team/MembersPanel'
import { PlanLimitNotice } from './PlanLimitNotice'
import { TeamSelect } from './TeamSelect'

export interface TeamStripProps {
  team: TeamSummary | null
  teams: readonly TeamSummary[]
  /** From the team detail; null while unknown. */
  memberCount: number | null
  myRole: TeamRole | null
  teamLimit: TeamLimitPosition | null
  onSwitch: (teamId: string) => void
  onJoin: () => void
  onNewTeam: () => void
  onInvite: () => void
  onRename: () => void
  onLeave: () => void
  onDelete: () => void
  onUpgrade?: () => void
}

/** The proactive limit line: "2 of 2 collaborative teams on your plan". */
export function teamLimitText(limit: TeamLimitPosition | null): string | null {
  if (!limit || limit.max === null) return null
  return `${limit.current} of ${limit.max} collaborative teams on your plan · your personal team never counts`
}

/** The same sentence the server refuses with (services/limits.py) — no client
 *  claim about what an upgrade buys. */
export const AT_LIMIT_MESSAGE =
  "You're at your collaborative-team limit. Leave a team or upgrade your plan."

interface TeamMenuProps {
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

function TeamMenu(props: TeamMenuProps): React.JSX.Element {
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
              position: 'absolute',
              left: 0,
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

/** "personal workspace · 3 members" — only the facts that are known. */
function TeamSubtitle({
  team,
  memberCount
}: {
  team: TeamSummary | null
  memberCount: number | null
}): React.JSX.Element {
  const parts: string[] = []
  if (team?.is_personal) parts.push('personal workspace')
  if (memberCount !== null) parts.push(`${memberCount} ${memberCount === 1 ? 'member' : 'members'}`)
  return <span style={{ fontSize: 12, color: 'var(--mut)' }}>{parts.join(' · ')}</span>
}

function LimitLine({
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

export function TeamStrip(props: TeamStripProps): React.JSX.Element {
  const { team, teams, memberCount, myRole, teamLimit } = props
  const canManage = myRole !== null && MANAGER_ROLES.includes(myRole)
  const collaborative = team !== null && !team.is_personal
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <TeamSelect teams={teams} team={team} onSwitch={props.onSwitch} />
        <TeamMenu
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
      </div>
      <TeamSubtitle team={team} memberCount={memberCount} />
      <LimitLine teamLimit={teamLimit} onUpgrade={props.onUpgrade} />
    </div>
  )
}
