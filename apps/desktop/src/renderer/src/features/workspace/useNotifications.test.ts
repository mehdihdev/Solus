// Notifications hook: unread count, optimistic mark-read, offline fallback.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useNotifications } from './useNotifications'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, listNotificationsPage: vi.fn(), markNotificationRead: vi.fn() }
})

const NOTIFS: resources.NotificationApi[] = [
  {
    id: 'n1',
    type: 'team.invite',
    title: 'You were invited',
    body: null,
    payload: {},
    read_at: null,
    created_at: '2026-07-06T00:00:00Z'
  },
  {
    id: 'n2',
    type: 'invite.accepted',
    title: 'Priya joined',
    body: null,
    payload: {},
    read_at: '2026-07-05T00:00:00Z',
    created_at: '2026-07-05T00:00:00Z'
  }
]

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true })
  vi.mocked(resources.listNotificationsPage).mockResolvedValue({ data: NOTIFS, meta: {} })
  vi.mocked(resources.markNotificationRead).mockResolvedValue(NOTIFS[0])
})

describe('useNotifications', () => {
  it('loads notifications and counts unread', async () => {
    const { result } = renderHook(() => useNotifications())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.items).toHaveLength(2)
    expect(result.current.unreadCount).toBe(1)
  })

  it('marks read optimistically, dropping the unread count', async () => {
    const { result } = renderHook(() => useNotifications())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.markRead('n1')
    })
    expect(result.current.unreadCount).toBe(0)
    expect(vi.mocked(resources.markNotificationRead)).toHaveBeenCalledWith('n1')
  })

  it('is offline when not linked', async () => {
    useWorkspaceStore.setState({ linked: false })
    const { result } = renderHook(() => useNotifications())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(resources.listNotificationsPage).not.toHaveBeenCalled()
  })

  it('exposes hasMore and appends the next cursor page via loadMore', async () => {
    const more: resources.NotificationApi = { ...NOTIFS[0], id: 'n3' }
    vi.mocked(resources.listNotificationsPage)
      .mockResolvedValueOnce({ data: NOTIFS, meta: { has_next: true, next_cursor: 'c2' } })
      .mockResolvedValueOnce({ data: [more], meta: { has_next: false } })
    const { result } = renderHook(() => useNotifications())
    await waitFor(() => expect(result.current.hasMore).toBe(true))
    await act(async () => {
      await result.current.loadMore()
    })
    expect(result.current.items.map((n) => n.id)).toEqual(['n1', 'n2', 'n3'])
    expect(result.current.hasMore).toBe(false)
    expect(vi.mocked(resources.listNotificationsPage)).toHaveBeenLastCalledWith('c2')
  })
})
