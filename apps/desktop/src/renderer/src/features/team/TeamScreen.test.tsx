import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TeamScreen } from './TeamScreen'
import { TEAM, ACTIVITY } from '../workspace/workspaceData.constants'

afterEach(() => {
  vi.useRealTimers()
})

describe('TeamScreen — roster', () => {
  it('renders all four members with their roles', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    for (const member of TEAM) {
      expect(screen.getByText(member.name)).toBeInTheDocument()
      expect(screen.getByText(`● ${member.role.toUpperCase()}`)).toBeInTheDocument()
      expect(screen.getByText(member.email)).toBeInTheDocument()
    }
  })

  it('marks the current user with a YOU badge', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    expect(screen.getByText('(you)')).toBeInTheDocument()
  })

  it('shows member last-active times', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    expect(screen.getByText('12 min ago')).toBeInTheDocument()
    expect(screen.getByText('1h ago')).toBeInTheDocument()
  })
})

describe('TeamScreen — activity feed', () => {
  it('renders every activity row', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    for (const item of ACTIVITY) {
      expect(screen.getByText(new RegExp(escapeRegExp(item.what)))).toBeInTheDocument()
    }
  })

  it('flags cross-domain rows with an AFFECTS YOUR CODE badge', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    const affected = ACTIVITY.filter((a) => a.affects).length
    expect(screen.getAllByText('AFFECTS YOUR CODE')).toHaveLength(affected)
  })

  it('opens the linked alert when an affects-row is clicked', async () => {
    const onOpenAlert = vi.fn()
    render(<TeamScreen onOpenAlert={onOpenAlert} />)
    await userEvent.click(screen.getByText(/swapped U4: DRV8833 → DRV8316C/))
    expect(onOpenAlert).toHaveBeenCalledWith('a1')
  })

  it('does nothing when a row without an alert is clicked', async () => {
    const onOpenAlert = vi.fn()
    render(<TeamScreen onOpenAlert={onOpenAlert} />)
    await userEvent.click(screen.getByText(/tuned standing-gait stride/))
    expect(onOpenAlert).not.toHaveBeenCalled()
  })
})

describe('TeamScreen — invite flow (visual only)', () => {
  it('opens and closes the invite modal', async () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    await userEvent.click(screen.getByText('Invite teammate'))
    expect(screen.getByPlaceholderText('teammate@team.dev')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByPlaceholderText('teammate@team.dev')).not.toBeInTheDocument()
  })

  it('ignores an invalid email', () => {
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    fireEvent.click(screen.getByText('Invite teammate'))
    fireEvent.change(screen.getByPlaceholderText('teammate@team.dev'), {
      target: { value: 'not-an-email' }
    })
    fireEvent.click(screen.getByText('Send invite'))
    // Modal stays open, no pending row appears.
    expect(screen.getByPlaceholderText('teammate@team.dev')).toBeInTheDocument()
    expect(screen.queryByText('INVITE PENDING')).not.toBeInTheDocument()
  })

  it('adds a pending member after sending a valid invite', () => {
    vi.useFakeTimers()
    render(<TeamScreen onOpenAlert={vi.fn()} />)
    fireEvent.click(screen.getByText('Invite teammate'))
    fireEvent.change(screen.getByPlaceholderText('teammate@team.dev'), {
      target: { value: 'new@strider.dev' }
    })
    fireEvent.click(screen.getByText('Send invite'))
    expect(screen.getByText(/Sending…/)).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(1200)
    })
    expect(screen.getByText('new@strider.dev')).toBeInTheDocument()
    expect(screen.getByText('INVITE PENDING')).toBeInTheDocument()
    // Modal closed after send.
    expect(screen.queryByPlaceholderText('teammate@team.dev')).not.toBeInTheDocument()
  })
})

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
