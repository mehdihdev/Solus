// SOLUSDEV-233: SOL chat sessions OUTLIVE the page. Live transcript state
// lives HERE (per project), so navigating away neither aborts the stream nor
// loses the turn — the page re-attaches on return, and a reply that finishes
// while the user is elsewhere raises the shell toast.
//
// SEC-H3 evolution, deliberate: unmount-abort was the original no-orphaned-
// streams control; ownership by this singleton is its successor. Every stream
// is still held by exactly one AbortController, bounded to one live turn per
// project PER RENDERER (the detached orb window is its own process) and
// MAX_CONCURRENT_TURNS across projects, capped per turn (MAX_TURN_CHARS), and
// torn down on identity change (sign-out OR account switch) and on explicit
// chat switches. Runtime-only — never persisted.
import { create } from 'zustand'
import { useAuthStore } from '../../store/authStore'
import { useShellStore } from '../workspace/shellStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ApiError } from '../../lib/api/envelope.types'
import { decideSolConfirmation } from '../../lib/api/resources'
import {
  createSolConversation,
  listSolTurns,
  streamSolMessage,
  type SolActionMode,
  type SolTurn
} from './solApi'
import type { ContextUsedInfo, SolStreamEvent } from './solStream'
import type { PendingConfirmation } from '../../lib/api/solStream'
import {
  purgeAllCachedChats,
  readCachedChat,
  removeCachedChat as removeCachedChatFile,
  writeCachedChat
} from './solCache'
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
  /** CTR-03: every action this turn parked, in the order they were proposed.
   *  A LIST since SOLUSDEV-168: the turn no longer ends at the first parked
   *  call, so one message can park several. Overwriting a single slot would
   *  silently drop every card but the last — and a dropped card is a
   *  destructive action the user can neither approve nor reject. */
  confirmations: readonly PendingConfirmation[]
}

export type ChatStatus = 'loading' | 'ready' | 'offline'

export interface SolSession {
  /** Which conversation the transcript belongs to; null = fresh chat. */
  conversationId: string | null
  items: readonly ChatItem[]
  contextUsed: ContextUsedInfo | null
  creditsExhausted: boolean
  streaming: boolean
  status: ChatStatus
}

export const EMPTY_SESSION: SolSession = {
  conversationId: null,
  items: [],
  contextUsed: null,
  creditsExhausted: false,
  streaming: false,
  status: 'ready'
}

interface SolChatState {
  sessions: Readonly<Record<string, SolSession>>
}

export const useSolChatStore = create<SolChatState>()(() => ({ sessions: {} }))

/** The session for a project (EMPTY_SESSION when none exists yet). */
export const selectSession = (s: SolChatState, projectId: string | null): SolSession =>
  (projectId ? s.sessions[projectId] : undefined) ?? EMPTY_SESSION

// ---- module-held runtime (non-serializable; never enters the store) --------
const controllers = new Map<string, AbortController>()
const turnTokens = new Map<string, object>()

/** Per-turn rendered-content ceiling (SEC-H3). Far above any real reply. */
export const MAX_TURN_CHARS = 200_000
/** Client-side ceiling on concurrent background turns across projects — the
 *  server's frequency cap and budgets still gate each one (ADR-019). */
export const MAX_CONCURRENT_TURNS = 3
/** New-conversation titles are seeded from the first message (SOLUSDEV-233). */
const TITLE_SEED_CHARS = 60

let itemSeq = 0
const nextItemId = (): string => `local-${++itemSeq}`

function patchSession(projectId: string, fn: (session: SolSession) => SolSession): void {
  useSolChatStore.setState((state) => ({
    sessions: {
      ...state.sessions,
      [projectId]: fn(state.sessions[projectId] ?? EMPTY_SESSION)
    }
  }))
}

/** The orb pulses while ANY project's turn streams (one turn per project). */
function refreshOrbPulse(): void {
  const anyStreaming = Object.values(useSolChatStore.getState().sessions).some(
    (session) => session.streaming
  )
  useOrbStore.getState().setStreaming(anyStreaming)
}

function cancelLiveTurn(projectId: string): void {
  turnTokens.delete(projectId)
  controllers.get(projectId)?.abort()
  controllers.delete(projectId)
  patchSession(projectId, (session) => ({ ...session, streaming: false }))
  refreshOrbPulse()
}

/** Sign-out teardown (SEC-M4 idiom): abort every stream, drop every session. */
export function resetSolChatSessions(): void {
  for (const controller of controllers.values()) controller.abort()
  controllers.clear()
  turnTokens.clear()
  useSolChatStore.setState({ sessions: {} })
  refreshOrbPulse()
}

function turnToItem(turn: SolTurn): ChatItem {
  return {
    id: turn.id,
    role: turn.role,
    content: turn.content,
    citations: [],
    trace: [],
    pending: false,
    error: null,
    confirmations: []
  }
}

function blankItem(id: string, role: ChatItem['role'], content: string, pending = false): ChatItem {
  return { id, role, content, citations: [], trace: [], pending, error: null, confirmations: [] }
}

/** Author-safe failure text for a rejected/failed turn — never the raw error. */
function turnFailureText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 402) return "You're out of SOL credits — top up to keep going."
    if (error.status === 429) return 'Too many SOL turns right now — give it a few seconds.'
  }
  return 'SOL is unreachable right now.'
}

function applyEvent(
  patch: (fn: (item: ChatItem) => ChatItem) => void,
  event: SolStreamEvent
): void {
  switch (event.type) {
    case 'token':
      // SEC-H3: bound per-turn accumulation.
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
      // Append, never replace. The backend dedupes by concrete action, so a
      // re-proposal arrives as the SAME confirmationId rather than a duplicate
      // card — matching on the id here keeps that true in the UI.
      patch((m) =>
        m.confirmations.some((c) => c.confirmationId === event.pending.confirmationId)
          ? m
          : { ...m, confirmations: [...m.confirmations, event.pending] }
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

/** True when the user is looking at THIS project's SOL page right now. */
function userIsWatching(projectId: string): boolean {
  const onSolScreen = useShellStore.getState().lastMain === 'sol'
  const currentProject = useWorkspaceStore.getState().project?.id ?? null
  return onSolScreen && currentProject === projectId
}

/** A backgrounded reply finished (or failed): raise the shell toast. The View
 *  action is offered only when the workspace is still on the turn's project. */
function notifyAway(projectId: string, prompt: string, failed: boolean): void {
  if (userIsWatching(projectId)) return
  const sameProject = useWorkspaceStore.getState().project?.id === projectId
  useShellStore.getState().setToast({
    kind: failed ? 'warn' : 'ok',
    title: failed ? 'SOL turn failed' : 'SOL replied',
    // Another project's prompt is that project's business (SOLUSDEV-242): the
    // toast names the fact, not the text, when the user has moved on.
    body: sameProject
      ? `“${prompt.slice(0, 60)}${prompt.length > 60 ? '…' : ''}” — open SOL to read it.`
      : 'A turn finished in another project — switch back to read it.',
    ...(sameProject ? { action: 'View', screen: 'sol' as const } : {})
  })
}

/** Load history so the session matches the project's ACTIVE conversation.
 *  No-ops when it already does — including the id a send just created, which
 *  is what keeps a mid-send store write from reloading away the live turn. */
export async function syncSession(projectId: string): Promise<void> {
  const active = selectConversationId(useOrbStore.getState(), projectId)
  const session = selectSession(useSolChatStore.getState(), projectId)
  // Matching and healthy (or already loading) ⇒ nothing to do. Only a failed
  // load (offline) re-fetches, so remounts retry without double-fetching.
  if (session.conversationId === active && session.status !== 'offline') return
  if (active === null) {
    patchSession(projectId, () => ({ ...EMPTY_SESSION }))
    return
  }
  patchSession(projectId, (s) => ({
    ...EMPTY_SESSION,
    conversationId: active,
    streaming: s.streaming,
    status: 'loading'
  }))
  // Paint the ~/.solus cache first (SOLUSDEV-233): returning to a chat is
  // instant, and past chats stay readable offline. The server load below is
  // still the source of truth and replaces it.
  const cached = await readCachedChat(projectId, active)
  if (cached !== null && cached.length > 0) {
    patchSession(projectId, (s) =>
      s.conversationId === active && s.status === 'loading' && s.items.length === 0
        ? { ...s, items: cached }
        : s
    )
  }
  try {
    const turns = await listSolTurns(projectId, active)
    // Still the active conversation? A switch mid-fetch discards this load.
    if (selectConversationId(useOrbStore.getState(), projectId) !== active) return
    const loaded = [...turns].reverse().map(turnToItem)
    patchSession(projectId, (s) => ({
      ...s,
      // Merge, don't replace: a send may have appended local items while
      // history was in flight — loading must never wipe a live turn.
      items: [...loaded, ...s.items.filter((m) => m.id.startsWith('local-'))],
      status: 'ready'
    }))
    writeCachedChat(projectId, active, loaded)
  } catch (error: unknown) {
    if (selectConversationId(useOrbStore.getState(), projectId) !== active) return
    handleHistoryFailure(projectId, active, error)
  }
}

/** A failed history load. Refusals (401/403/404) outrank the cache — the
 *  server ANSWERED that this conversation is not (or is no longer) the
 *  caller's, so the painted items AND the file are dropped (SEC review H1).
 *  Only network/5xx keeps the cache readable. */
function handleHistoryFailure(projectId: string, conversationId: string, error: unknown): void {
  const refused =
    error instanceof ApiError &&
    (error.status === 401 || error.status === 403 || error.status === 404)
  if (!refused) {
    patchSession(projectId, (s) => ({
      ...s,
      status: s.items.length > 0 ? 'ready' : 'offline'
    }))
    return
  }
  removeCachedChatFile(projectId, conversationId)
  if (error.status === 404) {
    useOrbStore.getState().clearConversation(projectId)
    patchSession(projectId, () => ({ ...EMPTY_SESSION }))
  } else {
    patchSession(projectId, (s) => ({ ...s, items: [], status: 'offline' }))
  }
}

export function selectConversation(projectId: string, conversationId: string): void {
  cancelLiveTurn(projectId)
  useOrbStore.getState().setConversation(projectId, conversationId)
  void syncSession(projectId)
}

export function startNewChat(projectId: string): void {
  cancelLiveTurn(projectId)
  useOrbStore.getState().clearConversation(projectId)
  void syncSession(projectId)
}

export async function sendMessage(
  projectId: string,
  content: string,
  actionMode: SolActionMode,
  mentions: readonly string[] = []
): Promise<void> {
  const text = content.trim()
  if (!text || controllers.has(projectId)) return
  if (controllers.size >= MAX_CONCURRENT_TURNS) {
    patchSession(projectId, (s) => ({
      ...s,
      items: [
        ...s.items,
        {
          ...blankItem(nextItemId(), 'assistant', ''),
          error: 'Too many chats are running — wait for one to finish.'
        }
      ]
    }))
    return
  }
  const turnToken = {}
  turnTokens.set(projectId, turnToken)
  const assistantId = nextItemId()
  const patch = (fn: (item: ChatItem) => ChatItem): void =>
    patchSession(projectId, (s) => ({
      ...s,
      items: s.items.map((m) => (m.id === assistantId ? fn(m) : m))
    }))
  patchSession(projectId, (s) => ({
    ...s,
    creditsExhausted: false,
    streaming: true,
    items: [
      ...s.items,
      blankItem(nextItemId(), 'user', text),
      blankItem(assistantId, 'assistant', '', true)
    ]
  }))
  refreshOrbPulse()
  let failed = false
  try {
    let activeId = selectConversationId(useOrbStore.getState(), projectId)
    if (!activeId) {
      activeId = (await createSolConversation(projectId, text.slice(0, TITLE_SEED_CHARS))).id
      // Session first, store second: syncSession sees them equal and no-ops,
      // so the just-created id never reloads away the live turn.
      patchSession(projectId, (s) => ({ ...s, conversationId: activeId }))
      useOrbStore.getState().setConversation(projectId, activeId)
    } else {
      // Stamp the session so a later sync never mistakes this live transcript
      // for another conversation's.
      const stamped = activeId
      patchSession(projectId, (s) => ({ ...s, conversationId: stamped }))
    }
    const controller = new AbortController()
    controllers.set(projectId, controller)
    await streamSolMessage({
      projectId,
      conversationId: activeId,
      content: text,
      actionMode,
      mentions,
      signal: controller.signal,
      onEvent: (event) => {
        if (event.type === 'context_used') {
          patchSession(projectId, (s) => ({
            ...s,
            contextUsed: {
              sections: event.sections,
              truncated: event.truncated,
              dropped: event.dropped
            }
          }))
          return
        }
        // Mid-stream credit exhaustion arrives as an error FRAME, not a 402.
        if (event.type === 'error') {
          failed = true
          if (event.code === 'insufficient_credits') {
            patchSession(projectId, (s) => ({ ...s, creditsExhausted: true }))
          }
        }
        applyEvent(patch, event)
      }
    })
  } catch (error: unknown) {
    failed = true
    if (error instanceof ApiError && error.status === 402) {
      patchSession(projectId, (s) => ({ ...s, creditsExhausted: true }))
    }
    const note = turnFailureText(error)
    patch((m) => ({ ...m, pending: false, error: note }))
  } finally {
    // Only the send that still owns the turn cleans up — a cancelled turn
    // settling late must not clobber a newer send's state.
    if (turnTokens.get(projectId) === turnToken) settleTurn(projectId, text, failed)
  }
}

/** End-of-turn bookkeeping for the send that still owns the turn: release the
 *  controller, stop the pulse, mirror the settled transcript to the ~/.solus
 *  cache, and raise the away toast when nobody was watching. */
function settleTurn(projectId: string, prompt: string, failed: boolean): void {
  turnTokens.delete(projectId)
  controllers.delete(projectId)
  patchSession(projectId, (s) => ({ ...s, streaming: false }))
  refreshOrbPulse()
  const session = selectSession(useSolChatStore.getState(), projectId)
  if (session.conversationId !== null) {
    writeCachedChat(projectId, session.conversationId, session.items)
  }
  notifyAway(projectId, prompt, failed)
}

export async function decideConfirmation(
  projectId: string,
  confirmationId: string,
  decision: 'approve' | 'reject'
): Promise<void> {
  // Clear ONLY on success — ConfirmationCard owns the failure state (CTR-03).
  await decideSolConfirmation(projectId, confirmationId, decision)
  patchSession(projectId, (s) => ({
    ...s,
    items: s.items.map((m) =>
      m.confirmations.some((c) => c.confirmationId === confirmationId)
        ? {
            ...m,
            confirmations: m.confirmations.filter((c) => c.confirmationId !== confirmationId)
          }
        : m
    )
  }))
}

// SEC-M4 / SEC review H1: sessions and the ~/.solus cache hold account data;
// ANY identity change — sign-out or an in-place session swap (OAuth loopback,
// magic link, another window) — must tear down streams, sessions, stored
// conversation ids, and the on-disk cache. Lane-owned subscription.
useAuthStore.subscribe((state, prev) => {
  if (prev.status !== 'authenticated') return
  const signedOut = state.status === 'unauthenticated'
  const identitySwapped = state.status === 'authenticated' && state.user?.email !== prev.user?.email
  if (signedOut || identitySwapped) {
    resetSolChatSessions()
    purgeAllCachedChats()
  }
})
