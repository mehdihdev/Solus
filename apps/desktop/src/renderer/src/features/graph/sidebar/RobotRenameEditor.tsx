// The inline rename, moved from the robot card to the sidebar heading (SOLUSDEV-250 P4).
// Failed drafts stay; a 409 waits for a refreshed version before Save re-enables.
import { useState } from 'react'
import type { Entity } from '../../../lib/api/resources'
import type { RobotSession, RobotView } from '../robots/robotSession'

export function RobotRenameEditor({
  entity,
  session,
  state,
  onClose
}: {
  entity: Entity
  session: RobotSession
  state: RobotView
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
