// Live Bench: the LB-05 LiveBenchWidget, scoped to the shared focus via the
// useSharedFocus adapter (SOLUSDEV-70 wiring). Without a focused entity the
// screen no longer dead-ends (SOLUSDEV-72): active sessions with streaming
// devices render a device-keyed telemetry view, and the empty state offers a
// real path to connect a device from the Sources screen. Honesty rules
// (SOLUSDEV-152) still bind: nothing here labels data REAL that it cannot
// vouch for, and "nothing streaming" is only claimed once the API said so.
import { useCallback } from 'react'
import type { Focus } from '@solus/shared-types'
import { Button } from '../../components/ui/Button'
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { useFocusStore } from '../workspace/focusStore'
import { useSharedFocus } from '../workspace/useSharedFocus'
import type { MainScreen } from '../workspace/shellStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { LiveBenchWidget } from '../../widgets/livebench/LiveBenchWidget'
import { DeviceBenchView } from './DeviceBenchView'
import { activeDeviceIds, useActiveBenchSessions } from './useActiveBenchSessions'

export interface BenchScreenProps {
  /** Shell navigation for the "Connect a device" affordance. */
  onNavigate?: (screen: MainScreen) => void
}

function Empty({
  children,
  ...props
}: React.ComponentProps<typeof ScreenEmptyState>): React.JSX.Element {
  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <ScreenEmptyState {...props}>{children}</ScreenEmptyState>
    </div>
  )
}

export function BenchScreen({ onNavigate }: BenchScreenProps = {}): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  const focus = useSharedFocus()
  // Session polling only runs on the unfocused branch — the focused view is
  // entity-scoped and unchanged.
  const sessions = useActiveBenchSessions(project?.id ?? null, project !== null && focus === null)
  const onFocusChange = useCallback((next: Focus | null): void => {
    if (next) void useFocusStore.getState().focus(next.entity.entityId)
  }, [])

  if (!project) {
    return (
      <Empty
        icon={<Icons.bench size={30} />}
        title="Live Bench watches the focused part"
        body="Open a project and select an entity in the Context Model — its live telemetry, signals, and observer events stream here."
        status="NO PROJECT OPEN"
      />
    )
  }

  if (focus === null) {
    const deviceIds = activeDeviceIds(sessions)
    if (deviceIds.length > 0) {
      return <DeviceBenchView projectId={project.id} deviceIds={deviceIds} />
    }
    return (
      <Empty
        icon={<Icons.bench size={30} />}
        title="Nothing is focused"
        body="Select an entity in the Context Model and its bench telemetry appears here — or start a local stream to watch devices directly."
        // Only claim "nothing streaming" once the session list actually said so.
        status={sessions === null ? 'NO PART FOCUSED' : 'NOTHING STREAMING'}
      >
        <Button kind="primary" size="sm" onClick={() => onNavigate?.('sources')}>
          Connect a device
        </Button>
      </Empty>
    )
  }

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', padding: 20 }}>
      <LiveBenchWidget focus={focus} onFocusChange={onFocusChange} />
    </div>
  )
}
