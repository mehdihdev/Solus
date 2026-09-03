// SOLX-02 / SOLUSDEV-233: the chat surface's view of a project's SOL session.
// State and the streaming turn live in solChatStore — a session OUTLIVES this
// hook, so navigating away keeps the reply running and returning re-attaches.
// This hook only selects the session and keeps it synced to the project's
// active conversation.
import { useEffect } from 'react'
import type { SolActionMode } from './solApi'
import type { ContextUsedInfo } from './solStream'
import { selectConversationId, useOrbStore } from './orbStore'
import {
  decideConfirmation,
  selectConversation as selectConversationInStore,
  selectSession,
  sendMessage,
  startNewChat as startNewChatInStore,
  syncSession,
  useSolChatStore,
  type ChatItem,
  type ChatStatus,
  type TraceEntry
} from './solChatStore'

export type { ChatItem, ChatStatus, TraceEntry }

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
   *  the text, never encoded into it. */
  send: (
    content: string,
    actionMode: SolActionMode,
    mentions?: readonly string[]
  ) => Promise<void>
  /** Switch to another owned conversation (cancels any live turn first). */
  selectConversation: (conversationId: string) => void
  /** Forget the active conversation so the next send starts a fresh chat. */
  startNewChat: () => void
  /** CTR-03: record approve/reject for a parked action. Rejection is a decision
   *  too, so both clear the card; the arguments that execute are the stored
   *  server-side ones the user was shown, never re-sent from here. */
  decide: (confirmationId: string, decision: 'approve' | 'reject') => Promise<void>
}

export function useSolChat(projectId: string | null): SolChat {
  const session = useSolChatStore((s) => selectSession(s, projectId))
  const conversationId = useOrbStore((s) => selectConversationId(s, projectId))

  // Keep the session pointed at the active conversation. syncSession no-ops
  // when they already match (including the id a live send just created), and
  // deliberately does NOT abort anything on unmount — sessions outlive pages.
  useEffect(() => {
    if (projectId) void syncSession(projectId)
  }, [projectId, conversationId])

  return {
    items: session.items,
    status: session.status,
    streaming: session.streaming,
    contextUsed: session.contextUsed,
    creditsExhausted: session.creditsExhausted,
    activeConversationId: conversationId,
    send: (content, actionMode, mentions) =>
      projectId ? sendMessage(projectId, content, actionMode, mentions) : Promise.resolve(),
    selectConversation: (id) => projectId && selectConversationInStore(projectId, id),
    startNewChat: () => projectId && startNewChatInStore(projectId),
    decide: (confirmationId, decision) =>
      projectId ? decideConfirmation(projectId, confirmationId, decision) : Promise.resolve()
  }
}
