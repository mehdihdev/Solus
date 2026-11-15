// SOLUSDEV-326: server turns as transcript items, with each reply's stored tool rows folded into its
// steps — so a reloaded turn shows one Thinking block, as it did live, instead of a column of grey
// `tool → outcome` lines above the reply.
//
// The server stores a turn's tool rows BEFORE its assistant turn (routers/sol.py _persist_turn), with
// `attrs = {call: {call_id, tool, args}, result: {ok, error: {code}}}` — redacted before it was
// stored. A row folds only when that shape proves out; anything else stays a row, never a step
// invented from prose. Rows with no reply after them (an aborted turn) also stay rows.
import { turnToReasonedItem } from './solChatItems'
import type { SolTurn } from './solApi'
import type { ChatItem, TraceEntry } from './solChatStore'
import { toToolArgs } from './solStream'

/** Display bound on a stored tool name or error code (they are Solus-authored ids). */
const MAX_ID_CHARS = 128

const record = (value: unknown): Record<string, unknown> | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null

const id = (value: unknown): string | null =>
  typeof value === 'string' && value.length > 0 && value.length <= MAX_ID_CHARS ? value : null

/** The stored call: its id, tool and redacted args — or null when unproven. */
function storedCall(value: unknown): Pick<TraceEntry, 'callId' | 'tool' | 'args'> | null {
  const call = record(value)
  const tool = id(call?.tool)
  const callId = id(call?.call_id)
  if (!call || !tool || !callId) return null
  const args = toToolArgs(call.args)
  return { callId, tool, ...(args ? { args } : {}) }
}

/** The stored outcome: ok, or the error code it failed with — or null when unproven. */
function storedOutcome(value: unknown): Pick<TraceEntry, 'ok' | 'errorCode'> | null {
  const result = record(value)
  if (!result || typeof result.ok !== 'boolean') return null
  return {
    ok: result.ok,
    errorCode: result.ok ? null : (id(record(result.error)?.code) ?? 'error')
  }
}

/** A stored tool row as a step, or null when its attrs are unproven. */
export function toStoredStep(turn: SolTurn): TraceEntry | null {
  const call = storedCall(turn.attrs.call)
  const outcome = storedOutcome(turn.attrs.result)
  return call && outcome ? { ...call, ...outcome } : null
}

export function foldToolTurns(turns: readonly SolTurn[]): ChatItem[] {
  const items: ChatItem[] = []
  let rows: ChatItem[] = []
  let steps: TraceEntry[] = []
  for (const turn of turns) {
    const step = turn.role === 'tool' ? toStoredStep(turn) : null
    if (step) {
      rows = [...rows, turnToReasonedItem(turn)]
      steps = [...steps, step]
      continue
    }
    if (turn.role === 'assistant' && steps.length > 0) {
      const reply = turnToReasonedItem(turn)
      items.push({ ...reply, trace: [...steps, ...reply.trace] })
    } else {
      items.push(...rows, turnToReasonedItem(turn))
    }
    rows = []
    steps = []
  }
  return [...items, ...rows]
}
