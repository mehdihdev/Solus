// Team settings: rename, new-project notification, and the delete danger zone.
// Rename is owner/admin; delete is owner-only and hidden for personal
// workspaces. Roles come from FND-01; mutations round-trip via useTeamData.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Segmented } from '../../../components/ui/Segmented'
import { Section, Row } from '../settingsUi'
import { DeleteConfirmModal } from '../../workspace/modals'
import type { TeamData } from '../../team/useTeamData'

const NOTIFY_OPTIONS = ['On', 'Off'] as const

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

export function TeamSection({ team }: { team: TeamData }): React.JSX.Element {
  const { team: detail, myRole, actions } = team
  if (!detail) return <></>
  const notify = detail.settings.notify_project_created
  const canRename = myRole === 'owner' || myRole === 'admin'
  const showDanger = myRole === 'owner' && !detail.is_personal

  return (
    <Section title="Team" sub="Shared with everyone on this team.">
      <Row label="Name">
        <TeamNameRow
          name={detail.name}
          canRename={canRename}
          onRename={(name) => void actions.updateTeam({ name })}
        />
      </Row>
      <Row label="Notify team on new projects">
        <Segmented
          size="sm"
          ariaLabel="Notify on new projects"
          options={NOTIFY_OPTIONS}
          value={notify ? 'On' : 'Off'}
          onChange={(v) =>
            void actions.updateTeam({ settings: { notify_project_created: v === 'On' } })
          }
        />
      </Row>
      {showDanger && (
        <Row label="Danger zone">
          <DeleteTeamRow teamName={detail.name} onDelete={actions.deleteTeam} />
        </Row>
      )}
    </Section>
  )
}
