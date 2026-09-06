// The Workspace's Add › Hardware panel: a Physical Robot (seven categories) and
// a Sourced part (SOLUSDEV-246 ST5 — the same sourcing panel the BOM uses).
import { useState } from 'react'
import type { SolMode } from '../../../store/settingsStore'
import { SourcingModal } from '../../sourcing/SourcingModal'
import type { RobotSession, RobotView } from './robotSession'

export function RobotHardware({
  session,
  state,
  online,
  mode
}: {
  session: RobotSession
  state: RobotView
  online: boolean
  mode: SolMode
}): React.JSX.Element {
  const [sourcing, setSourcing] = useState(false)
  const error = state.error?.key === 'create' ? state.error.message : null
  return (
    <div className="robot-hardware">
      <p>
        {mode === 'Guide'
          ? 'Create a robot to organize its physical parts. Each robot starts with seven hardware categories and uses the project name until you rename it.'
          : 'Create a robot with seven hardware categories. Rename it on the canvas.'}
      </p>
      <button
        type="button"
        disabled={!online || state.busy !== null}
        onClick={() => {
          void session.create()
        }}
      >
        {state.busy === 'create' ? 'Adding Physical Robot…' : 'Add Physical Robot'}
      </button>
      <p>
        {mode === 'Guide'
          ? 'Sourced: describe what the part must do, or let Solus derive it from a CAD assembly; compare candidates and the chosen one enters a robot category as planned.'
          : 'Sourced: requirement or CAD-derived torque → candidates → a planned part in a category.'}
      </p>
      <button type="button" disabled={!online} onClick={() => setSourcing(true)}>
        Find a sourced part
      </button>
      {!online && <p>Connect this project to add hardware.</p>}
      {error && <p role="alert">{error}</p>}
      {sourcing && (
        <SourcingModal
          projectId={session.projectId}
          door="workspace"
          onClose={() => setSourcing(false)}
          onSelected={() => void session.load()}
        />
      )}
    </div>
  )
}
