// SOLUSDEV-319 B8: the change chip a SOL turn shows for a direct bench-view write (wireflow
// live-bench-view.md §5; route doc bench-view.md §6–§7). Undo is a USER action: the user's own
// REST PATCH with the result's inverse ops, `undo: true` and its version — never a SOL call.
// The summary is Solus-composed but model-adjacent: rendered as plain text only.
import { useState } from 'react'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { canEditBenchView } from '../bench/view/BenchViewContext'
import { useBenchViewStore } from '../bench/view/useBenchView'
import { useMe } from '../workspace/useMe'
import type { BenchViewChange } from './solChatItems'

const CONFLICT_TEXT = 'View changed since — Undo unavailable'
const ERROR_TEXT = 'Undo failed — check your connection.'

type UndoState = 'idle' | 'pending' | 'undone' | 'conflict' | 'error'

const CHIP: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  fontSize: 11.5,
  color: 'var(--mut)',
  border: '1px solid var(--bd)',
  borderRadius: 6,
  padding: '4px 8px',
  marginTop: 6
}

/** The open project's team when the chip's project is open, else the active team. */
function useCanUndo(projectId: string): boolean {
  const teamId = useWorkspaceStore((s) =>
    s.project?.id === projectId ? (s.project.teamId ?? s.teamId) : s.teamId
  )
  const { me } = useMe()
  return teamId ? canEditBenchView(me, teamId) : false
}

function statusText(state: UndoState): string | null {
  if (state === 'undone') return 'Undone ✓'
  if (state === 'conflict') return CONFLICT_TEXT
  if (state === 'error') return ERROR_TEXT
  return null
}

export function BenchViewChangeCard({
  change,
  projectId
}: {
  change: BenchViewChange
  projectId: string
}): React.JSX.Element {
  const canUndo = useCanUndo(projectId)
  const [state, setState] = useState<UndoState>('idle')
  const { version, inverseOps } = change
  const undoable = canUndo && version !== null && inverseOps !== null && state !== 'undone'

  const onUndo = async (): Promise<void> => {
    if (version === null || inverseOps === null) return
    setState('pending')
    const outcome = await useBenchViewStore
      .getState()
      .undo(projectId, { version, inverseOps: [...inverseOps] })
    if (outcome.ok) setState('undone')
    else setState(outcome.failure.kind === 'conflict' ? 'conflict' : 'error')
  }

  const status = statusText(state)
  return (
    <div className="sol-bench-change" style={CHIP}>
      <span aria-hidden="true">⚙</span>
      <span style={{ flex: 1, minWidth: 0 }}>
        Bench view · <span>{change.summary}</span>
      </span>
      {status && <span role="status">{status}</span>}
      {undoable && (
        <button
          type="button"
          onClick={() => void onUndo()}
          disabled={state === 'pending' || state === 'conflict'}
        >
          Undo
        </button>
      )}
    </div>
  )
}

export function BenchViewChangesView({
  changes,
  projectId
}: {
  changes: readonly BenchViewChange[] | undefined
  projectId: string
}): React.JSX.Element | null {
  if (!changes?.length) return null
  return (
    <>
      {changes.map((change) => (
        <BenchViewChangeCard key={change.callId} change={change} projectId={projectId} />
      ))}
    </>
  )
}
