// SOLUSDEV-233: the chats sidebar's data — the caller's conversations for the
// active project, newest first. Refetches when the active conversation changes
// (a first send creates one) and on demand (rename/delete) so the list never
// needs a manual reload.
import { useCallback, useEffect, useState } from 'react'
import { listSolConversations, type SolConversation } from './solApi'

export type SolConversationsStatus = 'loading' | 'ready' | 'offline'

export interface SolConversationsData {
  conversations: readonly SolConversation[]
  status: SolConversationsStatus
  /** Refetch the list (after a rename/delete). */
  refresh: () => void
}

export function useSolConversations(
  projectId: string | null,
  activeConversationId: string | null
): SolConversationsData {
  const [conversations, setConversations] = useState<readonly SolConversation[]>([])
  const [version, setVersion] = useState(0)
  // Status is derived, not stored (the UsagePanel pattern): 'loading' until the
  // fetch for THIS key has answered.
  const key = `${projectId}|${activeConversationId}|${version}`
  const [answered, setAnswered] = useState<{ key: string; status: 'ready' | 'offline' } | null>(
    null
  )
  if (!projectId && conversations.length > 0) setConversations([])

  const refresh = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    if (!projectId) return
    let stale = false
    // The previous list stays in state during a refetch, so renderers can keep
    // showing rows and reserve the loading state for a first, empty load.
    listSolConversations(projectId)
      .then((list) => {
        if (stale) return
        setConversations(list)
        setAnswered({ key, status: 'ready' })
      })
      .catch(() => {
        if (!stale) setAnswered({ key, status: 'offline' })
      })
    return () => {
      stale = true
    }
  }, [projectId, key])

  const status: SolConversationsStatus = !projectId
    ? 'ready'
    : answered?.key === key
      ? answered.status
      : 'loading'
  return { conversations, status, refresh }
}
