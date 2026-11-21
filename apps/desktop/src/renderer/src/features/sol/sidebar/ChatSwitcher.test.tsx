// SOL sidebar chat switcher (sol-sidebar.md §3, Chat switcher): the title trigger, the popover
// list, search, keyboard, new chat and the empty / offline states.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import type { SolConversation } from '../solApi'
import type { SolConversationsData } from '../useSolConversations'
import { ChatSwitcher, type ChatSwitcherProps } from './ChatSwitcher'

function chat(id: string, title: string | null): SolConversation {
  const at = new Date().toISOString()
  return { id, project_id: 'p1', title, created_by: 'u1', created_at: at, updated_at: at }
}

const CHATS = [chat('a', 'IMU drops out'), chat('b', 'Gripper torque'), chat('c', 'CUDA 11.8')]

function data(over: Partial<SolConversationsData> = {}): SolConversationsData {
  return { conversations: CHATS, status: 'ready', refresh: vi.fn(), ...over }
}

let props: ChatSwitcherProps

function renderSwitcher(over: Partial<ChatSwitcherProps> = {}): ReturnType<typeof render> {
  props = {
    data: data(),
    activeConversationId: 'a',
    onSelect: vi.fn(),
    onNewChat: vi.fn(),
    onShowAll: vi.fn(),
    ...over
  }
  return render(<ChatSwitcher {...props} />)
}

const trigger = (): HTMLElement => screen.getByRole('button', { name: /Switch chat/ })
const list = (): HTMLElement => screen.getByRole('listbox', { name: 'Chats in this project' })
const search = (): HTMLElement => screen.getByRole('combobox', { name: 'Search chats' })

beforeEach(() => {
  vi.useRealTimers()
})

describe('ChatSwitcher — trigger', () => {
  it('names the active chat and starts closed', () => {
    renderSwitcher()
    expect(trigger()).toHaveTextContent('IMU drops out')
    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('reads New chat when no conversation is active yet', () => {
    renderSwitcher({ activeConversationId: null })
    expect(trigger()).toHaveTextContent('New chat')
  })

  it('opens the list, refreshes it and focuses search', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    expect(trigger()).toHaveAttribute('aria-expanded', 'true')
    expect(within(list()).getAllByRole('option')).toHaveLength(3)
    expect(search()).toHaveFocus()
    expect(props.data.refresh).toHaveBeenCalledTimes(1)
  })

  it('opens from ArrowDown on the trigger', () => {
    renderSwitcher()
    fireEvent.keyDown(trigger(), { key: 'ArrowDown' })
    expect(list()).toBeInTheDocument()
  })

  it('starts a new chat from the plus button', () => {
    renderSwitcher()
    fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
    expect(props.onNewChat).toHaveBeenCalled()
  })
})

describe('ChatSwitcher — list', () => {
  it('marks the active chat selected', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    const active = within(list()).getByRole('option', { name: /IMU drops out/ })
    expect(active).toHaveAttribute('aria-selected', 'true')
  })

  it('picks a chat and closes', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    fireEvent.click(within(list()).getByRole('option', { name: /Gripper torque/ }))
    expect(props.onSelect).toHaveBeenCalledWith('b')
    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
  })

  it('does not re-select the chat already open', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    fireEvent.click(within(list()).getByRole('option', { name: /IMU drops out/ }))
    expect(props.onSelect).not.toHaveBeenCalled()
  })

  it('filters by the search text and says when nothing matches', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    fireEvent.change(search(), { target: { value: 'cuda' } })
    expect(within(list()).getAllByRole('option')).toHaveLength(1)
    fireEvent.change(search(), { target: { value: 'nothing here' } })
    expect(within(list()).queryAllByRole('option')).toHaveLength(0)
    expect(screen.getByText('No chats match.')).toBeInTheDocument()
  })

  it('new chat in the list starts one and closes', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    fireEvent.click(screen.getByRole('button', { name: 'Start a new chat' }))
    expect(props.onNewChat).toHaveBeenCalled()
    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
  })

  it('All chats hands off to the SOL page', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    fireEvent.click(screen.getByRole('button', { name: 'All chats' }))
    expect(props.onShowAll).toHaveBeenCalled()
  })

  it('shows the offline and empty states', () => {
    const { unmount } = renderSwitcher({ data: data({ conversations: [], status: 'offline' }) })
    fireEvent.click(trigger())
    expect(screen.getByText('Chats unavailable — offline.')).toBeInTheDocument()
    unmount()
    renderSwitcher({ data: data({ conversations: [] }), activeConversationId: null })
    fireEvent.click(trigger())
    expect(screen.getByText('No chats yet. Ask SOL anything to start one.')).toBeInTheDocument()
  })
})

describe('ChatSwitcher — keyboard and dismissal', () => {
  it('moves with the arrows and opens the highlighted chat with Enter', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    // Opens on the active chat; one step down is the next.
    fireEvent.keyDown(search(), { key: 'ArrowDown' })
    const next = within(list()).getByRole('option', { name: /Gripper torque/ })
    expect(search()).toHaveAttribute('aria-activedescendant', next.id)
    fireEvent.keyDown(search(), { key: 'Enter' })
    expect(props.onSelect).toHaveBeenCalledWith('b')
  })

  it('Escape closes the list only, and returns focus to the trigger', () => {
    const outer = vi.fn()
    props = {
      data: data(),
      activeConversationId: 'a',
      onSelect: vi.fn(),
      onNewChat: vi.fn(),
      onShowAll: vi.fn()
    }
    render(
      <div onKeyDown={(e) => !e.defaultPrevented && outer()}>
        <ChatSwitcher {...props} />
      </div>
    )
    fireEvent.click(trigger())
    fireEvent.keyDown(search(), { key: 'Escape' })
    expect(outer).not.toHaveBeenCalled()
    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
    expect(trigger()).toHaveFocus()
  })

  it('closes on a press outside', () => {
    renderSwitcher()
    fireEvent.click(trigger())
    act(() => {
      fireEvent.pointerDown(document.body)
    })
    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
  })

  it('unmounts the list after its closing motion', () => {
    vi.useFakeTimers()
    renderSwitcher()
    fireEvent.click(trigger())
    fireEvent.keyDown(search(), { key: 'Escape' })
    act(() => {
      vi.runAllTimers()
    })
    expect(screen.queryByRole('listbox')).toBeNull()
  })
})
