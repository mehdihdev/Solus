import { useState, type ReactNode } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { SolMode } from '../../../store/settingsStore'
import { editableRobot, type RobotSession, type RobotView } from './robotSession'

interface ContentProps {
  entity: Entity
  session: RobotSession
  state: RobotView
  online: boolean
  mode: SolMode
  onDelete: (entity: Entity) => void
}
export function RobotNodeContent({
  entity,
  session,
  state,
  online,
  mode,
  onDelete
}: ContentProps): ReactNode {
  const [editing, setEditing] = useState(false)
  if (entity.type === 'robot_category')
    return (
      <span>
        {mode === 'Guide'
          ? 'Parts assigned to this category appear inside.'
          : 'Assigned parts inside.'}
      </span>
    )
  if (!online || !editableRobot(entity, session.projectId)) return null
  if (editing)
    return (
      <RobotRenameEditor
        entity={entity}
        session={session}
        state={state}
        onClose={() => setEditing(false)}
      />
    )
  return (
    <div className="robot-node-actions">
      <button type="button" disabled={state.busy !== null} onClick={() => setEditing(true)}>
        Rename
      </button>
      <button type="button" disabled={state.busy !== null} onClick={() => onDelete(entity)}>
        Delete
      </button>
    </div>
  )
}
function RobotRenameEditor({
  entity,
  session,
  state,
  onClose
}: Pick<ContentProps, 'entity' | 'session' | 'state'> & {
  onClose: () => void
}): React.JSX.Element {
  const [draft, setDraft] = useState(entity.name)
  const [conflictVersion, setConflictVersion] = useState<number | null>(null)
  const error = state.error?.key === entity.id ? state.error : null
  const blocked =
    !draft.trim() ||
    draft.trim().length > 512 ||
    state.busy !== null ||
    conflictVersion === entity.version
  const submit = async (): Promise<void> => {
    if (await session.rename(entity, draft)) onClose()
    else if (session.snapshot().error?.conflict) setConflictVersion(entity.version ?? null)
  }
  return (
    <form
      className="robot-node-editor"
      onSubmit={(event) => {
        event.preventDefault()
        if (!blocked) void submit()
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          onClose()
        }
      }}
    >
      <label>
        Robot name
        <input
          autoFocus
          required
          maxLength={512}
          value={draft}
          disabled={state.busy !== null}
          onChange={(event) => setDraft(event.currentTarget.value)}
        />
      </label>
      {error && <p role="alert">{error.message}</p>}
      {conflictVersion !== null && <p>Current name: {entity.name}</p>}
      <div className="robot-node-actions">
        <button type="submit" disabled={blocked}>
          Save name
        </button>
        <button type="button" disabled={state.busy !== null} onClick={onClose}>
          Cancel rename
        </button>
      </div>
    </form>
  )
}
