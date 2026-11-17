// Pure transcript-item helpers for the SOL chat store (split from
// solChatStore.ts to keep it focused): turning server turns and stream events
// into immutable ChatItem updates. No store access, no side effects.
import { ApiError } from '../../lib/api/envelope.types'
import type { AutoRun, PendingConfirmation } from '../../lib/api/solStream'
import { toResearchSources } from './researchSources'
import { toThinkingInfo } from './thinking'
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

/** Which Solus-written turn a stored user turn is, from the server's own attrs — never from its
 *  words: a notice is `authored_by: "solus"`, an answer carries the `answer` it settled. */
function storedKind(turn: SolTurn): Pick<ChatItem, 'kind'> {
  if (turn.role !== 'user') return {}
  if (turn.attrs.authored_by === 'solus') return { kind: 'notice' }
  const answer = turn.attrs.answer
  return typeof answer === 'object' && answer !== null ? { kind: 'answer' } : {}
}

const CHOSE = /^Chose ("(?:[^"\\]|\\.)*")(?: — ([\s\S]*))?$/

const EDITED = /^([\s\S]*?): ("(?:[^"\\]|\\.)*")$/

/** An answer turn's words as the receipt the thread shows (routers/sol_cards.py `answer_prompt`,
 *  and `answerLabel` live): `Chose "<label>"`, then ` — <typed>`, reads "Answered: Yes"; an
 *  edit's `<field label>: "<value>"` reads "Edited: Robot name — Rover arm". Read from the words
 *  alone, so it holds whatever mark `attrs.answer` carries for an edit. The label and the value
 *  come back as plain strings, for a text node only. */
export function answerReceipt(content: string): string {
  try {
    const chose = CHOSE.exec(content)
    if (chose) return `Answered: ${String(JSON.parse(chose[1]))}${chose[2] ? ` — ${chose[2]}` : ''}`
    const edited = EDITED.exec(content)
    if (edited) return `Edited: ${edited[1]} — ${String(JSON.parse(edited[2]))}`
  } catch {
    // Not the server's quoting: the words stand as they are.
  }
  return content
}

export function turnToItem(turn: SolTurn): ChatItem {
  return {
    id: turn.id,
    role: turn.role,
    ...storedKind(turn),
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
  const thinking = toThinkingInfo(turn.attrs.thinking)
  return {
    ...item,
    ...(answerSource ? { answerSource } : {}),
    ...(budgetReached ? { budgetReached } : {}),
    ...(thinking ? { thinking } : {})
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
        ...withAutoRun(m, event.autoRun)
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

/** What a `tool_call` frame says beside the call itself: its args and its working line. */
function attachToStep(
  patch: Patch,
  callId: string,
  extra: { args?: ToolArgs; working?: string }
): void {
  patch((item) => ({
    ...item,
    trace: item.trace.map((step) => (step.callId === callId ? { ...step, ...extra } : step))
  }))
}

/** SOLUSDEV-326: what SOL is doing right now, in the tool's own words: the newest call still in
 *  flight on a reply that has nothing to say yet. Null whenever there is text to read instead. */
export function workingLine(items: readonly ChatItem[]): string | null {
  const last = items[items.length - 1]
  if (!last?.pending || last.content) return null
  const step = [...last.trace].reverse().find((entry) => entry.ok === null && entry.working)
  return step?.working ?? null
}

/** The gate's answer to a call it will not run now: a park and a real refusal alike
 *  (agent/tools/shapes.py `ToolErrorCode.UNAUTHORIZED`). */
const GATE_REFUSED = 'unauthorized'

/** SOLUSDEV-326: a parked call's step stops reading as a failure. The server streams a parked
 *  call's `tool_confirmation` straight after its result (routers/sol.py `_drain_parked`), so the
 *  frame's step is the newest one of its tool the gate refused and no card has claimed. A refusal
 *  with no frame after it (Guide, a rejected call, the same action proposed twice) stays one.
 *  Run on every frame, before the store drops a card it already shows. */
export function markParked(patch: Patch, event: SolStreamEvent): void {
  if (event.type !== 'tool_confirmation') return
  const { confirmationId, tool } = event.pending
  patch((item) => {
    const at = item.trace.findLastIndex(
      (step) => step.tool === tool && step.errorCode === GATE_REFUSED && !step.parked
    )
    if (at < 0) return item
    const trace = item.trace.map((step, i) =>
      i === at ? { ...step, parked: { confirmationId } } : step
    )
    return { ...item, trace }
  })
}

/** The steps after a card was decided: the one it parked says which way. */
export function decidedTrace(
  trace: ChatItem['trace'],
  confirmationId: string,
  decision: 'approve' | 'reject'
): ChatItem['trace'] {
  return trace.map((step) =>
    step.parked?.confirmationId === confirmationId
      ? { ...step, parked: { confirmationId, decision } }
      : step
  )
}

/** The message text after a decision: a restored approvals item says what
 *  happened; a chat message gains an "Approval update" line. */
export function decidedContent(
  m: ChatItem,
  confirmationId: string,
  decision: 'approve' | 'reject'
): string {
  const approved = decision === 'approve'
  if (!m.id.startsWith('approvals-')) {
    const tool = m.confirmations.find((c) => c.confirmationId === confirmationId)?.tool ?? 'Action'
    return `${m.content}\n\nApproval update: ${tool} ${approved ? 'approval recorded' : 'was rejected'}.`
  }
  if (m.confirmations.length !== 1) return m.content
  return approved ? 'Approval recorded.' : 'Action rejected.'
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
      if (event.args || event.working) {
        attachToStep(patch, event.callId, {
          ...(event.args ? { args: event.args } : {}),
          ...(event.working ? { working: event.working } : {})
        })
      }
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

/** A history load merged with what is live: the loaded turns, then the conversation's still-open
 *  rows the live items do not already carry (one "Awaiting your approval" item), then the local
 *  items a send appended meanwhile. `decided` names rows decided here since the server listed them. */
export function withRestored(
  loaded: readonly ChatItem[],
  current: readonly ChatItem[],
  conversationId: string,
  approvals: readonly PendingConfirmation[],
  decided: (confirmationId: string) => boolean
): ChatItem[] {
  const local = current.filter((m) => m.id.startsWith('local-'))
  const liveIds = new Set(local.flatMap((m) => m.confirmations.map((c) => c.confirmationId)))
  const restored = approvals.filter(
    (c) => !liveIds.has(c.confirmationId) && !decided(c.confirmationId)
  )
  const awaiting: ChatItem[] = restored.length
    ? [
        {
          ...blankItem(`approvals-${conversationId}`, 'assistant', 'Awaiting your approval'),
          confirmations: restored
        }
      ]
    : []
  return [...loaded, ...awaiting, ...local]
}
