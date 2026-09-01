// SOLUSDEV-233: the SOL page's chats sidebar.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import { ChatsSidebar } from './ChatsSidebar'

vi.mock('./solApi', () => ({ listSolConversations: vi.fn() }))
const listSolConversations = vi.mocked(solApi.listSolConversations)

function conversation(id: string, title: string | null): solApi.SolConversation {
  return {
    id,
    project_id: 'p1',
    title,
    created_by: 'u1',
    created_at: '2026-08-16T00:00:00Z',
    updated_at: '2026-08-16T00:00:00Z'
  }
}

beforeEach(() => vi.clearAllMocks())

describe('ChatsSidebar', () => {
  it('lists chats with titles and marks the active one', async () => {
    listSolConversations.mockResolvedValue([
      conversation('c1', 'Project recap'),
      conversation('c2', null)
    ])
    render(
      <ChatsSidebar
        projectId="p1"
        activeConversationId="c1"
        onSelect={vi.fn()}
        onNewChat={vi.fn()}
      />
    )
    await waitFor(() => expect(screen.getByText('Project recap')).toBeInTheDocument())
    expect(screen.getByText('New chat')).toBeInTheDocument() // untitled fallback
    expect(screen.getByRole('button', { name: /Project recap/ })).toHaveAttribute(
      'aria-current',
      'true'
    )
  })

  it('selects a chat and starts a new one', async () => {
    listSolConversations.mockResolvedValue([conversation('c1', 'Project recap')])
    const onSelect = vi.fn()
    const onNewChat = vi.fn()
    render(
      <ChatsSidebar
        projectId="p1"
        activeConversationId={null}
        onSelect={onSelect}
        onNewChat={onNewChat}
      />
    )
    await userEvent.click(await screen.findByText('Project recap'))
    expect(onSelect).toHaveBeenCalledWith('c1')
    await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
    expect(onNewChat).toHaveBeenCalled()
  })

  it('shows honest empty and offline states', async () => {
    listSolConversations.mockResolvedValue([])
    const { rerender } = render(
      <ChatsSidebar
        projectId="p1"
        activeConversationId={null}
        onSelect={vi.fn()}
        onNewChat={vi.fn()}
      />
    )
    await waitFor(() => expect(screen.getByText(/No chats yet/)).toBeInTheDocument())

    listSolConversations.mockRejectedValue(new Error('down'))
    rerender(
      <ChatsSidebar
        projectId="p2"
        activeConversationId={null}
        onSelect={vi.fn()}
        onNewChat={vi.fn()}
      />
    )
    await waitFor(() => expect(screen.getByText(/Chats unavailable/)).toBeInTheDocument())
  })
})
