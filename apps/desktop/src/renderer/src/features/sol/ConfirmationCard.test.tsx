// The approval surface. What matters here is that a user can see WHAT they are
// approving — a bare tool name is not meaningful consent — and that a failed
// decision never looks like a successful one.
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { ConfirmationCard } from './ConfirmationCard'

const PENDING: PendingConfirmation = {
  confirmationId: 'c1',
  tool: 'onshape.set_variable',
  summary: 'Change a Variable Studio value (onshape.set_variable) with name=’width’',
  preview: [{ label: 'width', before: '100 mm', after: '120 mm' }]
}

describe('ConfirmationCard', () => {
  it('shows the diff, not just the action name', () => {
    render(<ConfirmationCard pending={PENDING} onDecide={vi.fn()} />)

    expect(screen.getByText('width')).toBeInTheDocument()
    expect(screen.getByText('100 mm')).toBeInTheDocument()
    expect(screen.getByText('120 mm')).toBeInTheDocument()
  })

  it('names the tool so the user knows what is acting', () => {
    render(<ConfirmationCard pending={PENDING} onDecide={vi.fn()} />)

    expect(screen.getByText('onshape.set_variable')).toBeInTheDocument()
  })

  it('renders any tool’s rows — it is not Onshape-specific', () => {
    const firmware: PendingConfirmation = {
      confirmationId: 'c2',
      tool: 'arduino.flash',
      summary: 'Flash firmware to the connected board',
      preview: [{ label: 'sketch', before: 'blink v3', after: 'blink v4' }]
    }

    render(<ConfirmationCard pending={firmware} onDecide={vi.fn()} />)

    expect(screen.getByText('arduino.flash')).toBeInTheDocument()
    expect(screen.getByText('blink v4')).toBeInTheDocument()
  })

  it('says so when a tool could not describe its change', () => {
    // Rare now — the server falls back to the arguments — but if even that is
    // absent the card must not imply a diff was checked.
    render(<ConfirmationCard pending={{ ...PENDING, preview: [] }} onDecide={vi.fn()} />)

    expect(screen.getByText(/could not describe its change/)).toBeInTheDocument()
  })

  it('approves through the callback', async () => {
    const onDecide = vi.fn(async () => {})
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(onDecide).toHaveBeenCalledWith('approve'))
  })

  it('rejects through the callback', async () => {
    // The card reports the decision and stops there; the host removes it. A
    // local "done" state here would claim an outcome the card cannot observe.
    const onDecide = vi.fn(async () => {})
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Reject' }))

    await waitFor(() => expect(onDecide).toHaveBeenCalledWith('reject'))
  })

  it('cannot be double-submitted while a decision is in flight', async () => {
    let release = (): void => {}
    const onDecide = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          release = resolve
        })
    )
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    await act(async () => release())
  })

  it('a failed decision does not look like a successful one', async () => {
    const onDecide = vi.fn(async () => {
      throw new Error('offline')
    })
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    expect(await screen.findByText(/offline/)).toBeInTheDocument()
    // ...and the user can try again.
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
  })

  it('never shouts the value — case is part of what executes', () => {
    // Onshape variable names and FeatureScript unit tokens are case-sensitive.
    // A card that paints `#WIDTH * 2` shows an expression that is not the one
    // being approved.
    render(<ConfirmationCard pending={PENDING} onDecide={vi.fn()} />)

    for (const text of ['width', '100 mm', '120 mm']) {
      const node = screen.getByText(text)
      expect(getComputedStyle(node).textTransform).not.toBe('uppercase')
    }
  })

  it('does not assume the action is a design change', () => {
    // The same gate carries CAD edits, robot control and shell commands.
    const shell: PendingConfirmation = {
      confirmationId: 'c3',
      tool: 'delphiscript.run_script',
      summary: 'Executes a script on the customer machine',
      preview: [{ label: 'command', before: null, after: 'rm -rf /tmp/build' }]
    }

    const { container } = render(<ConfirmationCard pending={shell} onDecide={vi.fn()} />)

    expect(container.textContent).not.toMatch(/your design/i)
    expect(screen.getByText('rm -rf /tmp/build')).toBeInTheDocument()
  })

  it('shows the reason a decision was refused, not a generic apology', async () => {
    const onDecide = vi.fn(async () => {
      throw new Error('What this action would do has changed since it was shown to you.')
    })
    render(<ConfirmationCard pending={PENDING} onDecide={onDecide} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    expect(await screen.findByText(/has changed since it was shown/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
  })
})
