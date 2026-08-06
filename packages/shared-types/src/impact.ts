// SOLUSDEV-219 (CTR-04) — the impact result contract.
//
// Impact is the flagship surface, and it was fully serialised: engine (LANE A,
// backend) -> consequence model (LANE A) -> widget (LANE B, frontend), with the
// widget also blocked on the SOL lane. Publishing the RESULT shape lets the
// engine and the widget be built at the same time, with fixtures standing in for
// the engine until it lands.
//
// WIRE SHAPE, snake_case, mirroring solus_api/contracts/impact.py — the two are
// validated against one set of fixtures. `Focus` (focus.ts) is camelCase because
// it is frontend state, not a wire type; `focusOfImpactNode` below is the
// documented bridge, and it is also the "jump to focus" operation every row
// needs, so the mapping is the deliverable rather than overhead.
//
// See docs/contracts/impact.md.

import type { CompleteKeysOf } from "./json";
import type { Domain, EntityRef, Focus, FocusStep } from "./focus";
import type { DiffRow } from "./action-gate";

/**
 * Severity, mirroring `solus_api.checkers.interface.Severity` (CHK-01).
 *
 * Ordered by REAL-WORLD impact, not style: `critical` = the robot will not work
 * or may be damaged; `warning` = degraded or unreliable; `info` = advisory.
 * Reused rather than re-declared — one severity vocabulary across checkers,
 * impact and autocomplete is the point.
 */
/**
 * A locator is a REFERENCE, never a URL. Accepts `firmware/motor_ctl.cpp:88`,
 * `sch:U3`, `cad:drive_harness`; refuses `javascript:`, `data:`, `http(s):` and
 * the characters a payload needs. A widget renders it as text and resolves it
 * itself — it must never go straight into an `href`.
 */
export const LOCATOR_PATTERN =
  /^(?!(?:javascript|data|vbscript|file|blob|https?):)(?:[a-z][a-z0-9_]*:)?[\w./-]+(?::\d+)?$/;

export const SEVERITIES = ["info", "warning", "critical"] as const;
export type Severity = (typeof SEVERITIES)[number];

/** Higher is worse. Use it to sort; never sort severity strings alphabetically. */
export function severityRank(severity: Severity): number {
  return SEVERITIES.indexOf(severity);
}

/** The worst of a set. Empty means `info` — no consequences is not an error. */
export function worstSeverity(severities: readonly Severity[]): Severity {
  return severities.reduce<Severity>(
    (worst, s) => (severityRank(s) > severityRank(worst) ? s : worst),
    "info",
  );
}

/** A graph entity as the API addresses it. `toEntityRef` converts to `Focus`'s form. */
export interface ImpactEntity {
  readonly project_id: string;
  readonly entity_id: string;
}

/** One hop of the traversal from the focus toward an affected entity. */
export interface ImpactPathStep {
  readonly entity: ImpactEntity;
  readonly domain: Domain;
  readonly label: string;
  /** `graph_edge.relation_type` traversed from this step toward the next. */
  readonly relation: string;
}

/** Where to look. `locator` is the thing a UI turns into a link. */
export interface ConsequenceEvidence {
  readonly label: string;
  readonly detail: string;
  /**
   * e.g. `firmware/motor_ctl.cpp:88`, `sch:U3`, `cad:drive_harness`. Null when
   * there is no place to point.
   *
   * Matches `LOCATOR_PATTERN`. An impact result is data a model may have
   * influenced, and this is the field a UI turns into a link — unconstrained it
   * would accept `javascript:` and `https://attacker/?leak=`.
   *
   * ⚠ RENDER EVERY STRING ON THIS CONTRACT AS A TEXT NODE, never as HTML and
   * never as a bare `href`. `rationale`, `headline` and `label` are plain text.
   */
  readonly locator: string | null;
}

/**
 * A SOL action a row can launch.
 *
 * `args` is a PROPOSAL, not an authorisation. If the tool is destructive it
 * still routes through the confirmation gate, which re-derives and stores its
 * own arguments — see docs/contracts/action-gate.md. Nothing here bypasses it.
 */
export interface SolAction {
  readonly tool: string;
  readonly label: string;
  readonly args: Readonly<Record<string, unknown>>;
}

/**
 * One specific thing that goes wrong at an affected entity.
 *
 * An entity can have several: the driver may be both under-rated and thermally
 * marginal. `rationale` is the why-this-matters prose — the reason Impact is
 * worth reading rather than a list of rule names.
 */
export interface Consequence {
  readonly id: string;
  readonly severity: Severity;
  /** One line, for the collapsed row. */
  readonly headline: string;
  /** Why this matters, in the user's terms. Respects SOL mode at render time (ADR-016). */
  readonly rationale: string;
  readonly evidence: readonly ConsequenceEvidence[];
  /** Null when there is no proposable fix — nullable, never absent. */
  readonly action: SolAction | null;
}

/**
 * An entity the change reaches, with everything that goes wrong there.
 *
 * `severity` is the worst of `consequences`, precomputed so a widget can sort
 * without walking every consequence. `path` is the traversal back to the focus,
 * starting AT the focus.
 */
export interface ImpactNode {
  readonly entity: ImpactEntity;
  readonly label: string;
  readonly domain: Domain;
  readonly severity: Severity;
  /** Hops from the focus. Always equals `path.length`. */
  readonly distance: number;
  readonly path: readonly ImpactPathStep[];
  readonly consequences: readonly Consequence[];
}

/** What was focused when the change happened. */
export interface ImpactFocus {
  readonly entity: ImpactEntity;
  readonly domain: Domain;
  readonly label: string;
}

/** One impact analysis. `nodes: []` means "nothing downstream broke" — a real answer. */
export interface ImpactResult {
  readonly focus: ImpactFocus;
  /** The change that caused this, as diff rows — the same shape the action gate renders. */
  readonly change: readonly DiffRow[];
  readonly computed_at: string;
  /**
   * Whether the traversal hit its bound (IMP-01 traverses to a bounded depth).
   * A widget that does not surface this presents a partial answer as a complete one.
   */
  readonly truncated: boolean;
  readonly nodes: readonly ImpactNode[];
}

/** Wire entity -> the `Focus` store's form. */
export function toEntityRef(entity: ImpactEntity): EntityRef {
  return { projectId: entity.project_id, entityId: entity.entity_id };
}

/**
 * The focus a row jumps to, breadcrumb included.
 *
 * Every impact row offers "show me this", and six lanes hand-rolling the
 * conversion would produce six different breadcrumbs — the same reason
 * `descend` exists in focus.ts. The resulting `path` is the traversal that
 * found the node, so the user sees how the change reached it.
 *
 * Takes the node alone: its `path` already starts at the focus, so the result
 * it came from adds nothing a caller would have to keep in scope.
 */
export function focusOfImpactNode(node: ImpactNode): Focus {
  const path: FocusStep[] = node.path.map((step) => ({
    entity: toEntityRef(step.entity),
    domain: step.domain,
    label: step.label,
    relation: step.relation,
  }));
  return {
    entity: toEntityRef(node.entity),
    domain: node.domain,
    label: node.label,
    path,
  };
}

// ── the field lists the drift guard checks against (see action-gate.ts) ──────

const IR = ["focus", "change", "computed_at", "truncated", "nodes"] as const;
export const IMPACT_RESULT_FIELDS: CompleteKeysOf<ImpactResult, typeof IR> = IR;

const IN = ["entity", "label", "domain", "severity", "distance", "path", "consequences"] as const;
export const IMPACT_NODE_FIELDS: CompleteKeysOf<ImpactNode, typeof IN> = IN;

const CQ = ["id", "severity", "headline", "rationale", "evidence", "action"] as const;
export const CONSEQUENCE_FIELDS: CompleteKeysOf<Consequence, typeof CQ> = CQ;

const CE = ["label", "detail", "locator"] as const;
export const CONSEQUENCE_EVIDENCE_FIELDS: CompleteKeysOf<ConsequenceEvidence, typeof CE> = CE;

const SA = ["tool", "label", "args"] as const;
export const SOL_ACTION_FIELDS: CompleteKeysOf<SolAction, typeof SA> = SA;
