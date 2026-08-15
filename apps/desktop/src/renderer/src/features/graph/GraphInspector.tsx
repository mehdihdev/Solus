// Right-hand inspector rail of the Context Model screen. Idle, it explains
// itself; once the entity list lands a selection in the shared focus store, it
// mounts the WS-01 widgets under WidgetHost — the focused part's summary plus
// its selectable neighbours (whose refocus round-trips through the host, so
// clicking a neighbour re-scopes every mounted widget, Live Bench included).
//
// Status-branched at the RAIL, not inside the widgets: during the fetch the
// focused entity is not yet in the cache and FocusSummaryWidget would say
// "Nothing focused" — a lie while a load is in flight — and on error both
// widgets would print the identical error line twice.
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { useFocusStore } from '../workspace/focusStore'
import { FocusSummaryWidget } from '../workspace/widgets/FocusSummaryWidget'
import { NeighborsWidget } from '../workspace/widgets/NeighborsWidget'
import { WidgetHost } from '../workspace/widgets/WidgetHost'

function Centered({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        padding: 32,
        textAlign: 'center'
      }}
    >
      {children}
    </div>
  )
}

export function GraphInspector(): React.JSX.Element {
  const status = useFocusStore((s) => s.status)
  const error = useFocusStore((s) => s.error)

  return (
    <div
      style={{
        width: 318,
        borderLeft: '1px solid var(--bd)',
        background: 'var(--sur)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
        overflowY: 'auto'
      }}
    >
      {status === 'ready' ? (
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* ponytail: no onSolAction — SOL routing lands with WS-04; until then the host's documented no-op applies */}
          <WidgetHost widget={FocusSummaryWidget} />
          <WidgetHost widget={NeighborsWidget} />
        </div>
      ) : status === 'loading' ? (
        <Centered>
          <Spinner />
          <Mono size={10} style={{ color: 'var(--mut)' }}>
            LOADING NEIGHBOURHOOD…
          </Mono>
        </Centered>
      ) : status === 'error' ? (
        <Centered>
          <div style={{ fontSize: 13, color: 'var(--mut)', lineHeight: 1.6 }}>
            Could not load the neighbourhood. {error}
          </div>
        </Centered>
      ) : (
        <Centered>
          <span style={{ color: 'var(--mut)', opacity: 0.6 }}>
            <Icons.search size={26} />
          </span>
          <div style={{ fontSize: 13, color: 'var(--mut)', lineHeight: 1.6 }}>
            Select an entity to inspect it — its properties, sources, and links across domains
            appear here.
          </div>
        </Centered>
      )}
    </div>
  )
}
