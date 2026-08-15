// SOLX-02: pure SSE framing for the SOL turn stream (SOLUSDEV-135 backend,
// API-implementation.md §11). SSE arrives on a POST, so the transport is
// fetch + ReadableStream (solApi.ts); THIS module is transport-free — feed it
// decoded text chunks, get validated events — so vitest covers framing with
// no network.
//
// Boundary rules (CLAUDE.md §7 — the stream crosses a trust boundary):
// - every frame is shape-validated; malformed or unknown frames are DROPPED,
//   never partially delivered;
// - `tool_call` args are discarded at the parse boundary — the trace renders
//   tool name + ok/error only, so raw argument values never reach the UI;
// - `citations` must be a string array (SOL-02: the structured provenance
//   surface — a frame that can't prove that shape is malformed).

import { toPendingConfirmation, type PendingConfirmation } from '../../lib/api/solStream'

export type SolStreamEvent =
  | { type: 'token'; text: string }
  | { type: 'tool_call'; callId: string; tool: string }
  | { type: 'tool_result'; callId: string; ok: boolean; errorCode: string | null }
  | { type: 'tool_confirmation'; pending: PendingConfirmation }
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

/** One small validator per frame name; anything unproven drops the frame. */
const VALIDATORS: Record<string, (d: Fields) => SolStreamEvent | null> = {
  token: (d) => (str(d.text) ? { type: 'token', text: d.text } : null),
  // args intentionally not carried across (see module header).
  tool_call: (d) =>
    str(d.call_id) && str(d.tool) ? { type: 'tool_call', callId: d.call_id, tool: d.tool } : null,
  tool_result: (d) => {
    if (!str(d.call_id) || typeof d.ok !== 'boolean') return null
    const error = d.error as Fields | undefined
    const errorCode = !d.ok && error && str(error.code) ? error.code : null
    return { type: 'tool_result', callId: d.call_id, ok: d.ok, errorCode }
  },
  // CTR-03: the parked destructive action. Shape-validated by the SAME reader
  // the pre-orb surface used, so there is exactly one definition of what a
  // confirmation frame is; an unusable payload drops the frame rather than
  // rendering a broken approval prompt.
  tool_confirmation: (d) => {
    const pending = toPendingConfirmation({ type: 'tool_confirmation', data: d })
    return pending ? { type: 'tool_confirmation', pending } : null
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
