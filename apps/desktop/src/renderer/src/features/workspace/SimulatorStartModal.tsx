// Start one simulator from Home's Simulation tab (SOLUSDEV-244), in the
// connect wizard's visual language (link header, headline, one action area):
// MuJoCo runs the builtin demo scene in one click; Gazebo takes its topics;
// MCAP replay takes a path under the SERVER's data root. The session lands in
// the current project's Live Bench through POST /projects/{id}/bench/sessions —
// the backend's refusal is shown here, in place, never swallowed.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import type { BenchSimulator } from '../../lib/api/resources'
import { LinkHeader } from '../onboarding/ConnectWizardModal'
import { PICKER_FIELD_STYLE } from '../onboarding/SelectionPicker'
import {
  simulatorMark,
  simulatorName,
  type SimStartConfig
} from '../project/localconnections/presentation'
import { ModalShell } from './modals'

const INSTRUCTION: Readonly<Record<BenchSimulator['kind'], (project: string) => string>> = {
  mujoco: (project) => `Runs the builtin demo scene and streams it into ${project}'s Live Bench.`,
  gazebo: (project) => `Enter the Gazebo topics to stream into ${project}'s Live Bench.`,
  'mcap-replay': (project) =>
    `Enter the MCAP path under the server's bench data root to replay into ${project}'s Live Bench.`,
  isaac: () => 'Isaac Sim has no live adapter yet — use a direct script or an MCAP recording.'
}

export interface SimulatorStartModalProps {
  simulator: BenchSimulator
  projectName: string
  /** Starts the session; resolves to the backend's error text, or null. */
  onStart: (config: SimStartConfig) => Promise<string | null>
  onClose: () => void
}

/** The config this simulator kind needs, from one text field, or null when
 *  the field is incomplete (or the kind has no in-app start). */
function configFor(kind: BenchSimulator['kind'], value: string): SimStartConfig | null {
  if (kind === 'mujoco') return { provider: 'mujoco' }
  if (kind === 'gazebo') {
    const topics = value
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    return topics.length > 0 ? { provider: 'gazebo', topics } : null
  }
  if (kind === 'mcap-replay') {
    return value.trim() ? { provider: 'mcap-replay', mcap_path: value.trim() } : null
  }
  return null
}

export function SimulatorStartModal({
  simulator,
  projectName,
  onStart,
  onClose
}: SimulatorStartModalProps): React.JSX.Element {
  const name = simulatorName(simulator.kind)
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const config = configFor(simulator.kind, value)
  const status = busy ? 'busy' : error ? 'error' : 'idle'

  const start = async (): Promise<void> => {
    if (!config) return
    setBusy(true)
    setError(null)
    const failure = await onStart(config)
    setBusy(false)
    if (failure) setError(failure)
    else onClose()
  }

  return (
    <ModalShell onClose={onClose} width={520}>
      <div role="dialog" aria-modal="true" aria-label={`Start ${name}`} className="cw-pop">
        <LinkHeader
          entry={{ id: simulator.kind, name, mark: simulatorMark(simulator.kind) }}
          status={status}
        />
        <div style={{ textAlign: 'center', marginTop: 18 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>
            {error ? `Couldn't start ${name}` : `Start ${name}`}
          </div>
          <div
            data-testid="sim-instruction"
            style={{
              fontSize: 12,
              lineHeight: 1.55,
              marginTop: 6,
              color: error ? 'var(--err)' : 'var(--mut)'
            }}
          >
            {error ?? INSTRUCTION[simulator.kind](projectName)}
          </div>
          <div style={{ marginTop: 16, display: 'grid', gap: 8, justifyItems: 'center' }}>
            {simulator.kind === 'gazebo' && (
              <input
                aria-label="Gazebo topics"
                placeholder="Topics, comma-separated"
                value={value}
                disabled={busy}
                onChange={(e) => setValue(e.target.value)}
                style={{ ...PICKER_FIELD_STYLE, width: 320 }}
              />
            )}
            {simulator.kind === 'mcap-replay' && (
              <input
                aria-label="MCAP path under the bench data root"
                placeholder="Path under the server's data root"
                value={value}
                disabled={busy}
                onChange={(e) => setValue(e.target.value)}
                style={{ ...PICKER_FIELD_STYLE, width: 320 }}
              />
            )}
            <Button
              kind="primary"
              size="sm"
              disabled={busy || config === null}
              onClick={() => void start()}
            >
              {busy ? <Spinner size={11} color="var(--acc-ink)" /> : 'Start'}
            </Button>
          </div>
        </div>
      </div>
    </ModalShell>
  )
}
