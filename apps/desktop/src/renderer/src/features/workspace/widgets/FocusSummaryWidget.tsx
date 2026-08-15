// A second reference widget: what is focused right now (WS-01).
//
// It exists to prove the broadcast. It never learns that the user clicked inside the neighbours
// widget — it just re-renders with new props, which is what "selection re-scopes every widget"
// means in practice.
import type { WidgetProps } from '../widget.contract'

export function FocusSummaryWidget({ focus, actions }: WidgetProps): React.JSX.Element {
  const { focusedEntity, neighborhood, status } = focus

  if (status === 'error') {
    return (
      <div data-testid="focus-error" className="text-sm text-mut">
        Could not load the neighbourhood. {focus.error}
      </div>
    )
  }

  if (!focusedEntity) {
    return (
      <section aria-label="Focus">
        <h2 data-testid="focused-name">Nothing focused</h2>
        <p data-testid="focused-domain" className="text-xs text-mut" />
      </section>
    )
  }

  return (
    <section aria-label="Focus">
      <h2 data-testid="focused-name">{focusedEntity.name}</h2>
      <p data-testid="focused-domain" className="text-xs text-mut">
        {focusedEntity.domain}
      </p>
      <p className="text-xs text-mut">
        {focusedEntity.type} · {neighborhood?.edges.length ?? 0} connections
      </p>

      <button
        type="button"
        // Proposes; it does not act. The host validates and routes (see WidgetHost).
        onClick={() => actions.requestSolAction({ kind: 'explain', entityId: focusedEntity.id })}
      >
        Ask SOL about this
      </button>
    </section>
  )
}
