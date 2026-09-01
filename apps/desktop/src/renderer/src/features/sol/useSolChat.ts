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
import type { ContextUsedInfo, SolStreamEvent } from './solStream'
import { decideSolConfirmation } from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
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
  /** SOLUSDEV-233: the latest turn's context manifest (labels only). */
  contextUsed: ContextUsedInfo | null
  /** True after a 402 turn rejection — drives the top-up card. */
  creditsExhausted: boolean
  activeConversationId: string | null
  send: (content: string, actionMode: SolActionMode) => Promise<void>
  /** Switch to another owned conversation (cancels any live turn first). */
  selectConversation: (conversationId: string) => void
  /** Forget the active conversation so the next send starts a fresh chat. */
  startNewChat: () => void
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

/** New-conversation titles are seeded from the first message (SOLUSDEV-233). */
const TITLE_SEED_CHARS = 60

/** Author-safe failure text for a rejected/failed turn — never the raw error. */
function turnFailureText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 402) return "You're out of SOL credits — top up to keep going."
    if (error.status === 429) return 'Too many SOL turns right now — give it a few seconds.'
  }
  return 'SOL is unreachable right now.'
}

function blankItem(id: string, role: ChatItem['role'], content: string, pending = false): ChatItem {
  return { id, role, content, citations: [], trace: [], pending, error: null, confirmation: null }
}

export function useSolChat(projectId: string | null): SolChat {
  const [items, setItems] = useState<ChatItem[]>([])
  const [status, setStatus] = useState<ChatStatus>('ready')
  const [contextUsed, setContextUsed] = useState<ContextUsedInfo | null>(null)
  const [creditsExhausted, setCreditsExhausted] = useState(false)
  const streaming = useOrbStore((s) => s.streaming)
  // Subscribed (not read once): the chats sidebar switches conversations by
  // writing this store, and the transcript must follow (SOLUSDEV-233).
  const conversationId = useOrbStore((s) => selectConversationId(s, projectId))
  const sendingRef = useRef(false)
  //#: SEC-H3: the in-flight stream, so unmount and project switches cancel it
  //  rather than leaving a read running (and the composer wedged).
  const abortRef = useRef<AbortController | null>(null)
  //#: The conversation id this hook just created mid-send. Its store write
  //  re-fires the history effect, which must NOT reload (and wipe) the live turn.
  const skipReloadRef = useRef<string | null>(null)

  const cancelLiveTurn = useCallback((): void => {
    abortRef.current?.abort()
    abortRef.current = null
    sendingRef.current = false
    useOrbStore.getState().setStreaming(false)
  }, [])

  // Unmount / project switch cancels any live turn: its tokens belong to a
  // chat we are no longer showing. Conversation switches cancel through
  // selectConversation/startNewChat instead, so a mid-send conversation
  // creation never aborts its own stream.
  useEffect(() => cancelLiveTurn, [projectId, cancelLiveTurn])

  useEffect(() => {
    if (skipReloadRef.current !== null && skipReloadRef.current === conversationId) {
      skipReloadRef.current = null
      return
    }
    setItems([])
    setContextUsed(null)
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
    }
  }, [projectId, conversationId])

  const selectConversation = useCallback(
    (id: string): void => {
      if (!projectId) return
      cancelLiveTurn()
      useOrbStore.getState().setConversation(projectId, id)
    },
    [projectId, cancelLiveTurn]
  )

  const startNewChat = useCallback((): void => {
    if (!projectId) return
    cancelLiveTurn()
    useOrbStore.getState().clearConversation(projectId)
  }, [projectId, cancelLiveTurn])

  const send = useCallback(
    async (content: string, actionMode: SolActionMode): Promise<void> => {
      const text = content.trim()
      if (!text || !projectId || sendingRef.current) return
      sendingRef.current = true
      setCreditsExhausted(false)
      useOrbStore.getState().setStreaming(true)
      const assistantId = nextItemId()
      const patch: Patch = (fn) =>
        setItems((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)))
      setItems((prev) => [
        ...prev,
        blankItem(nextItemId(), 'user', text),
        blankItem(assistantId, 'assistant', '', true)
      ])
      try {
        let activeId = selectConversationId(useOrbStore.getState(), projectId)
        if (!activeId) {
          activeId = (await createSolConversation(projectId, text.slice(0, TITLE_SEED_CHARS))).id
          skipReloadRef.current = activeId
          useOrbStore.getState().setConversation(projectId, activeId)
        }
        const controller = new AbortController()
        abortRef.current = controller
        await streamSolMessage({
          projectId,
          conversationId: activeId,
          content: text,
          actionMode,
          signal: controller.signal,
          onEvent: (event) => {
            if (event.type === 'context_used') {
              setContextUsed({
                sections: event.sections,
                truncated: event.truncated,
                dropped: event.dropped
              })
              return
            }
            applyEvent(patch, event)
          }
        })
      } catch (error: unknown) {
        // Turn rejection or transport failure: an author-safe note — never the
        // raw error. A 402 additionally lights the top-up card (SOLUSDEV-233).
        if (error instanceof ApiError && error.status === 402) setCreditsExhausted(true)
        const note = turnFailureText(error)
        patch((m) => ({ ...m, pending: false, error: note }))
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

  return {
    items,
    status,
    streaming,
    contextUsed,
    creditsExhausted,
    activeConversationId: conversationId,
    send,
    selectConversation,
    startNewChat,
    decide
  }
}
