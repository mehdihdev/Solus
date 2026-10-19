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
import { useShellStore } from '../workspace/shellStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ApiError } from '../../lib/api/envelope.types'
import { addSolusEntry, decideSolConfirmation, type SolusSection } from '../../lib/api/resources'
import {
  createSolConversation,
  listSolTurns,
  listSolConfirmations,
  streamSolMessage,
  type SolActionMode,
  type SolScreenshot
} from './solApi'
import { preferencesForTurn } from '../preferences/preferencesStore'
import type { ContextUsedInfo, SolStreamEvent } from './solStream'
import type { AutoRun, PendingConfirmation, SolArtifact } from '../../lib/api/solStream'
import {
  purgeAllCachedChats,
  readCachedChat,
  removeCachedChat as removeCachedChatFile,
  writeCachedChat
} from './solCache'
import { selectConversationId, useSolSessionStore } from './solSessionStore'
import { createTokenBatcher, type TokenBatcher } from './tokenBatcher'
import { commandExitStatus, hasCommandOutput, isCommandTool } from './commandCard'
import { finalOutputOf, type CommandRun } from './commandRuns'
import { createRunTracker, refusalStatus } from './commandRunTracker'
import {
  MAX_TURN_CHARS,
  appendContent,
  applyEvent,
  blankItem,
  turnFailureText,
  turnToItem,
  type Patch
} from './solChatItems'

export interface TraceEntry {
  callId: string
  tool: string
  /** Null while the call is in flight. */
  ok: boolean | null
  errorCode: string | null
}

/** SOLUSDEV-252 S5: an artifact in the transcript plus where the user filed it.
 *  `filedTo` lives in the store, not the card, so a remount cannot file twice. */
export interface ChatArtifact extends SolArtifact {
  filedTo: SolusSection | null
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
  /** SOLUSDEV-252 S5: every artifact a tool produced this turn, in order.
   *  Optional (like hasScreenshot) so reloaded/cached items and fixtures built
   *  before S5 stay valid — absent reads as none. */
  artifacts?: readonly ChatArtifact[]
  /** SOLUSDEV-252 S3: this user turn carried a screen capture. A flag only —
   *  pixels live in memory for one send and never enter an item. */
  hasScreenshot?: boolean
  /** SOLUSDEV-317: approved commands' output, kept (bounded, plain text) with
   *  the exit status under this message until the conversation is closed.
   *  Runtime only — never cached (solCache keeps role + content). */
  commandRuns?: readonly CommandRun[]
  /** SOLUSDEV-317 §10.1: Build-mode commands that ran without a card, as
   *  compact rows. Runtime only, like commandRuns. */
  autoRuns?: readonly AutoRun[]
}

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

function patchSession(projectId: string, fn: (session: SolSession) => SolSession): void {
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

function cancelLiveTurn(projectId: string): void {
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
  controllers.clear()
  batchers.clear()
  turnTokens.clear()
  useSolChatStore.setState({ sessions: {} })
  refreshStreaming()
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
    const loaded = [...turns].reverse().map(turnToItem)
    patchSession(projectId, (s) => ({
      ...s,
      // Merge, don't replace: a send may have appended local items while
      // history was in flight — loading must never wipe a live turn.
      items: (() => {
        const local = s.items.filter((m) => m.id.startsWith('local-'))
        const liveIds = new Set(local.flatMap((m) => m.confirmations.map((c) => c.confirmationId)))
        const restored = approvals.filter(
          (c) =>
            !liveIds.has(c.confirmationId) &&
            !decidedApprovals.has(`${projectId}:${c.confirmationId}`)
        )
        return [
          ...loaded,
          ...(restored.length
            ? [
                {
                  id: `approvals-${active}`,
                  role: 'assistant' as const,
                  content: 'Awaiting your approval',
                  citations: [],
                  trace: [],
                  pending: false,
                  error: null,
                  confirmations: restored,
                  artifacts: []
                }
              ]
            : []),
          ...local
        ]
      })(),
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

export async function sendMessage(
  projectId: string,
  content: string,
  actionMode: SolActionMode,
  mentions: readonly string[] = [],
  thinkHarder = false,
  screenshot?: SolScreenshot,
  options?: { forceConfirmation?: boolean }
): Promise<boolean> {
  const text = content.trim()
  if (!text || !admitTurn(projectId)) return false
  const userItem = {
    ...blankItem(nextItemId(), 'user', text),
    ...(screenshot ? { hasScreenshot: true } : {})
  }
  return runTurn(projectId, text, userItem, {
    projectId,
    content: text,
    actionMode,
    mentions,
    thinkHarder,
    ...confirmationOptions(options),
    // The circled region rides THIS send only (sol-window.md §8); the caller
    // drops it from memory once handed over.
    ...(screenshot ? { screenshot } : {})
  })
}

/** SOLUSDEV-317 (§5.5): after an approved command card, continue SOL's turn so
 *  it reads the result. No user bubble; same streaming path and admission. */
const RESUME_PAUSED = 'SOL paused — reply to continue'
const RESUME_PROMPT = 'your approved command'

async function resumeTurn(
  projectId: string,
  confirmationId: string,
  actionMode: SolActionMode
): Promise<void> {
  const session = selectSession(useSolChatStore.getState(), projectId)
  if (session.conversationId === null || !admitTurn(projectId)) return
  await runTurn(projectId, RESUME_PROMPT, null, {
    projectId,
    content: '',
    actionMode,
    resumeConfirmationId: confirmationId,
    ...confirmationOptions({ forceConfirmation: session.forceConfirmation })
  })
}

type TurnInput = Omit<
  Parameters<typeof streamSolMessage>[0],
  'conversationId' | 'onEvent' | 'signal' | 'preferences'
>

/** One streamed turn: optional user bubble, a pending assistant item, the
 *  stream, and end-of-turn bookkeeping. Shared by sends and resumes. */
async function runTurn(
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
    failed = !resumeRefusal(projectId, assistantId, patch, error)
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

/** A resume the server declined on purpose (§5.5): `resume_limit` pauses SOL
 *  until the person replies; `already_resumed` is someone else's resume and
 *  vanishes silently. True when handled. */
function resumeRefusal(
  projectId: string,
  assistantId: string,
  patch: Patch,
  error: unknown
): boolean {
  if (!(error instanceof ApiError) || error.status !== 409) return false
  if (error.code === 'resume_limit') {
    patch((m) => ({ ...m, pending: false, content: RESUME_PAUSED }))
    return true
  }
  if (error.code !== 'already_resumed') return false
  patchSession(projectId, (s) => ({ ...s, items: s.items.filter((m) => m.id !== assistantId) }))
  return true
}

/** One live turn per project, MAX_CONCURRENT_TURNS overall; the refusal is
 *  painted into the transcript, never thrown. */
function admitTurn(projectId: string): boolean {
  if (controllers.has(projectId)) return false
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

/** The message text after a decision: a restored approvals item says what
 *  happened; a chat message gains an "Approval update" line. */
function decidedContent(
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

/** Drop the decided card from whichever message carries it. */
function markDecided(
  projectId: string,
  confirmationId: string,
  decision: 'approve' | 'reject'
): void {
  decidedApprovals.add(`${projectId}:${confirmationId}`)
  patchSession(projectId, (s) => ({
    ...s,
    items: s.items.map((m) =>
      m.confirmations.some((c) => c.confirmationId === confirmationId)
        ? {
            ...m,
            content: decidedContent(m, confirmationId, decision),
            confirmations: m.confirmations.filter((c) => c.confirmationId !== confirmationId)
          }
        : m
    )
  }))
}

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

export async function decideConfirmation(
  projectId: string,
  confirmationId: string,
  decision: 'approve' | 'reject',
  options?: { actionMode?: SolActionMode }
): Promise<void> {
  // Clear ONLY on success — ConfirmationCard owns the failure state (CTR-03).
  const generation = identityGeneration
  const tool = findConfirmation(projectId, confirmationId)?.tool ?? null
  const approving = decision === 'approve' && tool !== null
  const tracked = approving && hasCommandOutput(tool)
  if (tracked) runs.begin(projectId, confirmationId, tool)
  const outcome = await postDecision(projectId, confirmationId, decision, tracked, generation)
  if (outcome === null) return
  markDecided(projectId, confirmationId, decision)
  if (approving) resumeAfterCommand(projectId, confirmationId, tool, options?.actionMode)
}

/** SOLUSDEV-317 §5.5: SOL continues after an approved command. Never after a
 *  rejection (the caller only calls on approve), and never for a non-command card. */
function resumeAfterCommand(
  projectId: string,
  confirmationId: string,
  tool: string,
  actionMode: SolActionMode | undefined
): void {
  if (isCommandTool(tool) && actionMode) void resumeTurn(projectId, confirmationId, actionMode)
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
    patchSession(projectId, (s) => ({
      ...s,
      contextUsed: {
        sections: event.sections,
        truncated: event.truncated,
        dropped: event.dropped
      }
    }))
    return false
  }
  // Mid-stream credit exhaustion arrives as an error FRAME, not a 402.
  if (event.type === 'error') {
    if (event.code === 'insufficient_credits') {
      patchSession(projectId, (s) => ({ ...s, creditsExhausted: true }))
    }
  }
  applyEvent(patch, event)
  return event.type === 'error'
}
