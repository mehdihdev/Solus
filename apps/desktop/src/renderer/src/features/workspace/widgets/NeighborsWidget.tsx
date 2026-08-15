// A reference widget: the focused entity's neighbours, each one selectable (WS-01).
//
// Deliberately plain — its job is to prove the contract, not to be the finished lens. A real
// schematic/CAD/telemetry widget is exactly this shape: read `focus`, render, call
// `actions.refocus` on selection. No store import, no fetching, no knowledge of other widgets.
import type { WidgetProps } from '../widget.contract'

export function NeighborsWidget({ focus, actions }: WidgetProps): React.JSX.Element {
  const { neighborhood, focusedEntity, status } = focus

  if (status === 'error') {
    return (
      <div data-testid="focus-error" className="text-sm text-mut">
        Could not load the neighbourhood. {focus.error}
      </div>
    )
  }

  return (
    <section aria-label="Neighbours">
      <p data-testid="neighbour-count" className="text-xs text-mut">
        {neighborhood?.entities.length ?? 0}
      </p>

      {neighborhood?.truncated ? (
        <p data-testid="truncated-notice" className="text-xs text-mut">
          Showing part of this neighbourhood — narrow the filters to see the rest.
        </p>
      ) : null}

      <ul>
        {(neighborhood?.entities ?? []).map((entity) => (
          <li key={entity.id}>
            <button
              type="button"
              // Selecting here re-scopes EVERY mounted widget, not just this one.
              onClick={() => actions.refocus(entity.id)}
              aria-current={entity.id === focusedEntity?.id}
            >
              {entity.name}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
