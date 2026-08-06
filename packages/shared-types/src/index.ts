// Contracts shared between the desktop/web frontends and the backend.
//
// LANE 0 owns this package (CODEOWNERS, docs/WORKTREES.md). Every type here is
// imported by at least two lanes that must not import each other's code — that
// is the entire selection criterion. Feature-local types belong in the feature.
//
// Each contract lives in its own file with its own doc in docs/contracts/. This
// barrel re-exports them; it is the ONLY file a new contract touches, and it is
// append-only, so adding one is not a merge conflict.

/** The legacy API error envelope. Superseded in practice by `lib/api/envelope.types.ts`. */
export interface ApiError {
  code: string;
  message: string;
}

// SOLUSDEV-217 (CTR-02) — what the user is looking at. docs/contracts/focus.md
export {
  DOMAINS,
  MAX_FOCUS_PATH,
  createFocusStore,
  descend,
  isSameEntity,
  parseFocus,
  type Domain,
  type EntityRef,
  type Focus,
  type FocusListener,
  type FocusStep,
  type FocusStore,
} from "./focus";

// SOLUSDEV-216 (CTR-01) — the widget framework. docs/contracts/widget.md
export {
  collectManifests,
  type Widget,
  type WidgetLifecycle,
  type WidgetManifest,
  type WidgetModules,
  type WidgetProps,
  type WidgetRenderState,
  type WidgetSizeHint,
  type WidgetSlotSize,
} from "./widget";

// SOLUSDEV-218 (CTR-03) — the destructive-action gate. docs/contracts/action-gate.md
export {
  CONFIRMATION_DECISIONS,
  CONFIRMATION_STATUSES,
  CONFIRMATION_TTL_MINUTES,
  confirmationDecisionPath,
  isConfirmationRefused,
  type ConfirmationDecision,
  type ConfirmationDecisionRequest,
  type ConfirmationOutcomeEnvelope,
  type ConfirmationStatus,
  type DiffRow,
  type ToolConfirmationEvent,
  type ToolErrorCode,
  type ToolErrorPayload,
  type ToolResultPayload,
} from "./action-gate";

// SOLUSDEV-219 (CTR-04) — the impact result. docs/contracts/impact.md
export {
  SEVERITIES,
  focusOfImpactNode,
  severityRank,
  toEntityRef,
  worstSeverity,
  type Consequence,
  type ConsequenceEvidence,
  type ImpactEntity,
  type ImpactFocus,
  type ImpactNode,
  type ImpactPathStep,
  type ImpactResult,
  type Severity,
  type SolAction,
} from "./impact";

// SOLUSDEV-220 (CTR-05) — the tool-knowledge boundary. docs/contracts/tool-knowledge.md
// ⚠ The type that cannot hold customer content. Read the doc before extending it.
export {
  CONTROL_EFFECTS,
  PROVENANCES,
  TOOL_FAMILIES,
  UI_SURFACES,
  controlId,
  parseLocator,
  parseToolKnowledge,
  vendorText,
  type ControlEffect,
  type ControlId,
  type Invocation,
  type Provenance,
  type ScreenLocator,
  type ToolFamily,
  type ToolKnowledge,
  type UiSurface,
  type VendorText,
} from "./tool-knowledge";

// SOLUSDEV-221 (CTR-06) — the orb ↔ overlay handoff. docs/contracts/orb-overlay.md
export {
  ORB_OVERLAY_CHANNELS,
  createLoopbackPorts,
  createStubOrb,
  createStubOverlay,
  parseOrbToOverlay,
  parseOverlayToOrb,
  type ControlPointer,
  type GuideStep,
  type HandoffEndReason,
  type OrbOverlayPort,
  type OrbPort,
  type OrbToOverlay,
  type OverlayPort,
  type OverlayToOrb,
  type ToolWindowRef,
  type WindowBounds,
} from "./orb-overlay";

/** Fixture typing support — see src/json.ts. */
export type { JsonShapeOf } from "./json";
