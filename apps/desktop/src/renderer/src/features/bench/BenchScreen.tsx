// Live Bench: the SOLUSDEV-235 widget canvas (EXT-16), whose default
// `builtin:livebench` slot is the LB-05 LiveBenchWidget scoped to the shared
// focus via the useSharedFocus adapter (SOLUSDEV-70 wiring). Without a focused
// entity the screen still does not dead-end (SOLUSDEV-72): active sessions
// with streaming devices render the device-keyed telemetry view, and the
// header's "Connect a device" opens the serial-device dialog in place.
// Honesty rules (SOLUSDEV-152) still bind: nothing here labels data REAL that
// it cannot vouch for, and "nothing streaming" is only claimed once the API
// said so.
import { useCallback } from 'react'
import type { Focus } from '@solus/shared-types'
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { useFocusStore } from '../workspace/focusStore'
import { useSharedFocus } from '../workspace/useSharedFocus'
import type { MainScreen } from '../workspace/shellStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { BenchCanvasHost } from './BenchCanvasHost'
import { DeviceBenchView } from './DeviceBenchView'
import { activeDeviceIds, useActiveBenchSessions } from './useActiveBenchSessions'

export interface BenchScreenProps {
  /** Shell navigation for the "Connect a device" and "Browse the Store" affordances. */
  onNavigate?: (screen: MainScreen) => void
}

function NoProject(): React.JSX.Element {
  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
      <ScreenEmptyState
        icon={<Icons.bench size={30} />}
        title="Live Bench watches the focused part"
        body="Open a project and select an entity in the Workspace — its live telemetry, signals, and observer events stream here."
        status="NO PROJECT OPEN"
      />
    </div>
  )
}

/**
 * The screen's one rule: with no focus AND at least one streaming device, the
 * device-keyed view takes the screen exactly as before; every other project
 * state is the canvas (whose Live Bench slot carries the focused view).
 */
export function BenchScreen({ onNavigate }: BenchScreenProps = {}): React.JSX.Element {
  const project = useWorkspaceStore((s) => s.project)
  const focus = useSharedFocus()
  // Session polling only runs on the unfocused branch — the focused view is
  // entity-scoped and unchanged.
  const sessions = useActiveBenchSessions(project?.id ?? null, project !== null && focus === null)
  const onFocusChange = useCallback((next: Focus | null): void => {
    if (next) void useFocusStore.getState().focus(next.entity.entityId)
  }, [])

  if (!project) return <NoProject />

  const deviceIds = focus === null ? activeDeviceIds(sessions) : []
  if (deviceIds.length > 0) {
    return <DeviceBenchView projectId={project.id} deviceIds={deviceIds} />
  }

  return (
    <BenchCanvasHost
      projectId={project.id}
      focus={focus}
      onFocusChange={onFocusChange}
      sessions={sessions}
      onNavigate={onNavigate}
    />
  )
}
