// The widget contract — the seam between the shared-focus engine and the widget canvas.
//
// WHY THIS FILE EXISTS SEPARATELY. WS-01 (the focus engine) listed WS-03 (the canvas) as a
// dependency and WS-03 listed WS-01, so neither could start. The cycle was never real: what each
// actually needed was the *contract* between them. Extracting it here lets both build against
// this file and neither against the other.
//
// A widget is "a lens on the shared focus": it RECEIVES the focused entity and its neighbourhood,
// and EMITS requests to re-focus or to ask SOL for something. That is the whole surface. A new
// lens — schematic, CAD, telemetry, Impact — drops in by implementing `WidgetProps`, with no
// bespoke wiring in the canvas and no new store.
//
// Versioned because widgets will outlive this shape. Adding an optional field is compatible;
// removing or retyping one is a breaking change and bumps the version.

import type { ComponentType } from 'react'
import type { Entity, Neighborhood } from '../../lib/api/resources'

/** Bumped when this contract changes shape. See the note above on what counts as breaking. */
export const WIDGET_CONTRACT_VERSION = 1

/** Where the shared focus currently is in its lifecycle. */
export type FocusStatus = 'idle' | 'loading' | 'ready' | 'error'

/**
 * What every widget RECEIVES.
 *
 * `focusedEntity` is the entity the user selected; `neighborhood` is the bounded subgraph around
 * it, already fetched once and shared by every widget — a widget must never fetch it itself, or
 * mounting N lenses would cost N requests per selection.
 *
 * `neighborhood.truncated` means the server capped the result. Surface it; a silently capped
 * neighbourhood reads as the whole picture.
 */
export interface WidgetFocus {
  readonly status: FocusStatus
  readonly focusedEntity: Entity | null
  readonly neighborhood: Neighborhood | null
  /** Set when `status` is `'error'`; safe to render, it is Solus-authored text. */
  readonly error: string | null
}

/**
 * The CLOSED set of actions a widget may ask for.
 *
 * A closed union rather than a free string, and enforced at runtime by the host — CLAUDE.md §7
 * fixes the available action set in Solus code *before* any model-influenced input reaches it,
 * and a widget's request is model-influenced the moment WS-04 lets SOL arrange the workspace.
 * Adding a member is a contract change, which is exactly the friction that rule wants.
 */
export const SOL_ACTION_KINDS = ['explain', 'diagnose', 'arrange_workspace'] as const

export type SolActionKind = (typeof SOL_ACTION_KINDS)[number]

/** A widget's request for SOL to act. Solus code decides what is actually allowed to run. */
export interface SolActionRequest {
  /** What the widget is asking for. Validated against `SOL_ACTION_KINDS` by the host. */
  readonly kind: SolActionKind
  /** The entity the request is about; defaults to the current focus when omitted. */
  readonly entityId?: string
  /** Free-text detail. UNTRUSTED for prompt purposes — it reaches the model as data, never as
   *  instructions (CLAUDE.md §7). */
  readonly detail?: string
}

/**
 * What every widget EMITS. Deliberately two verbs: a widget can move the shared focus, and it can
 * ask SOL for something. It cannot mutate the graph, fetch its own scope, or reach another widget
 * — those would each be a way for one lens to desynchronise the rest.
 */
export interface WidgetActions {
  /** Move the shared focus. Every other mounted widget re-scopes; the canvas does not remount. */
  refocus(entityId: string): void
  /** Ask SOL to act. The host validates and routes it; the widget never invokes a tool directly. */
  requestSolAction(request: SolActionRequest): void
}

/** The props every widget receives. Implementing this is the entire cost of being a widget. */
export interface WidgetProps {
  readonly focus: WidgetFocus
  readonly actions: WidgetActions
}

/** How a widget registers itself with the canvas (WS-03) and with saved layouts (WS-04). */
export interface WidgetDescriptor {
  /** Stable id — persisted in saved layouts, so renaming one orphans a user's layout. */
  readonly id: string
  /** Human-readable title for the widget's frame. */
  readonly title: string
  readonly Component: ComponentType<WidgetProps>
}
