// SOLX-02 / SOLUSDEV-233: the chat surface's view of a project's SOL session.
// State and the streaming turn live in solChatStore — a session OUTLIVES this
// hook, so navigating away keeps the reply running and returning re-attaches.
// This hook only selects the session and keeps it synced to the project's
// active conversation.
import { useCallback, useEffect, useMemo } from 'react'
import type { SolActionMode, SolScreenshot } from './solApi'
import type { SolusSection } from '../../lib/api/resources'
import type { ContextUsedInfo } from './solStream'
import { selectConversationId, useSolSessionStore } from './solSessionStore'
import {
  decideConfirmation,
  fileArtifact as fileArtifactInStore,
  selectConversation as selectConversationInStore,
  selectSession,
  sendMessage,
  startNewChat as startNewChatInStore,
  syncSession,
  useSolChatStore,
  type ChatArtifact,
  type ChatItem,
  type ChatStatus,
  type TraceEntry
} from './solChatStore'

export type { ChatArtifact, ChatItem, ChatStatus, TraceEntry }

export interface SolChat {
  items: readonly ChatItem[]
  status: ChatStatus
  streaming: boolean
  /** SOLUSDEV-233: the latest turn's context manifest (labels only). */
  contextUsed: ContextUsedInfo | null
  /** True after a 402 turn rejection — drives the top-up card. */
  creditsExhausted: boolean
  activeConversationId: string | null
  /** `mentions` are graph entity ids the user picked with `@` — carried beside
   *  the text, never encoded into it. `screenshot` is the circled region for
   *  THIS turn only (SOLUSDEV-252 S3). Resolves true when the turn settled
   *  without error (failures are painted into the transcript, never thrown). */
  send: (
    content: string,
    actionMode: SolActionMode,
    mentions?: readonly string[],
    thinkHarder?: boolean,
    screenshot?: SolScreenshot
  ) => Promise<boolean>
  /** Switch to another owned conversation (cancels any live turn first). */
  selectConversation: (conversationId: string) => void
  /** Forget the active conversation so the next send starts a fresh chat. */
  startNewChat: () => void
  /** CTR-03: record approve/reject for a parked action. Rejection is a decision
   *  too, so both clear the card; the arguments that execute are the stored
   *  server-side ones the user was shown, never re-sent from here. */
  decide: (confirmationId: string, decision: 'approve' | 'reject') => Promise<void>
  /** SOLUSDEV-252 S5: file a turn's artifact into a `.solus` section (once). */
  fileArtifact: (artifactId: string, section: SolusSection) => Promise<void>
}

export function useSolChat(projectId: string | null): SolChat {
  const session = useSolChatStore((s) => selectSession(s, projectId))
  const conversationId = useSolSessionStore((s) => selectConversationId(s, projectId))

  // Keep the session pointed at the active conversation. syncSession no-ops
  // when they already match (including the id a live send just created), and
  // deliberately does NOT abort anything on unmount — sessions outlive pages.
  useEffect(() => {
    if (projectId) void syncSession(projectId)
  }, [projectId, conversationId])

  // S2-A: callbacks keyed on the project only, so memoised rows downstream
  // (onDecide) do not re-render on every store tick of a streaming turn.
  const send = useCallback<SolChat['send']>(
    (content, actionMode, mentions, thinkHarder, screenshot) =>
      projectId
        ? sendMessage(projectId, content, actionMode, mentions, thinkHarder, screenshot)
        : Promise.resolve(false),
    [projectId]
  )
  const selectConversation = useCallback<SolChat['selectConversation']>(
    (id) => {
      if (projectId) selectConversationInStore(projectId, id)
    },
    [projectId]
  )
  const startNewChat = useCallback<SolChat['startNewChat']>(() => {
    if (projectId) startNewChatInStore(projectId)
  }, [projectId])
  const decide = useCallback<SolChat['decide']>(
    (confirmationId, decision) =>
      projectId ? decideConfirmation(projectId, confirmationId, decision) : Promise.resolve(),
    [projectId]
  )

  const fileArtifact = useCallback<SolChat['fileArtifact']>(
    (artifactId, section) =>
      projectId ? fileArtifactInStore(projectId, artifactId, section) : Promise.resolve(),
    [projectId]
  )

  return useMemo<SolChat>(
    () => ({
      items: session.items,
      status: session.status,
      streaming: session.streaming,
      contextUsed: session.contextUsed,
      creditsExhausted: session.creditsExhausted,
      activeConversationId: conversationId,
      send,
      selectConversation,
      startNewChat,
      decide,
      fileArtifact
    }),
    [session, conversationId, send, selectConversation, startNewChat, decide, fileArtifact]
  )
}
