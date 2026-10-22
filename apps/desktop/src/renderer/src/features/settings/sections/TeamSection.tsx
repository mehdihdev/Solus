// Settings › Team (SOLUSDEV-318, design A): a summary of the active team —
// name, your role, size — with the way to Home's team page, where members and
// roles live, and every team I belong to with a way to switch. The SOLUSDEV-86
// controls (rename, new-project notification, the owner danger zone) stay
// reachable behind "Edit team" so nothing is lost. Rename is owner/admin;
// delete is owner-only and hidden for personal workspaces. Roles come from
// FND-01; mutations round-trip via useTeamData.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Switch } from '../../../components/ui/Switch'
import { Section, Row, StatusTag } from '../settingsUi'
import { Reveal } from '../Reveal'
import { settingsStagger } from '../settingsMotion'
import { DeleteConfirmModal } from '../../workspace/modals'
import { switchWorkspaceTeam } from '../../workspace/teamSwitch'
import type { TeamData } from '../../team/useTeamData'
import type { TeamDetail, TeamRole, TeamSummary } from '../../../lib/api/resources'

const inputStyle: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '6px 10px',
  fontSize: 12,
  fontFamily: 'var(--font-ui)',
  outline: 'none'
}

function TeamNameRow({
  name,
  canRename,
  onRename
}: {
  name: string
  canRename: boolean
  onRename: (name: string) => void
}): React.JSX.Element {
  const [value, setValue] = useState(name)
  if (!canRename) {
    return <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{name}</span>
  }
  return (
    <span style={{ display: 'inline-flex', gap: 8 }}>
      <input
        aria-label="Team name"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={inputStyle}
      />
      <Button kind="ghost" size="sm" onClick={() => onRename(value.trim())}>
        Save
      </Button>
    </span>
  )
}

/** Owner-only. The shared delete dialog names the team and what goes with it
 *  (HOME H5 security review H2: the old inline "Delete this team?" named neither). */
function DeleteTeamRow({
  teamName,
  onDelete
}: {
  teamName: string
  onDelete: () => Promise<boolean>
}): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  return (
    <>
      <Button kind="danger" size="sm" onClick={() => setConfirming(true)}>
        Delete team
      </Button>
      {confirming && (
        <DeleteConfirmModal
          name={teamName}
          noun="team"
          detail="and every project in it"
          onClose={() => setConfirming(false)}
          onConfirm={onDelete}
        />
      )}
    </>
  )
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
}

function roleLabel(role: TeamRole | string | null): string {
  return role ? role[0].toUpperCase() + role.slice(1) : 'Member'
}

function TeamTile({ name, size = 34 }: { name: string; size?: number }): React.JSX.Element {
  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: 4,
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontWeight: 600,
        fontSize: size > 30 ? 12 : 10.5,
        flexShrink: 0
      }}
    >
      {initials(name)}
    </span>
  )
}

/** Every team I belong to (GET /users/me teams); switching goes through the
 *  one team-switch choke point, which also closes a project of another team. */
function TeamList({
  teams,
  currentId
}: {
  teams: readonly TeamSummary[]
  currentId: string
}): React.JSX.Element {
  return (
    <ul
      aria-label="Your teams"
      style={{
        listStyle: 'none',
        margin: '14px 0 0',
        padding: 0,
        borderTop: '1px solid var(--bd)'
      }}
    >
      {teams.map((t, i) => {
        const current = t.team_id === currentId
        return (
          <li
            key={t.team_id}
            className="settings-row-in"
            style={{
              ...settingsStagger(i),
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '9px 0',
              borderBottom: '1px solid var(--bd)'
            }}
          >
            <TeamTile name={t.name} size={26} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: current ? 600 : 500 }}>{t.name}</div>
              <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>{roleLabel(t.role)}</div>
            </div>
            {t.is_personal && <StatusTag tone="mut">Personal</StatusTag>}
            {current ? (
              <StatusTag tone="acc">Current</StatusTag>
            ) : (
              <Button
                kind="ghost"
                size="sm"
                aria-label={`Switch to ${t.name}`}
                onClick={() => switchWorkspaceTeam(t.team_id, 'settings')}
              >
                Switch
              </Button>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function summaryLine(detail: TeamDetail, role: TeamRole | null): string {
  if (detail.is_personal) return 'Your personal workspace — just you.'
  const members = `${detail.member_count} member${detail.member_count === 1 ? '' : 's'}`
  return `You're ${role === 'admin' || role === 'owner' ? 'an' : 'a'} ${roleLabel(role)} · ${members}`
}

function TeamEditor({ team }: { team: TeamData }): React.JSX.Element | null {
  const { team: detail, myRole, actions } = team
  if (!detail) return null
  const canRename = myRole === 'owner' || myRole === 'admin'
  const showDanger = myRole === 'owner' && !detail.is_personal
  return (
    <div style={{ marginTop: 6 }}>
      <Row label="Name">
        <TeamNameRow
          name={detail.name}
          canRename={canRename}
          onRename={(name) => void actions.updateTeam({ name })}
        />
      </Row>
      <Row
        label="Notify team on new projects"
        description="Everyone on the team hears when a project is created."
      >
        <Switch
          ariaLabel="Notify team on new projects"
          checked={detail.settings.notify_project_created}
          onChange={(on) => void actions.updateTeam({ settings: { notify_project_created: on } })}
        />
      </Row>
      {showDanger && (
        <Row
          label={<span style={{ color: 'var(--err)' }}>Danger zone</span>}
          description="Owner only. Asks you to confirm by name first."
        >
          <DeleteTeamRow teamName={detail.name} onDelete={actions.deleteTeam} />
        </Row>
      )}
    </div>
  )
}

export interface TeamSectionProps {
  team: TeamData
  /** Home's team page (members, roles, invites). */
  onOpenTeam: () => void
}

export function TeamSection({ team, onOpenTeam }: TeamSectionProps): React.JSX.Element {
  const [editing, setEditing] = useState(false)
  const detail = team.team
  if (!detail) return <></>
  return (
    <Section
      id="team"
      title="Team"
      sub="The team you're working in now, and every team you belong to."
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <TeamTile name={detail.name} />
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{detail.name}</div>
          <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 2 }}>
            {summaryLine(detail, team.myRole)}
          </div>
        </div>
        <Button
          kind="bare"
          size="sm"
          aria-expanded={editing}
          onClick={() => setEditing((open) => !open)}
        >
          Edit team
        </Button>
        <Button kind="ghost" size="sm" onClick={onOpenTeam}>
          Open team page →
        </Button>
      </div>
      <Reveal open={editing}>
        <TeamEditor team={team} />
      </Reveal>
      {team.teams.length > 1 && <TeamList teams={team.teams} currentId={detail.id} />}
    </Section>
  )
}
