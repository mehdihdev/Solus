// Team settings: rename, new-project notification, and the delete danger zone.
// Rename is owner/admin; delete is owner-only and hidden for personal
// workspaces. Roles come from FND-01; mutations round-trip via useTeamData.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import { Segmented } from '../../../components/ui/Segmented'
import { Section, Row } from '../settingsUi'
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

function DeleteTeamRow({ onDelete }: { onDelete: () => void }): React.JSX.Element {
  const [confirming, setConfirming] = useState(false)
  if (!confirming) {
    return (
      <Button kind="danger" size="sm" onClick={() => setConfirming(true)}>
        Delete team
      </Button>
    )
  }
  return (
    <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
      <span style={{ fontSize: 11.5, color: 'var(--mut)' }}>Delete this team?</span>
      <Button kind="ghost" size="sm" onClick={() => setConfirming(false)}>
        Cancel
      </Button>
      <Button kind="danger" size="sm" onClick={onDelete}>
        Confirm delete
      </Button>
    </span>
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
          <DeleteTeamRow onDelete={() => void actions.deleteTeam()} />
        </Row>
      )}
    </Section>
  )
}
