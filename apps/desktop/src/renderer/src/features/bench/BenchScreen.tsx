// Live Bench discovers sessions independently of focus and narrows device panels
// through confirmed topology. Empty projects open Workspace Add Hardware.
import { lazy, Suspense, useCallback, useState } from 'react'
import type { Focus } from '@solus/shared-types'
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { useFocusStore } from '../workspace/focusStore'
import { useSharedFocus } from '../workspace/useSharedFocus'
import type { MainScreen } from '../workspace/shellStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { Button } from '../../components/ui/Button'
import { ConnectDeviceModal } from './ConnectDeviceModal'
import { useWorkspaceSessionGeneration } from '../graph/workspaceSession'
import { BenchCanvasHost } from './BenchCanvasHost'
import { DeviceBenchView } from './DeviceBenchView'
import { activeDeviceIds, useActiveBenchSessions } from './useActiveBenchSessions'
import { useExternalBenchDevices } from './useExternalBenchDevices'
import './bench.css'
import { BenchRealtimeContext, useBenchRealtime } from './BenchRealtime'

const ScenePanel = lazy(() =>
  import('./scene/ScenePanel').then((module) => ({ default: module.ScenePanel }))
)

const RunsView = lazy(() =>
  import('./runs/RunsView').then((module) => ({ default: module.RunsView }))
)

export interface BenchScreenProps {
  /** Shell navigation for Workspace and the Store. */
  onNavigate?: (screen: MainScreen) => void
  onAddHardware?: () => void
}

function NoProject(): React.JSX.Element {
  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <ScreenEmptyState
        icon={<Icons.bench size={30} />}
        title="Live Bench watches connected hardware"
        body="Open a project to see connected hardware telemetry. Select a part in Workspace to narrow its signals."
        status="NO PROJECT OPEN"
      />
    </div>
  )
}

export function BenchScreen({
  onNavigate,
  onAddHardware
}: BenchScreenProps = {}): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  const focus = useSharedFocus()
  const generation = useWorkspaceSessionGeneration()
  const [pausedAt, setPausedAt] = useState<number | null>(null)
  const [stream, setStream] = useState<{ generation: number; live: boolean } | null>(null)
  const paused = pausedAt === generation
  const onStreamChange = useCallback(
    (live: boolean) => setStream({ generation, live }),
    [generation]
  )
  const [connectionGeneration, setConnectionGeneration] = useState<number | null>(null)
  // Keep discovery active while focus narrows the displayed device telemetry.
  const projectId = project?.id ?? null
  const sessions = useActiveBenchSessions(projectId, true)
  const externalDevices = useExternalBenchDevices(projectId, true)
  const focusEntityId = focus?.entity.entityId
  const realtime = useBenchRealtime(projectId, sessions, focusEntityId)
  const onFocusChange = useCallback((next: Focus | null): void => {
    if (next) void useFocusStore.getState().focus(next.entity.entityId)
  }, [])

  if (!project) return <NoProject />

  const deviceIds = [...new Set([...activeDeviceIds(sessions), ...externalDevices])]
  return (
    <BenchRealtimeContext.Provider value={realtime}>
      <div className="bench-workspace">
        <BenchHeader
          paused={paused}
          live={stream?.generation === generation && stream.live}
          empty={deviceIds.length === 0}
          onAddHardware={onAddHardware}
          onConnections={() => setConnectionGeneration(generation)}
          onPause={() => {
            if (paused) setStream(null)
            setPausedAt(paused ? null : generation)
          }}
        />
        {paused && (
          <p className="bench-device-chips">
            Scene and signal panes paused. Hardware sessions and recording continue.
          </p>
        )}
        {connectionGeneration === generation && (
          <ConnectDeviceModal
            projectId={project.id}
            onClose={() => setConnectionGeneration(null)}
          />
        )}
        <SessionChips sessions={sessions} />
        <ConnectionStatus sessions={sessions} paused={paused} realtime={realtime} />
        <div className="bench-panes">
          <aside className="bench-left">
            <Suspense fallback={<p role="status">Loading scene…</p>}>
              <ScenePanel projectId={project.id} paused={paused} compact />
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
            projectId={project.id}
            deviceIds={deviceIds}
            focusEntityId={focusEntityId}
            paused={paused}
            onStreamChange={onStreamChange}
            onConfirmBoard={onAddHardware}
          />
        </div>
        <section className="bench-secondary" aria-label="Runs and capture">
          <Suspense fallback={<p role="status">Loading runs…</p>}>
            <RunsView projectId={project.id} sessions={sessions} />
          </Suspense>
        </section>
        <section className="bench-secondary" aria-label="Workspace widgets">
          <BenchCanvasHost
            projectId={project.id}
            focus={focus}
            onFocusChange={onFocusChange}
            sessions={sessions}
            onNavigate={onNavigate}
            onAddHardware={onAddHardware}
            embedded
          />
        </section>
      </div>
    </BenchRealtimeContext.Provider>
  )
}

function BenchHeader({
  paused,
  live,
  empty,
  onAddHardware,
  onConnections,
  onPause
}: {
  paused: boolean
  live: boolean
  empty: boolean
  onAddHardware?: () => void
  onConnections: () => void
  onPause: () => void
}): React.JSX.Element {
  return (
    <header className="bench-topbar">
      <h1>Live Bench</h1>
      <Button size="sm" kind="ghost" onClick={onPause}>
        {paused ? '▶ Resume' : '⏸ Pause'}
      </Button>
      <span className={`bench-status ${!paused && live ? 'bench-status-live' : ''}`} role="status">
        {paused ? 'PAUSED' : live ? '● STREAMING' : 'NO STREAM'}
      </span>
      <Button size="sm" kind="ghost" onClick={onConnections}>
        Manage connections
      </Button>
      {empty && (
        <Button size="sm" kind="primary" onClick={onAddHardware}>
          Add hardware
        </Button>
      )}
    </header>
  )
}

function SessionChips({
  sessions
}: {
  sessions: ReturnType<typeof useActiveBenchSessions>
}): React.JSX.Element {
  return (
    <div className="bench-device-chips">
      {sessions?.map((session) => (
        <span key={session.id} role="status">
          {session.label} ·{' '}
          {session.status === 'starting'
            ? 'starting'
            : session.status === 'ended'
              ? 'disconnected (session ended)'
              : session.link}
        </span>
      ))}
    </div>
  )
}

function ConnectionStatus({
  sessions,
  paused,
  realtime
}: {
  sessions: ReturnType<typeof useActiveBenchSessions>
  paused: boolean
  realtime: ReturnType<typeof useBenchRealtime>
}): React.JSX.Element {
  return (
    <>
      {' '}
      {!!sessions?.some((session) => session.status !== 'ended') && !paused && !realtime.ready && (
        <p role="status" className="bench-device-chips">
          {realtime.blocked
            ? 'Live data access is unavailable.'
            : 'Reconnecting — periodic updates'}
        </p>
      )}
    </>
  )
}
