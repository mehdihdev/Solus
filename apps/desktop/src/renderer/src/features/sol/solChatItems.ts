// Pure transcript-item helpers for the SOL chat store (split from
// solChatStore.ts to keep it focused): turning server turns and stream events
// into immutable ChatItem updates. No store access, no side effects.
import { ApiError } from '../../lib/api/envelope.types'
import type { SolTurn } from './solApi'
import type { ChatItem } from './solChatStore'
import type { SolStreamEvent } from './solStream'

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
        )
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
