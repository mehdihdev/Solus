// SOLUSDEV-235 / EXT-16 — Live Bench hosts the widget canvas.
//
// The canvas (features/canvas) owns the grid, the slots, the picker and the
// layout persistence; this file owns how Live Bench wraps it: the screen's
// title and focus/device line go in as the canvas `header` (the canvas renders
// its own `+ Add widget` beside it — ONE button, never two), Store navigation
// and the project's connected source kinds go in as props so the picker's
// requirement hints are judged against real sources, never assumed met
// (docs/wireflows/widget-canvas.md "Header", "Picker"). Developer registrations
// with a widget view (EXT-20) go in as the picker's Developer section.
import { useMemo } from 'react'
import type { Focus, SourceKind } from '@solus/shared-types'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import type { BenchSession } from '../../lib/api/resources'
import { WidgetCanvas, type DevWidgetEntry } from '../canvas'
import { extRef } from '../canvas/layout'
import { selectDevRegistration, useDevExtensionsStore } from '../devExtensions/devExtensionsStore'
import { connectedKinds } from '../extensions/extensionLogic'
import { useProjectSources } from '../project/useProjectSources'
import type { MainScreen } from '../workspace/shellStore'

export interface BenchCanvasHostProps {
  readonly projectId: string
  readonly focus: Focus | null
  readonly onFocusChange: (focus: Focus | null) => void
  /** Active sessions as last reported; null = unknown, which is never "none". */
  readonly sessions: readonly BenchSession[] | null
  /** Shell navigation for the picker's "Browse the Store". */
  readonly onNavigate?: (screen: MainScreen) => void
  readonly onAddHardware?: () => void
  readonly embedded?: boolean
}

/** What the header's status line may honestly say (SOLUSDEV-152 rules). */
type BenchHeaderStatus = 'focused' | 'unknown' | 'nothing-streaming' | 'awaiting-data'

const STATUS_LABEL: Readonly<Record<BenchHeaderStatus, string>> = {
  focused: 'FOCUSED',
  unknown: 'NO PART FOCUSED',
  'nothing-streaming': 'NOTHING STREAMING',
  'awaiting-data': 'AWAITING DEVICE DATA'
}

/**
 * "Nothing streaming" is only claimed once the session list actually said so;
 * while it is unknown the line says only that no part is focused. (A
 * streaming, unfocused bench never reaches the host — BenchScreen gives that
 * state to DeviceBenchView.)
 */
function benchHeaderStatus(
  focus: Focus | null,
  sessions: readonly BenchSession[] | null
): BenchHeaderStatus {
  if (focus !== null) return 'focused'
  return sessions === null ? 'unknown' : sessions.length > 0 ? 'awaiting-data' : 'nothing-streaming'
}

const TITLE_STYLE: React.CSSProperties = {
  margin: 0,
  fontSize: 14.5,
  fontWeight: 600,
  letterSpacing: '-0.01em',
  color: 'var(--tx)'
}

function BenchHeader({
  focus,
  sessions,
  onAddHardware,
  embedded
}: Pick<
  BenchCanvasHostProps,
  'projectId' | 'focus' | 'sessions' | 'onAddHardware' | 'embedded'
>): React.JSX.Element {
  const status = benchHeaderStatus(focus, sessions)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h2 style={TITLE_STYLE}>{embedded ? 'Workspace widgets' : 'Live Bench'}</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2, minWidth: 0 }}>
          <Mono size={9.5}>{STATUS_LABEL[status]}</Mono>
          {focus !== null && (
            <span
              style={{
                fontSize: 12,
                color: 'var(--tx)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap'
              }}
            >
              {focus.label ?? focus.entity.entityId}
            </span>
          )}
        </div>
      </div>
      {status === 'nothing-streaming' && !embedded && (
        <Button kind="primary" size="sm" onClick={onAddHardware}>
          Add hardware
        </Button>
      )}
    </div>
  )
}

/** The project's connected source kinds, or null while the list is unknown (= every requirement unmet). */
function useConnectedKinds(): ReadonlySet<SourceKind> | null {
  const { status, sources } = useProjectSources()
  return useMemo(
    () => (status === 'ready' ? connectedKinds(sources.map((s) => s.type)) : null),
    [status, sources]
  )
}

type DevStoreState = Parameters<typeof selectDevRegistration>[0]

/** Live developer registrations with a widget view, as picker rows (`ext:<slug>`
 *  refs — the frame resolver serves them from the dev path). */
function devWidgetEntriesFrom(state: DevStoreState): readonly DevWidgetEntry[] {
  return Object.keys(state.entries).flatMap((slug) => {
    const manifest = selectDevRegistration(state, slug)?.manifest
    const widget = manifest?.views.widget
    if (manifest === undefined || widget === undefined) return []
    return [
      {
        ref: extRef(slug),
        name: manifest.extension.name,
        path: state.entries[slug]?.devPath ?? '',
        size: { preferred: widget.preferred, minimum: widget.minimum }
      }
    ]
  })
}

function useDevWidgets(): readonly DevWidgetEntry[] {
  const devState = useDevExtensionsStore()
  return useMemo(() => devWidgetEntriesFrom(devState), [devState])
}

export function BenchCanvasHost(props: BenchCanvasHostProps): React.JSX.Element {
  const { projectId, focus, onFocusChange, sessions, onNavigate, onAddHardware } = props
  const kinds = useConnectedKinds()
  const dev = useDevWidgets()
  return (
    <WidgetCanvas
      projectId={projectId}
      focus={focus}
      onFocusChange={onFocusChange}
      header={
        <BenchHeader
          projectId={projectId}
          embedded={props.embedded}
          focus={focus}
          sessions={sessions}
          onAddHardware={onAddHardware ?? (onNavigate ? () => onNavigate('workspace') : undefined)}
        />
      }
      onOpenStore={onNavigate ? () => onNavigate('store') : undefined}
      connectedKinds={kinds}
      dev={dev}
    />
  )
}
