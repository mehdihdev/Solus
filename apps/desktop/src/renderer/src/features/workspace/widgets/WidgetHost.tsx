// The glue between the shared focus and any widget (SOLUSDEV-191 / WS-01).
//
// This is the ONLY place a widget is connected to the store. A widget receives `WidgetProps` and
// nothing else — it never imports the focus store, never fetches its own scope, and never reaches
// another widget. That is what lets a new lens drop in by implementing the contract alone, and
// what stops one lens desynchronising the rest.
//
// WS-03's canvas mounts these inside its layout frames; nothing here knows about layout.
import { useCallback, type ComponentType } from 'react'
import { useFocusStore, widgetFocus } from '../focusStore'
import { SOL_ACTION_KINDS } from '../widget.contract'
import type { SolActionRequest, WidgetActions, WidgetProps } from '../widget.contract'

interface WidgetHostProps {
  widget: ComponentType<WidgetProps>
  /**
   * Where a widget's SOL requests go. The widget proposes; the HOST decides — a widget must never
   * invoke a tool directly (CLAUDE.md §7: the model requests, Solus code decides, and the same
   * discipline applies to the UI). Real routing lands with WS-04's `arrange_workspace` tool; until
   * then an unhandled request is deliberately a no-op rather than a fake success.
   */
  onSolAction?: (request: SolActionRequest) => void
}

export function WidgetHost({ widget: Widget, onSolAction }: WidgetHostProps): React.JSX.Element {
  // Subscribes to the whole store, so any change (including a cache write) re-renders the widget.
  // Deliberately NOT memoised: zustand hands back a fresh object on every `set`, so a `useMemo`
  // keyed on it can never skip a recompute — it would be decoration, not an optimisation.
  // `widgetFocus` is a handful of property reads; if the widget count ever makes that matter, the
  // real fix is a selector (`useFocusStore(useShallow(widgetFocus))`), not a memo.
  const focus = widgetFocus(useFocusStore())

  const refocus = useCallback((entityId: string) => {
    void useFocusStore.getState().focus(entityId)
  }, [])

  const requestSolAction = useCallback(
    (request: SolActionRequest) => {
      // The host DECIDES — it does not merely forward. The contract's types are erased at
      // runtime, and once WS-04 lets SOL drive the workspace a widget's request is
      // model-influenced input; CLAUDE.md §7 requires the action set be fixed by Solus code
      // before that input is honoured. Dropping is deliberate: an unknown action is a bug or an
      // attack, and neither should reach the agent.
      if (!SOL_ACTION_KINDS.includes(request.kind)) return
      onSolAction?.(request)
    },
    [onSolAction]
  )

  const actions: WidgetActions = { refocus, requestSolAction }

  return <Widget focus={focus} actions={actions} />
}
