// SOLUSDEV-319: the command card layout on its own (ConfirmationCard.command.test.tsx
// covers it inside the real card, with the decision and the keyboard approver).
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { CommandCard, type CommandCardProps } from './CommandApprovalCard'

const PENDING: PendingConfirmation = {
  confirmationId: 'c1',
  tool: 'code.run',
  summary: 'Run the self-test',
  preview: [
    { label: 'command', before: null, after: '["/usr/bin/make","selftest"]' },
    { label: 'cwd', before: null, after: '/w/SolCmdTest' }
  ]
}

function renderCard(overrides: Partial<CommandCardProps> = {}): CommandCardProps {
  const props: CommandCardProps = {
    pending: PENDING,
    header: { program: 'make', risks: ['project_scripts'], sandboxed: true },
    variant: 'card',
    busy: false,
    closed: false,
    shortcut: { hint: '⌘↵', aria: 'Meta+Enter' },
    onApprove: vi.fn(),
    onReject: vi.fn(),
    preview: <div>rows</div>,
    details: <div>details</div>,
    failure: null,
    ...overrides
  }
  render(<CommandCard {...props} />)
  return props
}

describe('CommandCard', () => {
  it('lays out status, the shell line, badges and the two decisions', () => {
    const props = renderCard()
    expect(screen.getByRole('status')).toHaveTextContent('Needs approval')
    expect(screen.getByLabelText('Command line')).toHaveTextContent('$make selftest')
    expect(screen.getByTitle('/w/SolCmdTest')).toHaveTextContent('SolCmdTest')
    expect(screen.getByText('sandboxed')).toBeInTheDocument()
    expect(screen.getByText('project_scripts')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run command' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(props.onApprove).toHaveBeenCalledTimes(1)
    expect(props.onReject).toHaveBeenCalledTimes(1)
  })

  it('in the pill names SOL as the asker and shortens the button', () => {
    renderCard({ variant: 'pill' })
    expect(screen.getByRole('status')).toHaveTextContent('SOL wants to run a command')
    expect(screen.getByRole('button', { name: 'Run' })).toHaveAttribute(
      'aria-keyshortcuts',
      'Meta+Enter'
    )
  })

  it('disables both decisions and hides the hint while recording', () => {
    renderCard({ busy: true })
    expect(screen.getByRole('status')).toHaveTextContent('Recording decision…')
    expect(screen.getByRole('button', { name: 'Starting…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    expect(screen.queryByText('⌘↵')).toBeNull()
  })

  it('says the approval is closed after a terminal refusal', () => {
    const view = { closed: true }
    renderCard(view)
    expect(screen.getByRole('status')).toHaveTextContent('Approval closed')
    expect(screen.getByRole('button', { name: 'Run command' })).toBeDisabled()
  })

  it('shows only the program when the command is chunked', () => {
    renderCard({
      pending: {
        ...PENDING,
        preview: [{ label: 'command 1/2', before: null, after: '["/usr/bin/make","-j8"' }]
      }
    })
    expect(screen.getByLabelText('Command line')).toHaveTextContent(/^\$make$/)
    expect(screen.queryByTitle('/w/SolCmdTest')).toBeNull()
  })

  it('carries its variant and state for styling and motion', () => {
    renderCard({ variant: 'pill', busy: true })
    const card = screen.getByRole('region', { name: 'Action needs your approval' })
    expect(card).toHaveAttribute('data-variant', 'pill')
    expect(card).toHaveAttribute('data-state', 'busy')
  })
})
