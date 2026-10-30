// The Live Bench body: one panel per saved robot (with the teleoperation bar)
// above the single legacy layout for every non-robot device.
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import type { BenchSession } from '../../lib/api/resources'
import { DeviceBenchView } from './DeviceBenchView'
import { RobotPanels } from './RobotPanels'
import { TeleopBar } from './TeleopBar'
import { groupRobotSessions } from './robotGrouping'
import { useTeleopState } from './useTeleopState'

const ScenePanel = lazy(() =>
  import('./scene/ScenePanel').then((module) => ({ default: module.ScenePanel }))
)

const OTHERS_KEY = 'others'

function LegacyPanes({
  projectId,
  deviceIds,
  panelledRobotIds,
  paused,
  focusEntityId,
  onStream,
  onConfirmBoard
}: {
  projectId: string
  deviceIds: string[]
  panelledRobotIds: readonly string[]
  paused: boolean
  focusEntityId?: string
  onStream: (key: string, live: boolean) => void
  onConfirmBoard?: () => void
}): React.JSX.Element {
  const onStreamChange = useCallback((live: boolean) => onStream(OTHERS_KEY, live), [onStream])
  return (
    <div className="bench-panes">
      <aside className="bench-left">
        <Suspense fallback={<p role="status">Loading scene…</p>}>
          <ScenePanel
            projectId={projectId}
            paused={paused}
            compact
            excludeRobotIds={panelledRobotIds}
          />
        </Suspense>
        <div className="bench-sensor-empty">
          No camera stream available. Recorded video is time-aligned in Runs below.
        </div>
        <div className="bench-sensor-empty">
          No LiDAR or depth stream available. Recorded point clouds appear in Runs below.
        </div>
        <p className="bench-scene-caption">
          Recorded sensor frames remain time-aligned in the Runs pane below.
        </p>
      </aside>
      <DeviceBenchView
        projectId={projectId}
        deviceIds={deviceIds}
        focusEntityId={focusEntityId}
        paused={paused}
        onStreamChange={onStreamChange}
        onConfirmBoard={onConfirmBoard}
      />
    </div>
  )
}

export function BenchPanels({
  projectId,
  sessions,
  externalDevices,
  allDeviceIds,
  paused,
  focusEntityId,
  onStreamChange,
  onConfirmBoard
}: {
  projectId: string
  sessions: readonly BenchSession[] | null
  externalDevices: readonly string[]
  allDeviceIds: string[]
  paused: boolean
  focusEntityId?: string
  /** True when any visible panel has live signals. */
  onStreamChange: (live: boolean) => void
  onConfirmBoard?: () => void
}): React.JSX.Element {
  const { robots, otherDeviceIds } = groupRobotSessions(sessions, externalDevices)
  const { teleop, refresh } = useTeleopState(projectId, robots.length > 0)
  const [reports, setReports] = useState<Record<string, boolean>>({})
  const onStream = useCallback(
    (key: string, live: boolean) => setReports((previous) => ({ ...previous, [key]: live })),
    []
  )
  const showOthers = robots.length === 0 || otherDeviceIds.length > 0
  const keys = [...robots.map((robot) => robot.sessionId), ...(showOthers ? [OTHERS_KEY] : [])]
  const anyLive = keys.some((key) => reports[key] === true)
  useEffect(() => onStreamChange(anyLive), [onStreamChange, anyLive, reports])
  return (
    <>
      <TeleopBar projectId={projectId} robots={robots} teleop={teleop} onChanged={refresh} />
      <RobotPanels
        projectId={projectId}
        robots={robots}
        teleop={teleop}
        paused={paused}
        focusEntityId={focusEntityId}
        onStream={onStream}
        onConfirmBoard={onConfirmBoard}
      />
      {!showOthers && (
        <DeviceBenchView
          projectId={projectId}
          deviceIds={robots.flatMap((robot) => robot.deviceIds)}
          focusEntityId={focusEntityId}
          paused={paused}
          robotCount={robots.length}
          reasoningOnly
        />
      )}
      {showOthers && (
        <LegacyPanes
          projectId={projectId}
          deviceIds={robots.length > 0 ? otherDeviceIds : allDeviceIds}
          panelledRobotIds={robots.map((robot) => robot.robotId)}
          paused={paused}
          focusEntityId={focusEntityId}
          onStream={onStream}
          onConfirmBoard={onConfirmBoard}
        />
      )}
    </>
  )
}
