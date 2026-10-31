// SOLX-02: pure SSE framing for the SOL turn stream (SOLUSDEV-135 backend,
// API-implementation.md §11). SSE arrives on a POST, so the transport is
// fetch + ReadableStream (solApi.ts); THIS module is transport-free — feed it
// decoded text chunks, get validated events — so vitest covers framing with
// no network.
//
// Boundary rules (CLAUDE.md §7 — the stream crosses a trust boundary):
// - every frame is shape-validated; malformed or unknown frames are DROPPED,
//   never partially delivered;
// - `tool_call` args cross only as the server's REDACTED copy (agent/stream.py runs them through
//   redact_value) and only as bounded display text: at most 16 entries, every key and value cut
//   to 64 characters, nested values flattened to JSON text (SOLUSDEV-321 P1-T6);
// - a `tool_result` carries no tool value, except a Build-mode auto-run
//   code.exec's bounded output row (SOLUSDEV-317 §10.1), plain text only;
// - `citations` must be a string array (SOL-02: the structured provenance
//   surface — a frame that can't prove that shape is malformed).

import {
  toAutoRun,
  toPendingConfirmation,
  toSolArtifact,
  type AutoRun,
  type PendingConfirmation,
  type SolArtifact
} from '../../lib/api/solStream'
import { count, record, toResearchSources, type ResearchSources } from './researchSources'

/** One entry of the turn's context manifest (SOLUSDEV-233) — labels only. */
export interface ContextSectionInfo {
  kind: string
  citation: string | null
  tokens: number
  /** The layer the section was packed into (SOLUSDEV-321 P0-T4); absent on an older frame. */
  layer?: string
}

/** One context layer of the turn, in the prompt's order: what it cost, and — when it cost
 *  nothing — the server's own reason (`empty_reason`), never one written here. */
export interface ContextLayerInfo {
  layer: string
  tokens: number
  emptyReason: string | null
}

/** An entity SOL was pointed at, and the server's reason word for it, kept as it arrived. */
export interface ContextAnchor {
  id: string
  reason: string
}

/** An anchor that never reached the scope, and the cause that lost it (null when unsaid). */
export interface DroppedContextAnchor extends ContextAnchor {
  cause: string | null
}

export interface ContextUsedInfo {
  sections: readonly ContextSectionInfo[]
  truncated: boolean
  dropped: number
  /** SOLUSDEV-321 P1-T6, "Why SOL looked here": the three fields below are absent — not empty —
   *  on a frame written before P0-T4, so the panel never claims "no anchors" it was not told. */
  layers?: readonly ContextLayerInfo[]
  anchors?: readonly ContextAnchor[]
  anchorsDropped?: readonly DroppedContextAnchor[]
}

/** A tool call's arguments as the trace shows them: the server's redacted copy, as bounded text. */
export type ToolArgs = Readonly<Record<string, string>>

/** Who answered (SOLUSDEV-321 P1-T2): the first tier, `graph`, and the fact sources it read. */
export interface AnswerSourceInfo {
  source: string
  sources: readonly string[]
}

/** A ceiling the turn reached (SOLUSDEV-321 P1-T3): which, what it used and the cap. */
export interface BudgetReachedInfo {
  limit: string
  used: number
  cap: number
}

/** What SOL weighed before proposing a change (SOLUSDEV-321 P7): model text the server parsed out
 *  of the reply, held to its shape, masked and cut (agent/reasoning_frame.py), bounded again here. */
export interface ReasoningInfo {
  considered: readonly string[]
  ruledOut: readonly { what: string; why: string }[]
  proposing: string
}

/** A `reasoning` frame on its assistant item: waiting for the proposal card it precedes
 *  (`confirmationId` null), then that card's. */
export interface CardReasoning {
  confirmationId: string | null
  reasoning: ReasoningInfo
}

/** What the frame adds to a transcript item (solChatStore's ChatItem extends it). */
export interface ReasonedItem {
  reasoning?: readonly CardReasoning[]
}

export type SolStreamEvent =
  | { type: 'token'; text: string }
  | ({ type: 'context_used' } & ContextUsedInfo)
  | { type: 'tool_call'; callId: string; tool: string; args?: ToolArgs }
  | { type: 'answer_source'; answer: AnswerSourceInfo }
  | { type: 'budget_reached'; budget: BudgetReachedInfo }
  | {
      type: 'tool_result'
      callId: string
      ok: boolean
      errorCode: string | null
      /** SOLUSDEV-317 §10.1: present only for a Build-mode auto-run code.exec. */
      autoRun?: AutoRun
    }
  | { type: 'tool_confirmation'; pending: PendingConfirmation }
  | { type: 'artifact'; artifact: SolArtifact }
  /** SOLUSDEV-321 P1-T5: the web sources a turn's research found (bounded, validated whole). */
  | { type: 'research_sources'; research: ResearchSources }
  /** SOLUSDEV-321 P7: what SOL weighed before a proposal (bounded, validated whole). */
  | { type: 'reasoning'; reasoning: ReasoningInfo }
  | { type: 'message'; role: string; content: string; citations: string[] }
  | { type: 'error'; code: string; message: string }
  | { type: 'done'; conversationId: string; turnId: string }

export interface SolStreamParser {
  /** Feed one decoded chunk; returns every event completed by it (may be empty). */
  push(chunk: string): SolStreamEvent[]
}

// ponytail: one turn's largest frame is a full assistant message (backend caps
// content), so 1 MB of undelimited buffer means a broken or hostile stream —
// discard and resync at the next frame boundary rather than grow forever.
const MAX_BUFFER_CHARS = 1_000_000

function str(value: unknown): value is string {
  return typeof value === 'string'
}

type Fields = Record<string, unknown>

// SOLUSDEV-321 P1-T6 bounds. The server sends eleven layers (agent/layers.py), keeps at most
// eight anchors (agent/reason.py MAX_ANCHORS) and lists as dropped every other id the turn named,
// which the 8,000-character message and the mention and pin lists hold far under 512. A label is
// an id, layer, reason, cause, source or limit word. Over a bound is unproven, so the frame is
// dropped whole — as with the research sources, nothing arrives half delivered.
const MAX_LAYERS = 32
const MAX_ANCHORS = 32
const MAX_DROPPED_ANCHORS = 512
const MAX_LABEL = 64
const MAX_EMPTY_REASON = 200
const MAX_ANSWER_SOURCES = 16
const MAX_TOOL_ARGS = 16
const MAX_ARG_CHARS = 64
// SOLUSDEV-321 P7: the server's own `reasoning` bounds (agent/stream.py REASONING_*).
const MAX_REASONING_ITEMS = 12
const MAX_REASONING_TEXT = 200
const MAX_PROPOSING = 400

/** A non-empty word of at most `cap` characters. */
function label(value: unknown, cap: number): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= cap
}

/** The word; null when the frame left it out (or sent null); undefined when it is unproven. */
function maybeLabel(value: unknown, cap: number): string | null | undefined {
  if (value === undefined || value === null) return null
  return label(value, cap) ? value : undefined
}

/** `text` cut to `cap` characters, the last an ellipsis when it was cut. Characters are code
 *  points (an emoji is one, as on the server), and only the head that can decide it is counted. */
function cut(text: string, cap: number): string {
  const points = Array.from(text.slice(0, 2 * cap + 1))
  return points.length <= cap ? text : `${points.slice(0, cap - 1).join('')}…`
}

const argText = (value: unknown): string =>
  typeof value === 'string' ? value : JSON.stringify(value)

/** The args of a `tool_call`, as bounded text, or undefined when there is nothing to show. The
 *  server redacted them (agent/stream.py); this bounds them so a model-proposed call with a
 *  thousand keys or a megabyte value costs the transcript a line, not a page. */
function toToolArgs(value: unknown): ToolArgs | undefined {
  const d = record(value)
  if (d === null) return undefined
  const entries = Object.entries(d)
    .slice(0, MAX_TOOL_ARGS)
    .map(([key, v]): [string, string] => [cut(key, MAX_ARG_CHARS), cut(argText(v), MAX_ARG_CHARS)])
  return entries.length > 0 ? Object.fromEntries(entries) : undefined
}

/** One small validator per frame name; anything unproven drops the frame. */
function toSection(value: unknown): ContextSectionInfo | null {
  const d = record(value)
  if (d === null || !str(d.kind) || typeof d.tokens !== 'number') return null
  if (d.citation !== null && !str(d.citation)) return null
  const layer = label(d.layer, MAX_LABEL) ? { layer: d.layer } : {}
  return { kind: d.kind, citation: d.citation, tokens: d.tokens, ...layer }
}

function toLayer(value: unknown): ContextLayerInfo | null {
  const d = record(value)
  if (d === null || !label(d.layer, MAX_LABEL) || !count(d.tokens)) return null
  const emptyReason = maybeLabel(d.empty_reason, MAX_EMPTY_REASON)
  return emptyReason === undefined ? null : { layer: d.layer, tokens: d.tokens, emptyReason }
}

function toAnchor(value: unknown): ContextAnchor | null {
  const d = record(value)
  if (d === null || !label(d.id, MAX_LABEL) || !label(d.reason, MAX_LABEL)) return null
  return { id: d.id, reason: d.reason }
}

function toDroppedAnchor(value: unknown): DroppedContextAnchor | null {
  const anchor = toAnchor(value)
  const cause = maybeLabel(record(value)?.cause, MAX_LABEL)
  return anchor === null || cause === undefined ? null : { ...anchor, cause }
}

/** A list the frame may leave out: undefined when it did, null when anything in it is unproven. */
function rows<T>(
  value: unknown,
  cap: number,
  parse: (row: unknown) => T | null
): readonly T[] | null | undefined {
  if (value === undefined) return undefined
  if (!Array.isArray(value) || value.length > cap) return null
  const parsed = value.map(parse)
  return parsed.every((row): row is T => row !== null) ? parsed : null
}

function toContextUsed(d: Fields): ContextUsedInfo | null {
  if (!Array.isArray(d.sections)) return null
  if (typeof d.truncated !== 'boolean' || typeof d.dropped !== 'number') return null
  const sections = d.sections.map(toSection)
  const layers = rows(d.layers, MAX_LAYERS, toLayer)
  const anchors = rows(d.anchors, MAX_ANCHORS, toAnchor)
  const anchorsDropped = rows(d.anchors_dropped, MAX_DROPPED_ANCHORS, toDroppedAnchor)
  if (sections.some((s) => s === null)) return null
  if (layers === null || anchors === null || anchorsDropped === null) return null
  return {
    sections: sections as ContextSectionInfo[],
    truncated: d.truncated,
    dropped: d.dropped,
    layers,
    anchors,
    anchorsDropped
  }
}

/** The tier that answered and the fact sources it read — from the live `answer_source` frame, or
 *  from the `attrs` the server stored on the assistant turn (`answer_source` + `sources`). Only
 *  `source` is required: a list left out reads as none, while one that is present but unproven
 *  drops the frame. (The frame's `citations` are not kept: the `message` frame carries them.) */
export function toAnswerSourceInfo(data: unknown): AnswerSourceInfo | null {
  const d = record(data)
  if (d === null || !label(d.source, MAX_LABEL)) return null
  const { sources = [] } = d
  if (!Array.isArray(sources) || sources.length > MAX_ANSWER_SOURCES) return null
  return sources.every((s): s is string => label(s, MAX_LABEL))
    ? { source: d.source, sources }
    : null
}

/** The ceiling a turn reached — from the live `budget_reached` frame or the stored attrs. */
export function toBudgetReachedInfo(data: unknown): BudgetReachedInfo | null {
  const d = record(data)
  if (d === null || !label(d.limit, MAX_LABEL) || !count(d.used) || !count(d.cap)) return null
  return { limit: d.limit, used: d.used, cap: d.cap }
}

/** Text of at most `cap` characters — code points, as the server counts them; a string longer
 *  than `2 * cap` UTF-16 units cannot be, so only a bounded one is split. */
function bounded(value: unknown, cap: number): value is string {
  return typeof value === 'string' && value.length <= 2 * cap && Array.from(value).length <= cap
}

const reasoningText = (value: unknown): string | null =>
  bounded(value, MAX_REASONING_TEXT) ? value : null

function toRuledOut(value: unknown): { what: string; why: string } | null {
  const d = record(value)
  return d && bounded(d.what, MAX_REASONING_TEXT) && bounded(d.why, MAX_REASONING_TEXT)
    ? { what: d.what, why: d.why }
    : null
}

/** A `reasoning` frame's payload (SOLUSDEV-321 P7), or null when anything in it is unproven: model
 *  text, so a list past twelve entries or a string past its bound drops the frame whole. */
function toReasoning(d: Fields): ReasoningInfo | null {
  const considered = rows(d.considered, MAX_REASONING_ITEMS, reasoningText)
  const ruledOut = rows(d.ruled_out, MAX_REASONING_ITEMS, toRuledOut)
  if (!considered || !ruledOut || !bounded(d.proposing, MAX_PROPOSING)) return null
  return { considered, ruledOut, proposing: d.proposing }
}

const VALIDATORS: Record<string, (d: Fields) => SolStreamEvent | null> = {
  token: (d) => (str(d.text) ? { type: 'token', text: d.text } : null),
  // SOLUSDEV-233: the turn's context manifest — kind/citation/tokens labels
  // only; the backend never sends section text and this validator would drop
  // any frame that tried to smuggle a different shape.
  // SOLUSDEV-321 P1-T6 adds where SOL looked and why (anchors, dropped anchors) and what each
  // layer cost; all Solus-authored words and counts, bounded (see toContextUsed).
  context_used: (d) => {
    const info = toContextUsed(d)
    return info ? { type: 'context_used', ...info } : null
  },
  // The args come back redacted and bounded (see the module header and toToolArgs).
  tool_call: (d) => {
    if (!str(d.call_id) || !str(d.tool)) return null
    const args = toToolArgs(d.args)
    return { type: 'tool_call', callId: d.call_id, tool: d.tool, ...(args ? { args } : {}) }
  },
  // SOLUSDEV-321 P1-T2 / P1-T3: who answered, and the ceiling a turn reached. Counts and fixed
  // words written by Solus — never model text — bounded all the same.
  answer_source: (d) => {
    const answer = toAnswerSourceInfo(d)
    return answer ? { type: 'answer_source', answer } : null
  },
  budget_reached: (d) => {
    const budget = toBudgetReachedInfo(d)
    return budget ? { type: 'budget_reached', budget } : null
  },
  tool_result: (d) => {
    if (!str(d.call_id) || typeof d.ok !== 'boolean') return null
    const error = d.error as Fields | undefined
    const errorCode = !d.ok && error && str(error.code) ? error.code : null
    const autoRun = toAutoRun(d)
    return {
      type: 'tool_result',
      callId: d.call_id,
      ok: d.ok,
      errorCode,
      ...(autoRun ? { autoRun } : {})
    }
  },
  // CTR-03: the parked destructive action. Shape-validated by the SAME reader
  // the pre-orb surface used, so there is exactly one definition of what a
  // confirmation frame is; an unusable payload drops the frame rather than
  // rendering a broken approval prompt.
  tool_confirmation: (d) => {
    const pending = toPendingConfirmation({ type: 'tool_confirmation', data: d })
    return pending ? { type: 'tool_confirmation', pending } : null
  },
  // SOLUSDEV-252 S5: a tool's ArtifactRef, after its tool_result. A reference
  // only — the bytes are fetched by the card with the bearer, never inlined.
  artifact: (d) => {
    const artifact = toSolArtifact({ type: 'artifact', data: d })
    return artifact ? { type: 'artifact', artifact } : null
  },
  // SOLUSDEV-321 P1-T5: the sources of a turn's web research, right after its tool_result. The
  // frame carries page TITLES and URLs written by other people, so it is bounded and a payload
  // with anything unproven in it is dropped whole (see researchSources.ts).
  research_sources: (d) => {
    const research = toResearchSources(d)
    return research ? { type: 'research_sources', research } : null
  },
  // SOLUSDEV-321 P7: what SOL weighed before a proposal — model text the server masked and cut,
  // bounded again (see toReasoning); the chat draws it as plain text, never markup or a link.
  reasoning: (d) => {
    const reasoning = toReasoning(d)
    return reasoning ? { type: 'reasoning', reasoning } : null
  },
  message: (d) => {
    if (!str(d.role) || !str(d.content)) return null
    if (!Array.isArray(d.citations) || !d.citations.every(str)) return null
    return { type: 'message', role: d.role, content: d.content, citations: d.citations }
  },
  error: (d) =>
    str(d.code) && str(d.message) ? { type: 'error', code: d.code, message: d.message } : null,
  done: (d) =>
    str(d.conversation_id) && str(d.turn_id)
      ? { type: 'done', conversationId: d.conversation_id, turnId: d.turn_id }
      : null
}

/** Validate one named frame into an event, or null (frame dropped). */
function toEvent(name: string, data: unknown): SolStreamEvent | null {
  if (typeof data !== 'object' || data === null) return null
  const validate = Object.prototype.hasOwnProperty.call(VALIDATORS, name) ? VALIDATORS[name] : null
  return validate ? validate(data as Fields) : null
}

/** Parse one `event:`/`data:` frame body (delimiter already stripped). */
function parseFrame(block: string): SolStreamEvent | null {
  let name = ''
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    // Comments (:), id:, retry: and unknown fields are ignored per SSE.
  }
  if (!name || dataLines.length === 0) return null
  try {
    return toEvent(name, JSON.parse(dataLines.join('\n')))
  } catch {
    return null
  }
}

export function createSolStreamParser(): SolStreamParser {
  let buffer = ''
  return {
    push(chunk) {
      buffer += chunk.replace(/\r/g, '')
      const events: SolStreamEvent[] = []
      let at: number
      while ((at = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, at)
        buffer = buffer.slice(at + 2)
        const event = parseFrame(block)
        if (event) events.push(event)
      }
      if (buffer.length > MAX_BUFFER_CHARS) buffer = ''
      return events
    }
  }
}
