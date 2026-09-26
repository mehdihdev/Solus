import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import {
  getIsaacConnectionStatus,
  type IsaacConnectionStatus
} from '../../lib/api/resources.isaacConnection'
import { useSettingsStore } from '../../store/settingsStore'
import {
  useWorkspaceSessionGeneration,
  workspaceSessionGeneration
} from '../graph/workspaceSession'

export function IsaacConnectionPanel({
  projectId
}: {
  projectId: string | null
}): React.JSX.Element {
  const generation = useWorkspaceSessionGeneration()
  return (
    <ApplicationMonitor key={`${projectId ?? 'no-project'}:${generation}`} projectId={projectId} />
  )
}

function useApplicationMonitor(projectId: string | null): {
  monitoring: boolean
  snapshot: IsaacConnectionStatus | null
  failed: boolean
  toggle: () => void
} {
  const [monitoring, setMonitoring] = useState(false)
  const [snapshot, setSnapshot] = useState<IsaacConnectionStatus | null>(null)
  const [failed, setFailed] = useState(false)
  const generation = useWorkspaceSessionGeneration()
  useEffect(() => {
    if (!monitoring || !projectId) return
    const controller = new AbortController()
    const current = (): boolean =>
      !controller.signal.aborted && workspaceSessionGeneration() === generation
    let timer: ReturnType<typeof setTimeout> | undefined
    const refresh = async (): Promise<void> => {
      if (!current()) return
      try {
        const value = await getIsaacConnectionStatus(projectId, controller.signal)
        if (current()) {
          setSnapshot(value)
          setFailed(false)
        }
      } catch {
        if (current()) {
          setSnapshot(null)
          setFailed(true)
        }
      } finally {
        if (current())
          timer = setTimeout(() => {
            void refresh()
          }, 10000)
      }
    }
    void refresh()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [monitoring, projectId, generation])
  return {
    monitoring,
    snapshot,
    failed,
    toggle: () => {
      setSnapshot(null)
      setFailed(false)
      setMonitoring(!monitoring)
    }
  }
}

function monitoringLabel(
  monitoring: boolean,
  failed: boolean,
  snapshot: IsaacConnectionStatus | null
): string {
  if (!monitoring) return 'Disconnected'
  if (failed) return 'Status unavailable'
  if (!snapshot) return 'Checking application status…'
  if (
    snapshot.bridge === 'unavailable' ||
    snapshot.reason === 'capability_unavailable' ||
    snapshot.reason === 'observation_failed'
  )
    return 'Status unavailable'
  return 'Monitoring application status'
}

function ApplicationMonitor({ projectId }: { projectId: string | null }): React.JSX.Element {
  const { monitoring, snapshot, failed, toggle } = useApplicationMonitor(projectId)
  const connectionLabel = monitoringLabel(monitoring, failed, snapshot)
  return (
    <section
      aria-label="Isaac application connection"
      style={{ padding: 16, borderBottom: '1px solid var(--bd)' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 180 }}>
          <Mono size={11} color="var(--tx)">
            Isaac Sim
          </Mono>
          <div role="status" style={{ fontSize: 11, color: 'var(--mut)', marginTop: 5 }}>
            {connectionLabel}
          </div>
        </div>
        {projectId && (
          <Button
            size="sm"
            aria-label={monitoring ? 'Disconnect status monitoring' : 'Connect status monitoring'}
            onClick={toggle}
          >
            {monitoring ? 'Disconnect' : 'Connect'}
          </Button>
        )}
      </div>
      {!projectId ? (
        <p style={{ fontSize: 12, color: 'var(--mut)' }}>
          Open a project to monitor the application.
        </p>
      ) : (
        <ApplicationFacts snapshot={snapshot} />
      )}
    </section>
  )
}

function ApplicationFacts({
  snapshot
}: {
  snapshot: IsaacConnectionStatus | null
}): React.JSX.Element {
  const mode = useSettingsStore((state) => state.solMode)
  return (
    <>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 16, fontSize: 12 }}>
        <span>{snapshot?.installation === 'installed' ? 'Installed' : 'Installation unknown'}</span>
        <span>
          {snapshot?.owned_session === 'running'
            ? 'Owned session running'
            : snapshot?.owned_session === 'not_running'
              ? 'Owned session not running'
              : 'Owned session unknown'}
        </span>
      </div>
      <p style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.6, marginBottom: 0 }}>
        {mode === 'Guide'
          ? 'Connect checks the application bridge and monitors its owned session. Independently launched sessions are not observed.'
          : 'Read-only bridge monitoring · owned session only.'}
      </p>
      <p style={{ fontSize: 11, color: 'var(--mut)', marginBottom: 0 }}>
        Streaming: none — this connection provides no telemetry.
      </p>
    </>
  )
}
