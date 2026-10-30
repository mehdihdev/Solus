// One panel per saved-robot session: that robot's scene above its signal cards,
// plus a confirmed Release (torque off).
import { lazy, Suspense, useCallback, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { releaseRobot, type Teleop } from '../../lib/api/resources'
import { ModalShell } from '../workspace/modals'
import { DeviceBenchView } from './DeviceBenchView'
import type { RobotPanelInfo } from './robotGrouping'

const ScenePanel = lazy(() =>
  import('./scene/ScenePanel').then((module) => ({ default: module.ScenePanel }))
)

function ReleaseConfirm({
  robot,
  projectId,
  onDone
}: {
  robot: RobotPanelInfo
  projectId: string
  onDone: () => void
}): React.JSX.Element {
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  async function confirm(): Promise<void> {
    setBusy(true)
    setFailed(false)
    try {
      await releaseRobot(projectId, robot.sessionId)
      onDone()
    } catch {
      setFailed(true)
      setBusy(false)
    }
  }
  return (
    <ModalShell onClose={onDone} width={420}>
      <div role="dialog" aria-modal="true" aria-label={`Release ${robot.name}`}>
        <p style={{ fontSize: 14, lineHeight: 1.5 }}>
          {`Turn off torque on ${robot.name}? It will go limp and may fall.`}
        </p>
        {failed && (
          <p role="alert" style={{ color: 'var(--err)', fontSize: 12.5 }}>
            {robot.name} could not be released. It may be teleoperating or not support torque
            control.
          </p>
        )}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button kind="ghost" onClick={onDone}>
            Cancel
          </Button>
          <Button kind="danger" disabled={busy} onClick={() => void confirm()}>
            Turn off torque
          </Button>
        </div>
      </div>
    </ModalShell>
  )
}

function StreamedDeviceView({
  streamKey,
  onStream,
  ...props
}: Omit<React.ComponentProps<typeof DeviceBenchView>, 'onStreamChange'> & {
  streamKey: string
  onStream: (key: string, live: boolean) => void
}): React.JSX.Element {
  const onStreamChange = useCallback(
    (live: boolean) => onStream(streamKey, live),
    [onStream, streamKey]
  )
  return <DeviceBenchView {...props} onStreamChange={onStreamChange} />
}

export function RobotPanels({
  projectId,
  robots,
  teleop,
  paused,
  focusEntityId,
  onStream,
  onConfirmBoard
}: {
  projectId: string
  robots: readonly RobotPanelInfo[]
  teleop: Teleop | null
  paused: boolean
  focusEntityId?: string
  onStream: (key: string, live: boolean) => void
  onConfirmBoard?: () => void
}): React.JSX.Element | null {
  const [releasing, setReleasing] = useState<RobotPanelInfo | null>(null)
  if (robots.length === 0) return null
  const followerId = teleop?.state === 'running' ? teleop.follower.session_id : null
  return (
    <div className="bench-robot-panels">
      {robots.map((robot) => (
        <section key={robot.sessionId} className="bench-robot-panel" aria-label={robot.name}>
          <header>
            <h2 style={{ fontSize: 13, margin: 0 }}>{robot.name}</h2>
            <Button
              size="sm"
              kind="ghost"
              disabled={followerId === robot.sessionId}
              title={followerId === robot.sessionId ? 'Stop teleoperation first' : undefined}
              onClick={() => setReleasing(robot)}
            >
              Release…
            </Button>
          </header>
          <Suspense fallback={<p role="status">Loading scene…</p>}>
            <ScenePanel projectId={projectId} robotId={robot.robotId} paused={paused} compact />
          </Suspense>
          <StreamedDeviceView
            streamKey={robot.sessionId}
            onStream={onStream}
            projectId={projectId}
            deviceIds={robot.deviceIds}
            focusEntityId={focusEntityId}
            paused={paused}
            onConfirmBoard={onConfirmBoard}
            showReasoning={false}
          />
        </section>
      ))}
      {releasing && (
        <ReleaseConfirm robot={releasing} projectId={projectId} onDone={() => setReleasing(null)} />
      )}
    </div>
  )
}
