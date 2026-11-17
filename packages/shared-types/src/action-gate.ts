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
  /** SOLUSDEV-326: the Solus-authored card, when the tool authors one. Presentation only. */
  readonly card?: Card | null;
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

// ── SOLUSDEV-326: cards ──────────────────────────────────────────────────────
// See docs/contracts/action-gate.md §Cards. A card is the Solus-authored
// presentation of a parked call, computed once from its STORED arguments. It is
// never part of the consent or the stale check, and never sent back: the decision
// body is still a decision and nothing else.

/** The four kinds a card takes; the Hardware page's slot draws each its own way. */
export const CARD_KINDS = ["offer", "approval", "step", "problem"] as const;
export type CardKind = (typeof CARD_KINDS)[number];

/** A value the card shows. Never sent back: an edit becomes the person's answer turn. */
export interface CardField {
  readonly label: string;
  readonly value: string;
}

export interface Card {
  readonly kind: CardKind;
  /** At most 8 words, one line; an approval's starts "Approve:". */
  readonly title: string;
  /** At most 2 lines; `backtick` spans render as code chips. */
  readonly body: string;
  /** Guide mode's one-sentence explanation behind "more"; null in Expert. */
  readonly more: string | null;
  readonly field: CardField | null;
  /** At most 24 characters. */
  readonly primary: string;
  readonly secondary: string | null;
  /** The one line "Done so far" gains on approve. */
  readonly receipt: string;
  /** Server-set: SOL continues after any decision on this card. */
  readonly resumes: boolean;
}

export interface OpenCard {
  readonly confirmation_id: string;
  readonly conversation_id: string;
  readonly tool: string;
  readonly card: Card;
  /** ISO 8601; an expired card becomes a Problem with "Ask again". */
  readonly expires_at: string;
}

/** `GET …/sol/cards/open`: the caller's oldest open card here, and how many more wait. */
export interface OpenCards {
  readonly card: OpenCard | null;
  readonly queued: number;
}

/** `MessageCreate.notice`: something was plugged in; the server writes the turn. */
export interface DeviceNotice {
  readonly kind: "device";
  readonly device_ref: string;
}

/**
 * `MessageCreate.answer`: 0 is the primary button, 1 the secondary. It may also name an open card
 * with a `field`: an edit, choice 0 with `text` the new value, which expires the card undecided.
 */
export interface QuestionAnswer {
  readonly question_id: string;
  readonly choice: 0 | 1;
  readonly text?: string | null;
}

/** The open-card route. */
export function openCardsPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/sol/cards/open`;
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

const TC_FIELDS = [
  "confirmation_id",
  "tool",
  "args",
  "summary",
  "preview",
  "card",
] as const;
export const TOOL_CONFIRMATION_EVENT_FIELDS: CompleteKeysOf<
  ToolConfirmationEvent,
  typeof TC_FIELDS
> = TC_FIELDS;

const DR_FIELDS = ["label", "before", "after"] as const;
export const DIFF_ROW_FIELDS: CompleteKeysOf<DiffRow, typeof DR_FIELDS> =
  DR_FIELDS;

const CARD_KEYS = [
  "kind",
  "title",
  "body",
  "more",
  "field",
  "primary",
  "secondary",
  "receipt",
  "resumes",
] as const;
export const CARD_FIELDS: CompleteKeysOf<Card, typeof CARD_KEYS> = CARD_KEYS;

const CF_FIELDS = ["label", "value"] as const;
export const CARD_FIELD_FIELDS: CompleteKeysOf<CardField, typeof CF_FIELDS> =
  CF_FIELDS;

const OC_FIELDS = [
  "confirmation_id",
  "conversation_id",
  "tool",
  "card",
  "expires_at",
] as const;
export const OPEN_CARD_FIELDS: CompleteKeysOf<OpenCard, typeof OC_FIELDS> =
  OC_FIELDS;

const OCS_FIELDS = ["card", "queued"] as const;
export const OPEN_CARDS_FIELDS: CompleteKeysOf<OpenCards, typeof OCS_FIELDS> =
  OCS_FIELDS;

const DN_FIELDS = ["kind", "device_ref"] as const;
export const DEVICE_NOTICE_FIELDS: CompleteKeysOf<
  DeviceNotice,
  typeof DN_FIELDS
> = DN_FIELDS;

const QA_FIELDS = ["question_id", "choice", "text"] as const;
export const QUESTION_ANSWER_FIELDS: CompleteKeysOf<
  QuestionAnswer,
  typeof QA_FIELDS
> = QA_FIELDS;
