// Pure transcript-item helpers for the SOL chat store (split from
// solChatStore.ts to keep it focused): turning server turns and stream events
// into immutable ChatItem updates. No store access, no side effects.
import { BENCH_VIEW_LIMITS, isBenchViewOp, type BenchViewOp } from '@solus/shared-types'
import { ApiError } from '../../lib/api/envelope.types'
import type { AutoRun } from '../../lib/api/solStream'
import { toResearchSources } from './researchSources'
import type { SolTurn } from './solApi'
import type { ChatItem } from './solChatStore'
import {
  toAnswerSourceInfo,
  toBudgetReachedInfo,
  type CardReasoning,
  type SolStreamEvent,
  type ToolArgs
} from './solStream'

/** Per-turn rendered-content ceiling (SEC-H3). Far above any real reply. */
export const MAX_TURN_CHARS = 200_000

export function turnToItem(turn: SolTurn): ChatItem {
  return {
    id: turn.id,
    role: turn.role,
    content: turn.content,
    citations: [],
    trace: [],
    pending: false,
    error: null,
    confirmations: [],
    artifacts: [],
    // The server persists `attrs.screenshot = { width, height, app }` — never pixels.
    ...(turn.attrs.screenshot !== undefined ? { hasScreenshot: true } : {})
  }
}

/** A server turn as a transcript item, with the sources its stored attrs carry (if they validate).
 *  Lives here, not beside the validator: researchSources.ts must stay a leaf, or the stream parser
 *  that imports it would close an import cycle through this file. */
export function turnToSourcedItem(turn: SolTurn): ChatItem {
  const item = turnToItem(turn)
  const research = toResearchSources(turn.attrs.research_sources)
  return research === null ? item : { ...item, researchSources: research }
}

/** A server turn as a transcript item: the research sources its stored attrs carry (P1-T5), the
 *  tier that answered and the ceiling it reached (P1-T6) — each only when it validates. */
export function turnToReasonedItem(turn: SolTurn): ChatItem {
  const item = turnToSourcedItem(turn)
  const answerSource = toAnswerSourceInfo({
    source: turn.attrs.answer_source,
    sources: turn.attrs.sources
  })
  const budgetReached = toBudgetReachedInfo(turn.attrs.budget_reached)
  return {
    ...item,
    ...(answerSource ? { answerSource } : {}),
    ...(budgetReached ? { budgetReached } : {})
  }
}

export function blankItem(
  id: string,
  role: ChatItem['role'],
  content: string,
  pending = false
): ChatItem {
  return {
    id,
    role,
    content,
    citations: [],
    trace: [],
    pending,
    error: null,
    confirmations: [],
    artifacts: []
  }
}

/** Author-safe failure text for a rejected/failed turn — never the raw error. */
export function turnFailureText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 402) return "You're out of SOL credits — top up to keep going."
    if (error.status === 429) return 'Too many SOL turns right now — give it a few seconds.'
  }
  return 'SOL is unreachable right now.'
}

export type Patch = (fn: (item: ChatItem) => ChatItem) => void

/** Append streamed text. SEC-H3: bound per-turn accumulation. */
export function appendContent(patch: Patch, text: string): void {
  patch((m) => ({
    ...m,
    content:
      m.content.length >= MAX_TURN_CHARS ? m.content : (m.content + text).slice(0, MAX_TURN_CHARS)
  }))
}

/** SOLUSDEV-317 §10.1: a cardless Build-mode command's row, once per call. */
function withAutoRun(item: ChatItem, autoRun: AutoRun | undefined): Partial<ChatItem> {
  const runs = item.autoRuns ?? []
  if (!autoRun || runs.some((r) => r.callId === autoRun.callId)) return {}
  return { autoRuns: [...runs, autoRun] }
}

/** SOLUSDEV-319 B8: a direct SOL bench-view write, as the turn's change chip (wireflow
 *  live-bench-view.md §5). `version` + `inverseOps` are null when they did not validate — the
 *  chip still shows, with no Undo. */
export interface BenchViewChange {
  readonly callId: string
  /** Solus-composed one-line description; plain text only. */
  readonly summary: string
  readonly version: number | null
  readonly inverseOps: readonly BenchViewOp[] | null
}

declare module './solChatStore' {
  interface ChatItem {
    /** Runtime only, like autoRuns: never cached. */
    benchViewChanges?: readonly BenchViewChange[]
  }
}

/** The direct writes whose result is a change chip (route doc bench-view.md §6). */
export const BENCH_VIEW_CHANGE_TOOLS: ReadonlySet<string> = new Set([
  'bench_view.update_display',
  'bench_view.upsert_derived'
])
export const BENCH_VIEW_SUMMARY_CHARS = 200

function inverseOpsOf(value: unknown): readonly BenchViewOp[] | null {
  if (!Array.isArray(value) || value.length === 0) return null
  if (value.length > BENCH_VIEW_LIMITS.maxInverseOps) return null
  return value.every(isBenchViewOp) ? value : null
}

/** A tool result value `{version, inverse_ops, summary, ...}` as a chip, or null without a
 *  usable summary. Model-adjacent data: every field is checked, nothing is trusted. */
export function toBenchViewChange(callId: string, value: unknown): BenchViewChange | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const { summary, version, inverse_ops: inverse } = value as Record<string, unknown>
  if (typeof summary !== 'string' || !summary.trim()) return null
  const inverseOps = inverseOpsOf(inverse)
  const validVersion = Number.isSafeInteger(version) && (version as number) >= 0
  const undoable = inverseOps !== null && validVersion
  return {
    callId,
    summary: summary.slice(0, BENCH_VIEW_SUMMARY_CHARS),
    version: undoable ? (version as number) : null,
    inverseOps: undoable ? inverseOps : null
  }
}

/** The chip a tool result adds to its item: only for the two direct writes (by the trace step's
 *  tool, never the value's say-so), once per call. */
export function withBenchViewChange(
  item: ChatItem,
  callId: string,
  value: unknown
): Pick<ChatItem, 'benchViewChanges'> {
  const tool = item.trace.find((step) => step.callId === callId)?.tool
  const changes = item.benchViewChanges ?? []
  if (!tool || !BENCH_VIEW_CHANGE_TOOLS.has(tool)) return {}
  if (changes.some((change) => change.callId === callId)) return {}
  const change = toBenchViewChange(callId, value)
  return change ? { benchViewChanges: [...changes, change] } : {}
}

/** A successful result's value, when the frame carries one. */
function resultValue(event: Extract<SolStreamEvent, { type: 'tool_result' }>): unknown {
  return event.ok && 'value' in event ? event.value : undefined
}

export function applyEvent(patch: Patch, event: SolStreamEvent): void {
  switch (event.type) {
    case 'token':
      appendContent(patch, event.text)
      return
    case 'tool_call':
      patch((m) => ({
        ...m,
        trace: [...m.trace, { callId: event.callId, tool: event.tool, ok: null, errorCode: null }]
      }))
      return
    case 'tool_result':
      patch((m) => ({
        ...m,
        trace: m.trace.map((t) =>
          t.callId === event.callId ? { ...t, ok: event.ok, errorCode: event.errorCode } : t
        ),
        ...withAutoRun(m, event.autoRun),
        ...withBenchViewChange(m, event.callId, resultValue(event))
      }))
      return
    case 'tool_confirmation':
      // Append, never replace. The backend dedupes by concrete action, so a
      // re-proposal arrives as the SAME confirmationId rather than a duplicate
      // card — matching on the id here keeps that true in the UI.
      patch((m) =>
        m.confirmations.some((c) => c.confirmationId === event.pending.confirmationId)
          ? m
          : { ...m, confirmations: [...m.confirmations, event.pending] }
      )
      return
    case 'artifact':
      // Keyed on the id: a re-sent frame is the same bytes, not a second card.
      patch((m) =>
        (m.artifacts ?? []).some((a) => a.artifactId === event.artifact.artifactId)
          ? m
          : { ...m, artifacts: [...(m.artifacts ?? []), { ...event.artifact, filedTo: null }] }
      )
      return
    case 'message':
      patch((m) => ({ ...m, content: event.content, citations: event.citations, pending: false }))
      return
    case 'error':
      patch((m) => ({ ...m, pending: false, error: event.message }))
      return
    case 'context_used':
    case 'done':
      return
  }
}

function attachToolArgs(patch: Patch, callId: string, args: ToolArgs): void {
  patch((item) => ({
    ...item,
    trace: item.trace.map((step) => (step.callId === callId ? { ...step, args } : step))
  }))
}

/** SOLUSDEV-321 P7: the reasoning already hung on cards — every entry but the one still waiting. */
const onCards = (item: ChatItem): readonly CardReasoning[] =>
  (item.reasoning ?? []).filter((entry) => entry.confirmationId !== null)

/** The waiting reasoning onto the card that just arrived: the proposal it preceded. A card with
 *  none waiting, or one that already has its own, is left as it is.
 *  ponytail: a round whose reasoning precedes no card (a read, an auto-run edit) leaves it waiting,
 *  so a later round's card with no block of its own shows it; the frame naming its round would
 *  close that if it ever misleads. */
function hangOnCard(item: ChatItem, confirmationId: string): ChatItem {
  const waiting = item.reasoning?.find((entry) => entry.confirmationId === null)
  if (!waiting || onCards(item).some((entry) => entry.confirmationId === confirmationId)) {
    return item
  }
  return { ...item, reasoning: [...onCards(item), { ...waiting, confirmationId }] }
}

/** SOLUSDEV-321 P1-T6: the frames that say how an answer was reached, onto the assistant item that
 *  streamed them. Run right AFTER `applyEvent`, not inside it: that switch is already at the
 *  complexity limit, and a call's args join the trace step `applyEvent` has just made — as a
 *  proposal's reasoning (P7) joins the card `applyEvent` has just appended. */
export function applyReasoningFrame(patch: Patch, event: SolStreamEvent): void {
  switch (event.type) {
    case 'answer_source':
      patch((item) => ({ ...item, answerSource: event.answer }))
      return
    case 'budget_reached':
      patch((item) => ({ ...item, budgetReached: event.budget }))
      return
    case 'tool_call':
      if (event.args) attachToolArgs(patch, event.callId, event.args)
      return
    case 'reasoning':
      // A newer round's reasoning replaces one still waiting for its card.
      patch((item) => ({
        ...item,
        reasoning: [...onCards(item), { confirmationId: null, reasoning: event.reasoning }]
      }))
      return
    case 'tool_confirmation':
      patch((item) => hangOnCard(item, event.pending.confirmationId))
      return
  }
}
