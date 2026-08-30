// One simulator source (SOLUSDEV-72). Available → real start controls
// (mujoco: one-click builtin demo scene; gazebo: topics; mcap-replay: a path
// under the SERVER's data root). Unavailable → the backend's reason, plainly,
// with the controls dead — an unavailable simulator must be unstartable.
// Isaac has no live adapter: its row explains the direct-script/MCAP paths
// and never offers a start it cannot perform.
import { useState } from 'react'
import { Button } from '../../../components/ui/Button'
import type {
  BenchSession,
  BenchSimulator,
  GazeboSimConfig,
  McapReplayConfig,
  MujocoSimConfig
} from '../../../lib/api/resources'
import { PICKER_FIELD_STYLE } from '../../onboarding/SelectionPicker'
import { SessionChip } from './SessionChip'
import { simulatorName } from './presentation'

export type SimStartConfig = MujocoSimConfig | GazeboSimConfig | McapReplayConfig

export interface SimulatorRowProps {
  simulator: BenchSimulator
  sessions: BenchSession[]
  /** Runner-level reason; non-null disables the whole row. */
  disabledReason: string | null
  /** Starts the sim session; resolves to an error text or null. */
  onStart: (config: SimStartConfig) => Promise<string | null>
  onStop: (sessionId: string) => void
}

/** The start controls per simulator kind. Isaac deliberately returns null —
 *  there is no in-app start to offer. */
function StartControls({
  simulator,
  disabled,
  onStart
}: {
  simulator: BenchSimulator
  disabled: boolean
  onStart: (config: SimStartConfig) => void
}): React.JSX.Element | null {
  const [value, setValue] = useState('')

  if (simulator.kind === 'mujoco') {
    return (
      <Button
        kind="primary"
        size="sm"
        aria-label="Start MuJoCo demo scene"
        disabled={disabled}
        onClick={() => onStart({ provider: 'mujoco' })}
      >
        Start demo scene
      </Button>
    )
  }
  if (simulator.kind === 'gazebo') {
    const topics = value
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    return (
      <>
        <input
          aria-label="Gazebo topics"
          placeholder="Topics, comma-separated"
          value={value}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          style={{ ...PICKER_FIELD_STYLE, width: 200 }}
        />
        <Button
          kind="primary"
          size="sm"
          aria-label="Start Gazebo"
          disabled={disabled || topics.length === 0}
          onClick={() => onStart({ provider: 'gazebo', topics })}
        >
          Start
        </Button>
      </>
    )
  }
  if (simulator.kind === 'mcap-replay') {
    return (
      <>
        <input
          aria-label="MCAP path under the bench data root"
          placeholder="Path under the server's data root"
          value={value}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          style={{ ...PICKER_FIELD_STYLE, width: 200 }}
        />
        <Button
          kind="primary"
          size="sm"
          aria-label="Start MCAP replay"
          disabled={disabled || !value.trim()}
          onClick={() => onStart({ provider: 'mcap-replay', mcap_path: value.trim() })}
        >
          Start
        </Button>
      </>
    )
  }
  return null
}

export function SimulatorRow({
  simulator,
  sessions,
  disabledReason,
  onStart,
  onStop
}: SimulatorRowProps): React.JSX.Element {
  const [error, setError] = useState<string | null>(null)
  // Runner missing beats the simulator's own reason; both make it unstartable.
  const reason = disabledReason ?? (simulator.available ? null : simulator.reason)

  const start = async (config: SimStartConfig): Promise<void> => {
    setError(null)
    setError(await onStart(config))
  }

  return (
    <div style={{ padding: '12px 0', borderBottom: '1px solid var(--bd)' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <div style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600 }}>
          {simulatorName(simulator.kind)}
        </div>
        <StartControls
          simulator={simulator}
          disabled={reason !== null}
          onStart={(config) => void start(config)}
        />
      </div>
      {reason && <div style={{ fontSize: 10.5, color: 'var(--mut)', marginTop: 4 }}>{reason}</div>}
      {error && <div style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 4 }}>{error}</div>}
      {sessions.map((session) => (
        <SessionChip key={session.id} session={session} onStop={onStop} />
      ))}
    </div>
  )
}
