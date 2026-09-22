// SOLUSDEV-233: the SOL page's chats sidebar.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import { ChatsSidebar } from './ChatsSidebar'

vi.mock('./solApi', () => ({
  listSolConversations: vi.fn(),
  renameSolConversation: vi.fn(),
  deleteSolConversation: vi.fn()
}))
const listSolConversations = vi.mocked(solApi.listSolConversations)
const renameSolConversation = vi.mocked(solApi.renameSolConversation)
const deleteSolConversation = vi.mocked(solApi.deleteSolConversation)

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

describe('right-click menu (SOLUSDEV-233)', () => {
  it('renames a chat through the context menu', async () => {
    listSolConversations.mockResolvedValue([conversation('c1', 'Old name')])
    renameSolConversation.mockResolvedValue(conversation('c1', 'Diagnose run 41'))
    render(
      <ChatsSidebar
        projectId="p1"
        activeConversationId={null}
        onSelect={vi.fn()}
        onNewChat={vi.fn()}
      />
    )
    fireEvent.contextMenu(await screen.findByText('Old name'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Rename' }))
    const input = screen.getByLabelText('Chat name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Diagnose run 41')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(renameSolConversation).toHaveBeenCalledWith('p1', 'c1', 'Diagnose run 41')
    )
    expect(listSolConversations.mock.calls.length).toBeGreaterThan(1) // list refreshed
  })

  it('deletes a chat only after confirming, and clears the open chat', async () => {
    listSolConversations.mockResolvedValue([conversation('c1', 'Project recap')])
    deleteSolConversation.mockResolvedValue(undefined)
    const onNewChat = vi.fn()
    render(
      <ChatsSidebar
        projectId="p1"
        activeConversationId="c1"
        onSelect={vi.fn()}
        onNewChat={onNewChat}
      />
    )
    fireEvent.contextMenu(await screen.findByText('Project recap'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(deleteSolConversation).not.toHaveBeenCalled() // confirm first
    await userEvent.click(screen.getByRole('button', { name: 'Delete chat' }))
    await waitFor(() => expect(deleteSolConversation).toHaveBeenCalledWith('p1', 'c1'))
    expect(onNewChat).toHaveBeenCalled() // the open chat was deleted
  })

  it('keeps the confirm open with an error when the delete fails', async () => {
    listSolConversations.mockResolvedValue([conversation('c1', 'Project recap')])
    deleteSolConversation.mockRejectedValue(new Error('404'))
    render(
      <ChatsSidebar
        projectId="p1"
        activeConversationId={null}
        onSelect={vi.fn()}
        onNewChat={vi.fn()}
      />
    )
    fireEvent.contextMenu(await screen.findByText('Project recap'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete chat' }))
    expect(await screen.findByText(/Couldn.t delete this chat/)).toBeInTheDocument()
  })
})

describe('menu positioning (code review M)', () => {
  it('clamps the context menu inside the viewport near edges', async () => {
    listSolConversations.mockResolvedValue([conversation('c1', 'Project recap')])
    render(
      <ChatsSidebar
        projectId="p1"
        activeConversationId={null}
        onSelect={vi.fn()}
        onNewChat={vi.fn()}
      />
    )
    const row = await screen.findByText('Project recap')
    // Right-click at the very bottom-right corner of the window.
    fireEvent.contextMenu(row, { clientX: window.innerWidth, clientY: window.innerHeight })
    const menu = screen.getByRole('menu')
    const left = Number.parseFloat(menu.style.left)
    const top = Number.parseFloat(menu.style.top)
    expect(left).toBeLessThanOrEqual(window.innerWidth - 150)
    expect(top).toBeLessThanOrEqual(window.innerHeight - 90)
  })
})
