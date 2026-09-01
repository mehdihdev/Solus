// SOLUSDEV-233: the chats sidebar's data — the caller's conversations for the
// active project, newest first. Refetches when the active conversation changes
// (a first send creates one) so a new chat appears without a manual reload.
import { useEffect, useState } from 'react'
import { listSolConversations, type SolConversation } from './solApi'

export type SolConversationsStatus = 'loading' | 'ready' | 'offline'

export interface SolConversationsData {
  conversations: readonly SolConversation[]
  status: SolConversationsStatus
}

export function useSolConversations(
  projectId: string | null,
  activeConversationId: string | null
): SolConversationsData {
  const [conversations, setConversations] = useState<readonly SolConversation[]>([])
  const [status, setStatus] = useState<SolConversationsStatus>('ready')

  useEffect(() => {
    if (!projectId) {
      setConversations([])
      setStatus('ready')
      return
    }
    let stale = false
    // The previous list stays in state during a refetch, so renderers can keep
    // showing rows and reserve the loading state for a first, empty load.
    setStatus('loading')
    listSolConversations(projectId)
      .then((list) => {
        if (stale) return
        setConversations(list)
        setStatus('ready')
      })
      .catch(() => {
        if (!stale) setStatus('offline')
      })
    return () => {
      stale = true
    }
  }, [projectId, activeConversationId])

  return { conversations, status }
}
