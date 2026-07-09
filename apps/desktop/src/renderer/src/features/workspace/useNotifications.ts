// Real notifications for the shell bell (API.md §2.1): unread badge + mark-read.
// Degrades to `offline` (dev bypass / unreachable API) so the shell can fall
// back to the scripted demo alerts and the guided tour still works.
import { useCallback, useEffect, useState } from 'react'
import {
  listNotificationsPage,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationApi
} from '../../lib/api/resources'
import type { ApiMeta } from '../../lib/api/envelope.types'
import { useWorkspaceStore } from '../../store/workspaceStore'

export type NotificationsStatus = 'loading' | 'ready' | 'offline'

export interface NotificationsData {
  status: NotificationsStatus
  items: NotificationApi[]
  unreadCount: number
  hasMore: boolean
  markRead: (id: string) => Promise<void>
  markAllRead: () => Promise<void>
  loadMore: () => Promise<void>
  refresh: () => Promise<void>
}

export function useNotifications(): NotificationsData {
  const linked = useWorkspaceStore((s) => s.linked)
  const [status, setStatus] = useState<NotificationsStatus>(linked ? 'loading' : 'offline')
  const [items, setItems] = useState<NotificationApi[]>([])
  const [meta, setMeta] = useState<ApiMeta>({})

  const load = useCallback(async (): Promise<void> => {
    if (!linked) {
      setStatus('offline')
      return
    }
    try {
      const page = await listNotificationsPage()
      setItems(page.data)
      setMeta(page.meta)
      setStatus('ready')
    } catch {
      setStatus('offline')
    }
  }, [linked])

  // Append the next cursor page. No-op when there's nothing more; keeps the
  // current page on failure so the bell never regresses to empty.
  const loadMore = async (): Promise<void> => {
    if (!meta.has_next || !meta.next_cursor) return
    try {
      const page = await listNotificationsPage(meta.next_cursor)
      setItems((prev) => [...prev, ...page.data])
      setMeta(page.meta)
    } catch {
      /* keep the current page */
    }
  }

  useEffect(() => {
    void load()
  }, [load])

  const markRead = async (id: string): Promise<void> => {
    const stamp = new Date().toISOString()
    // Optimistic: reflect the read immediately, reconcile on failure.
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read_at: n.read_at ?? stamp } : n)))
    try {
      await markNotificationRead(id)
    } catch {
      await load().catch(() => undefined)
    }
  }

  const markAllRead = async (): Promise<void> => {
    const stamp = new Date().toISOString()
    // Optimistic: stamp every unread item, reconcile from the server on failure.
    setItems((prev) => prev.map((n) => (n.read_at ? n : { ...n, read_at: stamp })))
    try {
      await markAllNotificationsRead()
    } catch {
      await load().catch(() => undefined)
    }
  }

  const unreadCount = items.filter((n) => !n.read_at).length
  return {
    status,
    items,
    unreadCount,
    hasMore: meta.has_next ?? false,
    markRead,
    markAllRead,
    loadMore,
    refresh: load
  }
}
