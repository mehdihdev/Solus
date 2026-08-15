// SOLX-02: chat state for the SOL orb/screen. Owns the per-project history
// (loaded from GET …/turns via the stored conversation id), conversation
// creation on first send, and the fold of stream events into an immutable
// item list. The orbStore streaming flag wraps every turn so the orb pulses
// exactly while SOL is thinking.
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createSolConversation,
  listSolTurns,
  streamSolMessage,
  type SolActionMode,
  type SolTurn
} from './solApi'
import type { SolStreamEvent } from './solStream'
import { decideSolConfirmation } from '../../lib/api/resources'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { selectConversationId, useOrbStore } from './orbStore'

export interface TraceEntry {
  callId: string
  tool: string
  /** Null while the call is in flight. */
  ok: boolean | null
  errorCode: string | null
}

export interface ChatItem {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  /** SOL-02: structured provenance from the message event — never parsed from prose. */
  citations: readonly string[]
  trace: readonly TraceEntry[]
  pending: boolean
  /** Author-safe failure text (backend error frame or a local transport note). */
  error: string | null
  /** CTR-03: a parked destructive action awaiting this user's approval, shown
   *  inline on the turn that proposed it. Null once decided or never parked. */
  confirmation: PendingConfirmation | null
}

export type ChatStatus = 'loading' | 'ready' | 'offline'

export interface SolChat {
  items: readonly ChatItem[]
  status: ChatStatus
  streaming: boolean
  send: (content: string, actionMode: SolActionMode) => Promise<void>
  /** CTR-03: record approve/reject for a parked action. Rejection is a decision
   *  too, so both clear the card; the arguments that execute are the stored
   *  server-side ones the user was shown, never re-sent from here. */
  decide: (confirmationId: string, decision: 'approve' | 'reject') => Promise<void>
}

let itemSeq = 0
const nextItemId = (): string => `local-${++itemSeq}`

function turnToItem(turn: SolTurn): ChatItem {
  return {
    id: turn.id,
    role: turn.role,
    content: turn.content,
    citations: [],
    trace: [],
    pending: false,
    error: null,
    confirmation: null
  }
}

type Patch = (fn: (item: ChatItem) => ChatItem) => void

function applyEvent(patch: Patch, event: SolStreamEvent): void {
  switch (event.type) {
    case 'token':
      // SEC-H3: bound per-turn accumulation — a runaway stream must not grow
      // the renderer's memory without limit.
      patch((m) => ({
        ...m,
        content:
          m.content.length >= MAX_TURN_CHARS
            ? m.content
            : (m.content + event.text).slice(0, MAX_TURN_CHARS)
      }))
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
      patch((m) => ({ ...m, confirmation: event.pending }))
      return
    case 'message':
      patch((m) => ({ ...m, content: event.content, citations: event.citations, pending: false }))
      return
    case 'error':
      patch((m) => ({ ...m, pending: false, error: event.message }))
      return
    case 'done':
      return
  }
}

/** Per-turn rendered-content ceiling (SEC-H3). Far above any real reply. */
const MAX_TURN_CHARS = 200_000

export function useSolChat(projectId: string | null): SolChat {
  const [items, setItems] = useState<ChatItem[]>([])
  const [status, setStatus] = useState<ChatStatus>('ready')
  const streaming = useOrbStore((s) => s.streaming)
  const sendingRef = useRef(false)
  //#: SEC-H3: the in-flight stream, so unmount and project switches cancel it
  //  rather than leaving a read running (and the composer wedged).
  const abortRef = useRef<AbortController | null>(null)

  // Keyed on the PROJECT only: creating a conversation mid-send must not
  // trigger a reload that wipes the streaming item. The stored conversation id
  // is read once per project switch (detached-window sync rides persistence).
  useEffect(() => {
    setItems([])
    const conversationId = selectConversationId(useOrbStore.getState(), projectId)
    if (!projectId || !conversationId) {
      setStatus('ready')
      return
    }
    let stale = false
    setStatus('loading')
    listSolTurns(projectId, conversationId)
      .then((turns) => {
        if (stale) return
        const loaded = [...turns].reverse().map(turnToItem)
        // Merge, don't replace: a send may have appended local items while
        // history was in flight — loading must never wipe a live turn.
        setItems((prev) => [...loaded, ...prev.filter((m) => m.id.startsWith('local-'))])
        setStatus('ready')
      })
      .catch(() => {
        if (!stale) setStatus('offline')
      })
    return () => {
      stale = true
      // Switching project (or unmounting) cancels any live turn: its tokens
      // belong to a chat we are no longer showing.
      abortRef.current?.abort()
      abortRef.current = null
      sendingRef.current = false
      useOrbStore.getState().setStreaming(false)
    }
  }, [projectId])

  const send = useCallback(
    async (content: string, actionMode: SolActionMode): Promise<void> => {
      const text = content.trim()
      if (!text || !projectId || sendingRef.current) return
      sendingRef.current = true
      useOrbStore.getState().setStreaming(true)
      const assistantId = nextItemId()
      const patch: Patch = (fn) =>
        setItems((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)))
      setItems((prev) => [
        ...prev,
        {
          id: nextItemId(),
          role: 'user',
          content: text,
          citations: [],
          trace: [],
          pending: false,
          error: null,
          confirmation: null
        },
        {
          id: assistantId,
          role: 'assistant',
          content: '',
          citations: [],
          trace: [],
          pending: true,
          error: null,
          confirmation: null
        }
      ])
      try {
        let conversationId = selectConversationId(useOrbStore.getState(), projectId)
        if (!conversationId) {
          conversationId = (await createSolConversation(projectId)).id
          useOrbStore.getState().setConversation(projectId, conversationId)
        }
        const controller = new AbortController()
        abortRef.current = controller
        await streamSolMessage({
          projectId,
          conversationId,
          content: text,
          actionMode,
          signal: controller.signal,
          onEvent: (event) => applyEvent(patch, event)
        })
      } catch {
        // Transport failure: a local, author-safe note — never the raw error.
        patch((m) => ({ ...m, pending: false, error: 'SOL is unreachable right now.' }))
      } finally {
        abortRef.current = null
        sendingRef.current = false
        useOrbStore.getState().setStreaming(false)
      }
    },
    [projectId]
  )

  const decide = useCallback(
    async (confirmationId: string, decision: 'approve' | 'reject'): Promise<void> => {
      if (!projectId) return
      // Clear ONLY on success — that is ConfirmationCard's contract: it owns the
      // failure state, showing the server's own reason ("expired", "already
      // decided", "what this would do has changed") and staying mounted, because
      // the action really is still waiting. Clearing optimistically would strand
      // a parked action the user can no longer approve. Errors therefore
      // propagate rather than being swallowed here. Double-submit is already
      // impossible: the card disables both buttons while this promise is live.
      await decideSolConfirmation(projectId, confirmationId, decision)
      setItems((prev) =>
        prev.map((m) =>
          m.confirmation?.confirmationId === confirmationId ? { ...m, confirmation: null } : m
        )
      )
    },
    [projectId]
  )

  return { items, status, streaming, send, decide }
}
