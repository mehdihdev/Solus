// Real notifications for the shell bell (API.md §2.1): unread badge + mark-read.
// Degrades to `offline` (dev bypass / unreachable API) so the shell can fall
// back to the scripted demo alerts and the guided tour still works.
import { useCallback, useEffect, useState } from 'react'
import {
  listNotifications,
  markNotificationRead,
  type NotificationApi
} from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'

export type NotificationsStatus = 'loading' | 'ready' | 'offline'

export interface NotificationsData {
  status: NotificationsStatus
  items: NotificationApi[]
  unreadCount: number
  markRead: (id: string) => Promise<void>
  refresh: () => Promise<void>
}

export function useNotifications(): NotificationsData {
  const linked = useWorkspaceStore((s) => s.linked)
  const [status, setStatus] = useState<NotificationsStatus>(linked ? 'loading' : 'offline')
  const [items, setItems] = useState<NotificationApi[]>([])

  const load = useCallback(async (): Promise<void> => {
    if (!linked) {
      setStatus('offline')
      return
    }
    try {
      setItems(await listNotifications())
      setStatus('ready')
    } catch {
      setStatus('offline')
    }
  }, [linked])

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

  const unreadCount = items.filter((n) => !n.read_at).length
  return { status, items, unreadCount, markRead, refresh: load }
}
