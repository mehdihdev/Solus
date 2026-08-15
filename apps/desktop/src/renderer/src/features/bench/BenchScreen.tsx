// Live Bench: the LB-05 LiveBenchWidget, scoped to the shared focus via the
// useSharedFocus adapter (SOLUSDEV-70 wiring). Telemetry is ingested by
// external producers today — a connect flow (starting a robot/sim stream from
// the UI) is a separate unbuilt ticket — so this surface stays honest about
// what is and is not streaming: the widget derives its stream state from data
// timestamps and never labels anything REAL that it cannot vouch for.
import { useCallback } from 'react'
import type { Focus } from '@solus/shared-types'
import { Icons } from '../../components/ui/icons.constants'
import { ScreenEmptyState } from '../workspace/ScreenEmptyState'
import { useFocusStore } from '../workspace/focusStore'
import { useSharedFocus } from '../workspace/useSharedFocus'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { LiveBenchWidget } from '../../widgets/livebench/LiveBenchWidget'

export function BenchScreen(): React.JSX.Element {
  const hasProject = useWorkspaceStore((s) => s.project !== null)
  const focus = useSharedFocus()
  const onFocusChange = useCallback((next: Focus | null): void => {
    if (next) void useFocusStore.getState().focus(next.entity.entityId)
  }, [])

  if (!hasProject) {
    return (
      <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
        <ScreenEmptyState
          icon={<Icons.bench size={30} />}
          title="Live Bench watches the focused part"
          body="Open a project and select an entity in the Context Model — its live telemetry, signals, and observer events stream here."
          status="NO PROJECT OPEN"
        />
      </div>
    )
  }

  if (focus === null) {
    return (
      <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0 }}>
        <ScreenEmptyState
          icon={<Icons.bench size={30} />}
          title="Nothing is focused"
          body="Select an entity in the Context Model and its bench telemetry appears here."
          status="NO PART FOCUSED"
        />
      </div>
    )
  }

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', padding: 20 }}>
      <LiveBenchWidget focus={focus} onFocusChange={onFocusChange} />
    </div>
  )
}
