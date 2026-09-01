// SOLUSDEV-233: the chats sidebar's data hook.
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import { useSolConversations } from './useSolConversations'

vi.mock('./solApi', () => ({ listSolConversations: vi.fn() }))
const listSolConversations = vi.mocked(solApi.listSolConversations)

function conversation(id: string, title: string | null): solApi.SolConversation {
  return {
    id,
    project_id: 'p1',
    title,
    created_by: 'u1',
    created_at: '2026-08-30T00:00:00Z',
    updated_at: '2026-08-30T00:00:00Z'
  }
}

beforeEach(() => vi.clearAllMocks())

describe('useSolConversations', () => {
  it('loads the project’s conversations', async () => {
    listSolConversations.mockResolvedValue([conversation('c1', 'Project recap')])
    const { result } = renderHook(() => useSolConversations('p1', null))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.conversations.map((c) => c.id)).toEqual(['c1'])
  })

  it('is empty and quiet without a project', async () => {
    const { result } = renderHook(() => useSolConversations(null, null))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(listSolConversations).not.toHaveBeenCalled()
  })

  it('refetches when the active conversation changes (a first send created one)', async () => {
    listSolConversations.mockResolvedValue([])
    const { result, rerender } = renderHook(
      ({ active }: { active: string | null }) => useSolConversations('p1', active),
      { initialProps: { active: null as string | null } }
    )
    await waitFor(() => expect(result.current.status).toBe('ready'))
    listSolConversations.mockResolvedValue([conversation('c9', 'hello')])
    rerender({ active: 'c9' })
    await waitFor(() => expect(result.current.conversations).toHaveLength(1))
    expect(listSolConversations).toHaveBeenCalledTimes(2)
  })

  it('degrades to offline when the list cannot load', async () => {
    listSolConversations.mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useSolConversations('p1', null))
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })
})
