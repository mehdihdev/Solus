// Teleoperation bar (wireflow live-bench-teleop.md): pick leader/follower,
// open the confirmation dialog, show running / stopped state with Stop.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { stopTeleop, type Teleop, type TeleopStopReason } from '../../lib/api/resources'
import { defaultTeleopPair, robotNameFromLabel, type RobotPanelInfo } from './robotGrouping'
import { TeleopDialog } from './TeleopDialog'

const STOP_REASON_TEXT: Partial<Record<TeleopStopReason, string>> = {
  leader_lost: 'leader connection lost',
  follower_lost: 'follower connection lost',
  session_ended: 'a session ended',
  shutdown: 'Solus shut down'
}

function stoppedText(reason: TeleopStopReason | null): string {
  const detail = reason ? STOP_REASON_TEXT[reason] : undefined
  return `Stopped — follower holding pose${detail ? ` · ${detail}` : ''}`
}

function RobotSelect({
  label,
  value,
  robots,
  onChange
}: {
  label: string
  value: string
  robots: readonly RobotPanelInfo[]
  onChange: (sessionId: string) => void
}): React.JSX.Element {
  return (
    <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
      {label}
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {robots.map((robot) => (
          <option key={robot.sessionId} value={robot.sessionId}>
            {robot.name}
          </option>
        ))}
      </select>
    </label>
  )
}

function RunningBar({
  projectId,
  teleop,
  onChanged
}: {
  projectId: string
  teleop: Teleop
  onChanged: () => void
}): React.JSX.Element {
  const [stopFailed, setStopFailed] = useState(false)
  async function stop(): Promise<void> {
    setStopFailed(false)
    try {
      await stopTeleop(projectId)
    } catch {
      setStopFailed(true)
    }
    onChanged()
  }
  const leader = robotNameFromLabel(teleop.leader.label)
  const follower = robotNameFromLabel(teleop.follower.label)
  return (
    <section className="bench-teleop bench-teleop-running" aria-label="Teleoperation">
      <span role="status">{`Teleoperating ${leader} → ${follower} · ${teleop.rate_hz} Hz`}</span>
      <Button size="sm" kind="danger" onClick={() => void stop()}>
        Stop
      </Button>
      {stopFailed && <span role="alert">Stop could not be confirmed. Try again.</span>}
    </section>
  )
}

function PairingBar({
  projectId,
  robots,
  stopped,
  defaults,
  onChanged
}: {
  projectId: string
  robots: readonly RobotPanelInfo[]
  stopped: Teleop | null
  defaults: { leader: string; follower: string }
  onChanged: () => void
}): React.JSX.Element {
  const [picked, setPicked] = useState<Partial<typeof defaults>>({})
  const [dialogOpen, setDialogOpen] = useState(false)
  const pick = (side: 'leader' | 'follower'): string => {
    const id = picked[side]
    return robots.some((robot) => robot.sessionId === id) ? (id as string) : defaults[side]
  }
  const leader = robots.find((r) => r.sessionId === pick('leader'))
  const follower = robots.find((r) => r.sessionId === pick('follower'))
  return (
    <section className="bench-teleop" aria-label="Teleoperation">
      <strong>Teleoperation</strong>
      <RobotSelect
        label="Leader"
        value={pick('leader')}
        robots={robots}
        onChange={(id) => setPicked({ ...picked, leader: id })}
      />
      <span aria-hidden="true">→</span>
      <RobotSelect
        label="Follower"
        value={pick('follower')}
        robots={robots}
        onChange={(id) => setPicked({ ...picked, follower: id })}
      />
      <Button
        size="sm"
        kind="primary"
        disabled={!leader || !follower || leader === follower}
        onClick={() => setDialogOpen(true)}
      >
        Teleoperate…
      </Button>
      {stopped && <span role="status">{stoppedText(stopped.stop_reason)}</span>}
      {dialogOpen && leader && follower && (
        <TeleopDialog
          projectId={projectId}
          leader={leader}
          follower={follower}
          onClose={() => setDialogOpen(false)}
          onStarted={() => {
            setDialogOpen(false)
            onChanged()
          }}
        />
      )}
    </section>
  )
}

export function TeleopBar({
  projectId,
  robots,
  teleop,
  onChanged
}: {
  projectId: string
  robots: readonly RobotPanelInfo[]
  teleop: Teleop | null
  onChanged: () => void
}): React.JSX.Element | null {
  // Running first: Stop must stay reachable even if a robot session briefly drops.
  if (teleop?.state === 'running') {
    return <RunningBar projectId={projectId} teleop={teleop} onChanged={onChanged} />
  }
  const defaults = defaultTeleopPair(robots)
  if (!defaults) return null
  return (
    <PairingBar
      projectId={projectId}
      robots={robots}
      stopped={teleop}
      defaults={defaults}
      onChanged={onChanged}
    />
  )
}
