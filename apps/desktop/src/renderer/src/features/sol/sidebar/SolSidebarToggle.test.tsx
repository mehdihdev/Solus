// SOLUSDEV-327 — the menu bar's SOL toggle (sol-sidebar.md §2).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { resetSolChatSessions, useSolChatStore } from '../solChatStore'
import { SolSidebarToggle } from './SolSidebarToggle'
import { selectSidebarOpen, useSolSidebarStore } from './solSidebarStore'
import * as events from './sidebarEvents'

vi.mock('./sidebarEvents', () => ({ reportSidebarToggled: vi.fn() }))

beforeEach(() => {
  vi.clearAllMocks()
  useSolSidebarStore.getState().reset()
  resetSolChatSessions()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
})

const button = (): HTMLElement => screen.getByRole('button', { name: /SOL sidebar/ })

describe('SolSidebarToggle', () => {
  it('shows SOL and the shortcut, unpressed by default', () => {
    render(<SolSidebarToggle screen="workspace" />)
    expect(button()).toHaveAttribute('aria-pressed', 'false')
    expect(button()).toHaveTextContent('SOL')
    expect(button()).toHaveTextContent(/⌘J|Ctrl J/)
  })

  it('toggles the sidebar for its screen and reports it', () => {
    render(<SolSidebarToggle screen="bench" />)
    fireEvent.click(button())
    expect(selectSidebarOpen(useSolSidebarStore.getState(), 'bench')).toBe(true)
    expect(button()).toHaveAttribute('aria-pressed', 'true')
    expect(events.reportSidebarToggled).toHaveBeenCalledWith('open', 'bench', 'button')
    fireEvent.click(button())
    expect(events.reportSidebarToggled).toHaveBeenLastCalledWith('close', 'bench', 'button')
  })

  it('is hidden on the SOL page', () => {
    render(<SolSidebarToggle screen="sol" />)
    expect(screen.queryByRole('button', { name: /SOL sidebar/ })).toBeNull()
  })

  it('its orb quickens while SOL works on the project', () => {
    render(<SolSidebarToggle screen="workspace" />)
    const orb = (): Element | null => button().querySelector('.sol-orb')
    expect(orb()).not.toHaveClass('sol-pulse')
    act(() =>
      useSolChatStore.setState((s) => ({
        sessions: { ...s.sessions, p1: { ...(s.sessions.p1 ?? {}), streaming: true } as never }
      }))
    )
    expect(orb()).toHaveClass('sol-pulse')
  })
})
