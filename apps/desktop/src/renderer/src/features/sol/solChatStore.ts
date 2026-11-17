// SOLUSDEV-233: SOL chat sessions OUTLIVE the page. Live transcript state
// lives HERE (per project), so navigating away neither aborts the stream nor
// loses the turn — the page re-attaches on return, and a reply that finishes
// while the user is elsewhere raises the shell toast.
//
// SEC-H3 evolution, deliberate: unmount-abort was the original no-orphaned-
// streams control; ownership by this singleton is its successor. Every stream
// is still held by exactly one AbortController, bounded to one live turn per
// project PER RENDERER (the SOL window is its own process) and
// MAX_CONCURRENT_TURNS across projects, capped per turn (MAX_TURN_CHARS), and
// torn down on identity change (sign-out OR account switch) and on explicit
// chat switches. Runtime-only — never persisted.
import { create } from 'zustand'
import { useAuthStore } from '../../store/authStore'
import { ApiError } from '../../lib/api/envelope.types'
import { addSolusEntry, decideSolConfirmation, type SolusSection } from '../../lib/api/resources'
import {
  createSolConversation,
  listSolTurns,
  listSolConfirmations,
  streamSolMessage,
  type SolActionMode,
  type SolScreenshot,
  type StreamSolMessageInput
} from './solApi'
import { preferencesForTurn } from '../preferences/preferencesStore'
import type { ContextUsedInfo, SolStreamEvent } from './solStream'
import type { PendingConfirmation } from '../../lib/api/solStream'
import type { ChatItem } from './solChat.types'
import {
  purgeAllCachedChats,
  readCachedChat,
  removeCachedChat as removeCachedChatFile,
  writeCachedChat
} from './solCache'
import { selectConversationId, useSolSessionStore } from './solSessionStore'
import { createTokenBatcher, type TokenBatcher } from './tokenBatcher'
import { commandExitStatus, hasCommandOutput, resumesAfterApproval } from './commandCard'
import { finalOutputOf } from './commandRuns'
import { createRunTracker, refusalStatus } from './commandRunTracker'
import { processIdOf, rememberProcessOwner, resetProcessOwners } from './processOwners'
import type { WakeStart } from './processWake'
import { attachResearchSources } from './researchSources'
import { addThought } from './thinking'
import { foldToolTurns } from './historyFold'
import { applyContextUsed } from './contextUsed'
import { notifyAway } from './solAway'
import {
  MAX_TURN_CHARS,
  appendContent,
  applyEvent,
  applyReasoningFrame,
  blankItem,
  decidedContent,
  decidedTrace,
  markParked,
  turnFailureText,
  withRestored,
  type Patch
} from './solChatItems'

export type { ChatArtifact, ChatItem, TraceEntry } from './solChat.types'

export type ChatStatus = 'loading' | 'ready' | 'offline'

export interface SolSession {
  /** Explicit review choice for this mounted conversation session; never persisted. */
  forceConfirmation?: boolean
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
// S2-A: token text coalesces here and lands as ONE store commit per frame.
const batchers = new Map<string, TokenBatcher>()

export { MAX_TURN_CHARS }
/** Client-side ceiling on concurrent background turns across projects — the
 *  server's frequency cap and budgets still gate each one (ADR-019). */
export const MAX_CONCURRENT_TURNS = 3
/** New-conversation titles are seeded from the first message (SOLUSDEV-233). */
const TITLE_SEED_CHARS = 60

let itemSeq = 0
let identityGeneration = 0
const decidedApprovals = new Set<string>()
const nextItemId = (): string => `local-${++itemSeq}`

export function patchSession(projectId: string, fn: (session: SolSession) => SolSession): void {
  useSolChatStore.setState((state) => ({
    sessions: {
      ...state.sessions,
      [projectId]: fn(state.sessions[projectId] ?? EMPTY_SESSION)
    }
  }))
}

// SOLUSDEV-317: approved commands' output pollers (runtime only).
const runs = createRunTracker((projectId, fn) =>
  patchSession(projectId, (session) => ({ ...session, items: fn(session.items) }))
)

export function setForceConfirmation(projectId: string, forceConfirmation: boolean): void {
  patchSession(projectId, (session) => ({ ...session, forceConfirmation }))
}

/** The session streams while ANY project's turn streams (one turn per project). */
function refreshStreaming(): void {
  const anyStreaming = Object.values(useSolChatStore.getState().sessions).some(
    (session) => session.streaming
  )
  useSolSessionStore.getState().setStreaming(anyStreaming)
}

/** Test-visible: land buffered token text now instead of on the next frame. */
export function flushPendingTokens(projectId: string): void {
  batchers.get(projectId)?.flushNow()
}

export function cancelLiveTurn(projectId: string): void {
  turnTokens.delete(projectId)
  controllers.get(projectId)?.abort()
  controllers.delete(projectId)
  batchers.get(projectId)?.dispose()
  batchers.delete(projectId)
  patchSession(projectId, (session) => ({ ...session, streaming: false }))
  refreshStreaming()
}

/** Sign-out teardown (SEC-M4 idiom): abort every stream, drop every session. */
export function resetSolChatSessions(): void {
  identityGeneration += 1
  decidedApprovals.clear()
  for (const controller of controllers.values()) controller.abort()
  for (const batcher of batchers.values()) batcher.dispose()
  runs.stopAll()
  resetProcessOwners()
  controllers.clear()
  batchers.clear()
  turnTokens.clear()
  useSolChatStore.setState({ sessions: {} })
  refreshStreaming()
}

/** Load history so the session matches the project's ACTIVE conversation.
 *  No-ops when it already does — including the id a send just created, which
 *  is what keeps a mid-send store write from reloading away the live turn. */
export async function syncSession(projectId: string): Promise<void> {
  const active = selectConversationId(useSolSessionStore.getState(), projectId)
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
    forceConfirmation: s.conversationId === active && s.forceConfirmation === true,
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
    const [turns, approvals] = await Promise.all([
      listSolTurns(projectId, active),
      listSolConfirmations(projectId, active)
    ])
    // Still the active conversation? A switch mid-fetch discards this load.
    if (selectConversationId(useSolSessionStore.getState(), projectId) !== active) return
    // SOLUSDEV-326: each reply's stored tool rows fold into its steps, as the live turn showed.
    const loaded = foldToolTurns([...turns].reverse())
    patchSession(projectId, (s) => ({
      ...s,
      // Merge, don't replace: a send may have appended local items while
      // history was in flight — loading must never wipe a live turn.
      items: withRestored(loaded, s.items, active, approvals, (id) =>
        decidedApprovals.has(`${projectId}:${id}`)
      ),
      status: 'ready'
    }))
    writeCachedChat(projectId, active, loaded)
  } catch (error: unknown) {
    if (selectConversationId(useSolSessionStore.getState(), projectId) !== active) return
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
    useSolSessionStore.getState().clearConversation(projectId)
    patchSession(projectId, () => ({ ...EMPTY_SESSION }))
  } else {
    patchSession(projectId, (s) => ({ ...s, items: [], status: 'offline' }))
  }
}

export function selectConversation(projectId: string, conversationId: string): void {
  cancelLiveTurn(projectId)
  useSolSessionStore.getState().setConversation(projectId, conversationId)
  void syncSession(projectId)
}

export function startNewChat(projectId: string): void {
  cancelLiveTurn(projectId)
  useSolSessionStore.getState().clearConversation(projectId)
  void syncSession(projectId)
}

function confirmationOptions(options?: { forceConfirmation?: boolean }): {
  forceConfirmation?: true
} {
  return options?.forceConfirmation === true ? { forceConfirmation: true } : {}
}

/** What a send may carry beside its text: the Confirm-every-change choice and — from the SOL
 *  page only — the anchors that say where the person is looking (`StreamSolMessageInput`). */
type SendAnchors = Pick<StreamSolMessageInput, 'focus' | 'pins' | 'findingId' | 'robotId'>
export interface SendOptions extends SendAnchors {
  forceConfirmation?: boolean
}

export async function sendMessage(
  projectId: string,
  content: string,
  actionMode: SolActionMode,
  mentions: readonly string[] = [],
  thinkHarder = false,
  screenshot?: SolScreenshot,
  options?: SendOptions
): Promise<boolean> {
  const text = content.trim()
  if (!text || !admitTurn(projectId)) return false
  const userItem = {
    ...blankItem(nextItemId(), 'user', text),
    ...(screenshot ? { hasScreenshot: true } : {})
  }
  // Everything but `forceConfirmation` is the turn's anchors: they pass straight through, and
  // `turnBody` leaves the unset ones off the wire.
  const { forceConfirmation, ...anchors } = options ?? {}
  return runTurn(projectId, text, userItem, {
    projectId,
    content: text,
    actionMode,
    mentions,
    thinkHarder,
    ...confirmationOptions({ forceConfirmation }),
    ...anchors,
    // The circled region rides THIS send only (sol-window.md §8); the caller
    // drops it from memory once handed over.
    ...(screenshot ? { screenshot } : {})
  })
}

const isStreaming = (projectId: string): boolean =>
  selectSession(useSolChatStore.getState(), projectId).streaming

/** Resolves once no turn is live in the project.
 *  ponytail: no timeout — a live turn always settles (its stream ends or it is cancelled). */
function turnSettled(projectId: string): Promise<void> {
  if (!isStreaming(projectId)) return Promise.resolve()
  return new Promise((resolve) => {
    const stop = useSolChatStore.subscribe(() => {
      if (isStreaming(projectId)) return
      stop()
      resolve()
    })
  })
}

/** Make `conversationId` the project's open conversation (no-op when it already is). Only ever
 *  called with no turn live (`afterLiveTurn`), so there is nothing to cancel. */
async function enterConversation(
  projectId: string,
  conversationId: string | undefined
): Promise<void> {
  const sessions = useSolSessionStore.getState()
  if (!conversationId || selectConversationId(sessions, projectId) === conversationId) return
  sessions.setConversation(projectId, conversationId)
  await syncSession(projectId)
}

/** Start a turn once no other is live, in `conversationId` when given. A card is pressed, and a
 *  device announced, while SOL may still be replying: the live turn is left to finish (never
 *  cancelled) and the new one waits. Every waiter wakes on the same settle, so each checks again
 *  after every await; `start` must claim the turn before its own first await (`runTurn` does),
 *  which sends the others back to waiting. A sign-out or account switch settles every turn too:
 *  what was queued for the old identity never starts, and resolves `dropped`. */
export async function afterLiveTurn<T>(
  projectId: string,
  conversationId: string | undefined,
  start: () => Promise<T>,
  dropped: T
): Promise<T> {
  const generation = identityGeneration
  for (;;) {
    await turnSettled(projectId)
    if (generation !== identityGeneration) return dropped
    await enterConversation(projectId, conversationId)
    if (generation !== identityGeneration) return dropped
    if (!isStreaming(projectId)) return start()
  }
}

/** SOLUSDEV-317 (§5.5): after an approved command card, continue SOL's turn so
 *  it reads the result. No user bubble; same streaming path and admission. */
const RESUME_PAUSED = 'SOL paused — reply to continue'
const RESUME_PROMPT = 'your approved command'

/** Waits its turn behind a live one (`afterLiveTurn`): a card decided while SOL is replying still
 *  resumes, once, after that reply. With `conversationId` (a card decided outside the thread) it
 *  opens that conversation first; without, it goes only in the conversation it was decided in —
 *  the person opening another chat meanwhile drops it. `forceConfirmation` given (the Hardware
 *  surface, SOLUSDEV-326) overrides the session's choice. */
export function resumeTurn(
  projectId: string,
  confirmationId: string,
  actionMode: SolActionMode,
  forceConfirmation?: boolean,
  conversationId?: string
): Promise<void> {
  const decidedIn = selectSession(useSolChatStore.getState(), projectId).conversationId
  const start = async (): Promise<void> => {
    const session = selectSession(useSolChatStore.getState(), projectId)
    if (session.conversationId === null) return
    if (!conversationId && session.conversationId !== decidedIn) return
    if (!admitTurn(projectId)) return
    await runTurn(projectId, RESUME_PROMPT, null, {
      projectId,
      content: '',
      actionMode,
      resumeConfirmationId: confirmationId,
      ...confirmationOptions({ forceConfirmation: forceConfirmation ?? session.forceConfirmation })
    })
  }
  return afterLiveTurn(projectId, conversationId, start, undefined)
}

/** SOLUSDEV-317 §11.3: an interactive process SOL started is asking for input.
 *  Continue SOL in the conversation that started it — no user bubble, the same
 *  streaming path as a resume. Never while a turn streams, never into another
 *  conversation than the one open in this project's session. */
export function wakeTurn(
  projectId: string,
  conversationId: string,
  processPrompt: NonNullable<TurnInput['processPrompt']>,
  actionMode: SolActionMode
): WakeStart {
  const session = selectSession(useSolChatStore.getState(), projectId)
  if (session.conversationId !== conversationId) return 'elsewhere'
  if (session.streaming || controllers.has(projectId)) return 'busy'
  if (controllers.size >= MAX_CONCURRENT_TURNS) return 'busy'
  void runTurn(projectId, WAKE_PROMPT, null, {
    projectId,
    content: '',
    actionMode,
    processPrompt,
    ...confirmationOptions({ forceConfirmation: session.forceConfirmation })
  })
  return 'started'
}

const WAKE_PROMPT = 'a waiting process'

type TurnInput = Omit<
  Parameters<typeof streamSolMessage>[0],
  'conversationId' | 'onEvent' | 'signal' | 'preferences'
>

/** One streamed turn: optional user bubble, a pending assistant item, the
 *  stream, and end-of-turn bookkeeping. Shared by sends and resumes. */
export async function runTurn(
  projectId: string,
  prompt: string,
  userItem: ChatItem | null,
  input: TurnInput
): Promise<boolean> {
  const turnToken = {}
  turnTokens.set(projectId, turnToken)
  const assistantId = nextItemId()
  const patch = assistantPatch(projectId, assistantId)
  const batcher = createTokenBatcher(
    (text) => appendContent(patch, text),
    undefined,
    MAX_TURN_CHARS
  )
  patchSession(projectId, (s) => ({
    ...s,
    creditsExhausted: false,
    streaming: true,
    items: [
      ...s.items,
      ...(userItem ? [userItem] : []),
      blankItem(assistantId, 'assistant', '', true)
    ]
  }))
  refreshStreaming()
  let failed = false
  try {
    const activeId = await resolveConversationId(projectId, prompt)
    const controller = new AbortController()
    controllers.set(projectId, controller)
    batchers.set(projectId, batcher)
    await streamSolMessage({
      ...input,
      conversationId: activeId,
      // SOLUSDEV-244: the user's engineering conventions ride along with every
      // turn (null when nothing is written or outside the desktop app).
      preferences: await preferencesForTurn(),
      signal: controller.signal,
      onEvent: (event) => {
        if (handleTurnEvent(projectId, patch, batcher, event)) failed = true
      }
    })
  } catch (error: unknown) {
    failed = !resumeRefusal(projectId, assistantId, patch, error, input.notice !== undefined)
    if (failed) failTurn(projectId, patch, batcher, error)
  } finally {
    // Text still buffered when the stream ends lands before the turn settles
    // (a cancelled turn's batcher is already disposed, so this is inert).
    batcher.flushNow()
    if (batchers.get(projectId) === batcher) batchers.delete(projectId)
    // Only the send that still owns the turn cleans up — a cancelled turn
    // settling late must not clobber a newer send's state.
    if (turnTokens.get(projectId) === turnToken) settleTurn(projectId, prompt, failed)
  }
  return !failed
}

/** Someone else's continuation, or (SOLUSDEV-326) a device announced twice inside two seconds. */
const SILENT_REFUSALS: ReadonlySet<string> = new Set([
  'already_resumed',
  'already_woken',
  'notice_debounced'
])

/** A resume, wake or notice the server declined on purpose (§5.5, §11.2): `resume_limit` pauses
 *  SOL until the person replies; the silent ones and a notice's 422 (its device is gone) vanish. */
function resumeRefusal(
  projectId: string,
  assistantId: string,
  patch: Patch,
  error: unknown,
  notice = false
): boolean {
  if (!(error instanceof ApiError)) return false
  const gone = notice && error.status === 422
  if (!gone && error.status !== 409) return false
  if (error.code === 'resume_limit') {
    patch((m) => ({ ...m, pending: false, content: RESUME_PAUSED }))
    return true
  }
  if (!gone && !SILENT_REFUSALS.has(error.code)) return false
  patchSession(projectId, (s) => ({ ...s, items: s.items.filter((m) => m.id !== assistantId) }))
  return true
}

/** One live turn per project, MAX_CONCURRENT_TURNS overall; the refusal is
 *  painted into the transcript, never thrown. */
export function admitTurn(projectId: string): boolean {
  // The token is claimed before a turn's first await, the controller only after its conversation
  // is known: both, so a second turn in that gap is refused too (SOLUSDEV-326).
  if (controllers.has(projectId) || turnTokens.has(projectId)) return false
  if (controllers.size < MAX_CONCURRENT_TURNS) return true
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
  return false
}

/** The conversation this turn posts to, created on a first send. Session first,
 *  store second: syncSession sees them equal and no-ops, so the just-created id
 *  never reloads away the live turn; an existing id is stamped so a later sync
 *  never mistakes this live transcript for another conversation's. */
async function resolveConversationId(projectId: string, text: string): Promise<string> {
  const existing = selectConversationId(useSolSessionStore.getState(), projectId)
  const activeId =
    existing ?? (await createSolConversation(projectId, text.slice(0, TITLE_SEED_CHARS))).id
  patchSession(projectId, (s) => ({ ...s, conversationId: activeId }))
  if (!existing) useSolSessionStore.getState().setConversation(projectId, activeId)
  return activeId
}

/** A transport/HTTP failure: 402 flips the top-up card; the note lands after
 *  whatever prose already streamed. */
function failTurn(projectId: string, patch: Patch, batcher: TokenBatcher, error: unknown): void {
  if (error instanceof ApiError && error.status === 402) {
    patchSession(projectId, (s) => ({ ...s, creditsExhausted: true }))
  }
  const note = turnFailureText(error)
  batcher.flushNow()
  patch((m) => ({ ...m, pending: false, error: note }))
}

/** End-of-turn bookkeeping for the send that still owns the turn: release the
 *  controller, stop the pulse, mirror the settled transcript to the ~/.solus
 *  cache, and raise the away toast when nobody was watching. */
function settleTurn(projectId: string, prompt: string, failed: boolean): void {
  turnTokens.delete(projectId)
  controllers.delete(projectId)
  patchSession(projectId, (s) => ({ ...s, streaming: false }))
  refreshStreaming()
  const session = selectSession(useSolChatStore.getState(), projectId)
  if (session.conversationId !== null) {
    writeCachedChat(projectId, session.conversationId, session.items)
  }
  notifyAway(projectId, prompt, failed)
}

/** Drop the decided card from whichever message carries it. `null` is a refusal: the card goes
 *  with no word of a decision, and a restored approvals item it was the last row of goes too. */
function markDecided(
  projectId: string,
  confirmationId: string,
  decision: 'approve' | 'reject' | null
): void {
  decidedApprovals.add(`${projectId}:${confirmationId}`)
  patchSession(projectId, (s) => ({
    ...s,
    items: s.items.flatMap((m) => {
      if (!m.confirmations.some((c) => c.confirmationId === confirmationId)) return [m]
      const confirmations = m.confirmations.filter((c) => c.confirmationId !== confirmationId)
      if (decision) {
        const trace = decidedTrace(m.trace, confirmationId, decision)
        return [
          { ...m, content: decidedContent(m, confirmationId, decision), trace, confirmations }
        ]
      }
      return m.id.startsWith('approvals-') && !confirmations.length ? [] : [{ ...m, confirmations }]
    })
  }))
}

/** SOLUSDEV-326: a card decided outside the thread (the Hardware page's slot posts the decision
 *  itself): its row leaves the thread as one decided here does, and no history load restores it. */
export const cardDecided: typeof markDecided = (...decided) => markDecided(...decided)

/** POST the decision, closing the tracked command run with its exit status or
 *  its refusal. Rethrows so ConfirmationCard owns the failure state. */
async function postDecision(
  projectId: string,
  confirmationId: string,
  decision: 'approve' | 'reject',
  tracked: boolean,
  generation: number
): Promise<Awaited<ReturnType<typeof decideSolConfirmation>> | null> {
  try {
    const outcome = await decideSolConfirmation(projectId, confirmationId, decision)
    if (generation !== identityGeneration) return null
    if (tracked) {
      runs.end(projectId, confirmationId, commandExitStatus(outcome), finalOutputOf(outcome.value))
    }
    return outcome
  } catch (error: unknown) {
    if (tracked && generation === identityGeneration) {
      runs.end(projectId, confirmationId, refusalStatus(error))
    }
    throw error
  }
}

/** `postDecision` for a row that may carry a card. Refused (stale, expired, already decided) is
 *  the server's final word on a `resumes` card too, so SOL continues. By name, as
 *  ConfirmationCard reads it: the class crosses a module boundary. */
async function postCardDecision(
  pending: PendingConfirmation | null,
  resume: () => void,
  ...args: Parameters<typeof postDecision>
): ReturnType<typeof postDecision> {
  return postDecision(...args).catch((error: unknown) => {
    const refused = error instanceof Error && error.name === 'ConfirmationRefused'
    if (pending?.card?.resumes && refused) resume()
    throw error
  })
}

/** SOLUSDEV-317 §5.5 / SOLUSDEV-326: after ANY outcome of a card the server marked `resumes`, and
 *  after an approved command; never after a rejected one, nor a row that is neither. */
function shouldResume(pending: PendingConfirmation | null, approving: boolean): boolean {
  if (pending?.card?.resumes) return true
  return approving && pending !== null && resumesAfterApproval(pending.tool)
}

export async function decideConfirmation(
  projectId: string,
  confirmationId: string,
  decision: 'approve' | 'reject',
  options?: { actionMode?: SolActionMode; forceConfirmation?: boolean }
): Promise<void> {
  // Clear ONLY on success — ConfirmationCard owns the failure state (CTR-03).
  const generation = identityGeneration
  const pending = findConfirmation(projectId, confirmationId)
  const tool = pending?.tool ?? null
  const approving = decision === 'approve' && tool !== null
  const tracked = approving && hasCommandOutput(tool)
  const resume = (): void => {
    if (options?.actionMode) {
      void resumeTurn(projectId, confirmationId, options.actionMode, options.forceConfirmation)
    }
  }
  if (tracked) runs.begin(projectId, confirmationId, tool)
  const args = [projectId, confirmationId, decision, tracked, generation] as const
  const outcome = await postCardDecision(pending, resume, ...args)
  if (outcome === null) return
  markDecided(projectId, confirmationId, decision)
  if (approving && tool === 'code.process_start') recordProcessOwner(projectId, outcome.value)
  if (shouldResume(pending, approving)) resume()
}

/** §11.3: remember which conversation started this process, for its wakes. */
function recordProcessOwner(
  projectId: string,
  value: Readonly<Record<string, unknown>> | null | undefined
): void {
  const processId = processIdOf(value)
  const conversationId = selectSession(useSolChatStore.getState(), projectId).conversationId
  if (processId !== null && conversationId !== null) {
    rememberProcessOwner(projectId, processId, conversationId)
  }
}

function findConfirmation(projectId: string, confirmationId: string): PendingConfirmation | null {
  for (const item of selectSession(useSolChatStore.getState(), projectId).items) {
    const found = item.confirmations.find((c) => c.confirmationId === confirmationId)
    if (found) return found
  }
  return null
}

/** SOLUSDEV-252 S5: file a turn's artifact into a `.solus` section. Idempotent —
 *  an already-filed (or unknown) artifact posts nothing. Failure rethrows so the
 *  card shows the API's own reason; the store marks filed ONLY on success. */
export async function fileArtifact(
  projectId: string,
  artifactId: string,
  section: SolusSection
): Promise<void> {
  const artifact = selectSession(useSolChatStore.getState(), projectId)
    .items.flatMap((m) => m.artifacts ?? [])
    .find((a) => a.artifactId === artifactId)
  if (!artifact || artifact.filedTo !== null) return
  await addSolusEntry(projectId, section, {
    kind: 'artifact',
    artifact_id: artifactId,
    name: artifact.title
  })
  patchSession(projectId, (s) => ({
    ...s,
    items: s.items.map((m) =>
      m.artifacts
        ? {
            ...m,
            artifacts: m.artifacts.map((a) =>
              a.artifactId === artifactId ? { ...a, filedTo: section } : a
            )
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

function assistantPatch(projectId: string, assistantId: string): Patch {
  return (fn) =>
    patchSession(projectId, (s) => {
      // The live assistant item is always the LAST item while its turn streams
      // (nothing appends behind it); patch by index and fall back to the scan.
      const last = s.items.length - 1
      if (s.items[last]?.id !== assistantId) {
        return { ...s, items: s.items.map((m) => (m.id === assistantId ? fn(m) : m)) }
      }
      const items = s.items.slice()
      items[last] = fn(s.items[last])
      return { ...s, items }
    })
}

function handleTurnEvent(
  projectId: string,
  patch: Patch,
  batcher: ReturnType<typeof createTokenBatcher>,
  event: SolStreamEvent
): boolean {
  markParked(patch, event)
  if (
    event.type === 'tool_confirmation' &&
    (decidedApprovals.has(`${projectId}:${event.pending.confirmationId}`) ||
      selectSession(useSolChatStore.getState(), projectId).items.some((m) =>
        m.confirmations.some((c) => c.confirmationId === event.pending.confirmationId)
      ))
  )
    return false
  if (event.type === 'token') {
    batcher.push(event.text)
    return false
  }
  // Every other frame lands AFTER the prose it follows.
  batcher.flushNow()
  if (event.type === 'context_used') {
    applyContextUsed(patchSession, projectId, event)
    return false
  }
  if (event.type === 'research_sources') {
    attachResearchSources(patch, event.research)
    return false
  }
  if (event.type === 'thinking') {
    const now = Date.now()
    patch((item) => addThought(item, event.text, now))
    return false
  }
  // Mid-stream credit exhaustion arrives as an error FRAME, not a 402.
  if (event.type === 'error' && event.code === 'insufficient_credits') {
    patchSession(projectId, (s) => ({ ...s, creditsExhausted: true }))
  }
  applyEvent(patch, event)
  applyReasoningFrame(patch, event)
  return event.type === 'error'
}
