import type { CompleteKeysOf } from "./json";

// SOLUSDEV-218 (CTR-03) — the destructive-action gate contract.
//
// THIS DOCUMENTS A SHIPPED GATE. IT DOES NOT REDESIGN ONE. Every shape here is
// read from the SOLUS-ONS-A5 implementation on branch
// SOLUSDEV-60/ons-ui01-confirmation-surface (commit 8c9b812):
//
//   ConfirmationStatus          solus_api/models.py:176-190
//   ToolConfirmation columns    solus_api/models.py:654-699
//   ConfirmationDecision body   solus_api/schemas.py:166-175
//   the decide endpoint         solus_api/routers/sol.py:446-494
//   park / decide / STALE       solus_api/agent/confirmations.py
//   the streamed event          solus_api/agent/stream.py:57-81
//
// ⚠ That work is NOT yet on `main`. On `main` today the gate is a flat
// fail-closed refusal (solus_api/agent/runtime.py:162). Publishing the shape
// here is what lets the Tool viewport (WS-06) and the Impact widget (IMP-03)
// build the approval surface while the SOL lane builds the dispatcher behind it.
//
// SHAPES ARE WIRE SHAPES — snake_case, exactly as the API emits them, so the
// fixtures in ../fixtures/action-gate/ can be validated by BOTH this file and
// the Pydantic mirror in solus_api/contracts/action_gate.py. A renderer is free
// to map these into camelCase locally; the contract is the wire.
//
// See docs/contracts/action-gate.md.

/** Lifecycle of one approval. Terminal in every state but `pending`. */
export const CONFIRMATION_STATUSES = [
  "pending",
  "approved",
  "rejected",
  "expired",
  "stale",
] as const;
export type ConfirmationStatus = (typeof CONFIRMATION_STATUSES)[number];

/**
 * What a user may decide. **There is no `amend`.**
 *
 * Amend would mean the client supplies arguments at decision time, and the whole
 * security property of this round-trip is that it cannot: what was shown is what
 * executes. To change an action, reject it and ask SOL to propose the new one.
 */
export const CONFIRMATION_DECISIONS = ["approve", "reject"] as const;
export type ConfirmationDecision = (typeof CONFIRMATION_DECISIONS)[number];

/** `solus_api.agent.tools.shapes.ToolErrorCode`. */
export type ToolErrorCode =
  | "invalid_args"
  | "not_found"
  | "tool_error"
  | "timeout"
  | "unauthorized"
  | "unavailable";

/** How long a parked action stays approvable (`confirmations.CONFIRMATION_TTL`). */
export const CONFIRMATION_TTL_MINUTES = 30;

/**
 * One row of the diff being approved.
 *
 * Generic across every tool kind by construction — a CAD edit, a firmware flash
 * and a robot command all render the same three fields. `before` is null for an
 * action that does not REPLACE a value; the row then reports the argument the
 * action will run with, read from the same stored dict that executes.
 */
export interface DiffRow {
  readonly label: string;
  readonly before: string | null;
  readonly after: string | null;
}

/**
 * The `tool_confirmation` SSE event: a destructive action parked for approval.
 *
 * It carries the CONCRETE action — tool, arguments, a readable summary and the
 * diff — because a user cannot meaningfully approve an opaque id.
 */
export interface ToolConfirmationEvent {
  readonly confirmation_id: string;
  readonly tool: string;
  /** The stored arguments. Displayed IS executed — the client cannot change them. */
  readonly args: Readonly<Record<string, unknown>>;
  /** The action in words, authored by Solus (never by an upstream fork). */
  readonly summary: string;
  /** Empty when the tool offers no preview; the summary is then the consent. */
  readonly preview: readonly DiffRow[];
}

/**
 * The decide request body. A decision and NOTHING ELSE — the server model sets
 * `extra="forbid"`, so a body carrying its own `args` is a 422, not a merge.
 */
export interface ConfirmationDecisionRequest {
  readonly decision: ConfirmationDecision;
}

/** `solus_api.agent.tools.shapes.ToolError`. */
export interface ToolErrorPayload {
  readonly code: ToolErrorCode;
  readonly message: string;
  readonly retryable: boolean;
}

/** `solus_api.agent.tools.shapes.ToolResult`. `ok` and `error` are exclusive. */
export interface ToolResultPayload {
  readonly call_id: string;
  readonly ok: boolean;
  readonly value: Readonly<Record<string, unknown>> | null;
  readonly error: ToolErrorPayload | null;
}

/**
 * The decide endpoint's 200 body.
 *
 * ⚠ **HTTP 200 does not mean the action ran.** Wrong project, already decided,
 * expired, rejected, stale and tool-gone are ALL 200 with `data.ok === false`.
 * Only a non-member gets a 4xx (404, deliberately, so there is no existence
 * oracle). A UI that treats 200 as success is wrong.
 */
export interface ConfirmationOutcomeEnvelope {
  readonly data: ToolResultPayload;
}

/**
 * Whether an outcome means the action did NOT run. The 200-is-not-success guard.
 *
 * Takes the structural minimum rather than the full envelope, so it also accepts
 * a body that has not been narrowed yet — a caller should be able to ask the one
 * question that matters before it has proved anything about the error code.
 */
export function isConfirmationRefused(outcome: {
  readonly data: { readonly ok: boolean };
}): boolean {
  return !outcome.data.ok;
}

/** The shipped decide route (`routers/sol.py:446`). */
export function confirmationDecisionPath(
  projectId: string,
  confirmationId: string,
): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/sol/confirmations/${encodeURIComponent(confirmationId)}`;
}

// ── the field lists the drift guard checks against ───────────────────────────
// `satisfies` alone does not catch an ADDED field on a JSON import (freshness is
// lost on a variable), so these lists — proven complete against the interfaces
// by CompleteKeysOf — are compared at runtime with the manifest Pydantic emits.

const TC_FIELDS = ["confirmation_id", "tool", "args", "summary", "preview"] as const;
export const TOOL_CONFIRMATION_EVENT_FIELDS: CompleteKeysOf<
  ToolConfirmationEvent,
  typeof TC_FIELDS
> = TC_FIELDS;

const DR_FIELDS = ["label", "before", "after"] as const;
export const DIFF_ROW_FIELDS: CompleteKeysOf<DiffRow, typeof DR_FIELDS> = DR_FIELDS;
