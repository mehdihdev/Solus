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

// SOLUSDEV-166 (ADR-034) — machine-local ~/.solus state. docs/contracts/local-state.md
export {
  PROJECT_FOLDER_LINK_FIELDS,
  PROJECT_ID_RE,
  PROJECT_REGISTRY_FIELDS,
  PROJECT_REGISTRY_SCHEMA_VERSION,
  PROJECTS_FILENAME,
  SOLUS_HOME_DIRNAME,
  SOLUS_HOME_MODE,
  emptyProjectRegistry,
  isSafeProjectId,
  parseProjectRegistry,
  type ProjectFolderLink,
  type ProjectRegistry,
  type RegistryParseResult,
} from "./local-state";

/** Fixture typing support — see src/json.ts. */
export type { JsonShapeOf } from "./json";

// SOLUSDEV-235 (ADR-035) — the extension.toml manifest. docs/contracts/extension-manifest.md
export {
  BACKEND_FIELDS,
  CAPABILITY_NAME_RE,
  EXTENSION_FIELDS,
  EXTENSION_ID_RE,
  EXTENSION_MANIFEST_FIELDS,
  EXTENSION_MANIFEST_FILENAME,
  EXTENSION_MANIFEST_SCHEMA_VERSION,
  FIRST_PARTY_TABLES,
  GRAPH_DOMAINS,
  GRAPH_FIELDS,
  GRAPH_KIND_FIELDS,
  MANIFEST_LIMITS,
  SUPPORTED_SCHEMA_VERSIONS,
  TOOLS_FIELDS,
  composedToolName,
  declaresFirstParty,
  graphKindName,
  PAGE_VIEW_FIELDS,
  PERMISSIONS_FIELDS,
  PERMISSION_SCOPES,
  SETTING_FIELD_FIELDS,
  SETTING_TYPES,
  SETTINGS_FIELDS,
  SOURCE_KINDS,
  STORE_FIELDS,
  STORE_LINKS_FIELDS,
  STORE_SECTION_FIELDS,
  VIEWS_FIELDS,
  WIDGET_VIEW_FIELDS,
  WINDOW_VIEW_FIELDS,
  isSafeBundlePath,
  isSafeExtensionId,
  parseExtensionManifest,
  type Backend,
  type ExtensionManifest,
  type ExtensionManifestDocument,
  type ExtensionMeta,
  type Graph,
  type GraphDomain,
  type GraphKind,
  type ManifestParseResult,
  type PageView,
  type PermissionScope,
  type Permissions,
  type SettingField,
  type SettingType,
  type Settings,
  type SourceKind,
  type Store,
  type StoreLinks,
  type StoreSection,
  type SupportedSchemaVersion,
  type Tools,
  type Views,
  type WidgetView,
  type WindowView,
} from "./extension-manifest";
