// Shared workspace modals: submit round-trips, error surfacing, close behavior.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NameModal, JoinTeamModal, DeleteConfirmModal, ModalShell } from './modals'

describe('ModalShell', () => {
  it('carries the entrance-motion classes on backdrop and card (SOLUSDEV-233)', () => {
    const { container } = render(
      <ModalShell onClose={vi.fn()}>
        <div>body</div>
      </ModalShell>
    )
    expect(container.querySelector('.modal-backdrop-in')).not.toBeNull()
    expect(container.querySelector('.modal-card-in')).not.toBeNull()
  })
})

describe('NameModal', () => {
  it('submits the trimmed value and closes on success', async () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    const onClose = vi.fn()
    render(<NameModal title="New team" label="Team name" onClose={onClose} onSubmit={onSubmit} />)
    fireEvent.change(screen.getByLabelText('Team name'), { target: { value: '  Rockets  ' } })
    fireEvent.click(screen.getByText('Create'))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('Rockets'))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('shows the error text and stays open when submit fails', async () => {
    const onSubmit = vi.fn().mockResolvedValue(false)
    const onClose = vi.fn()
    render(
      <NameModal
        title="New team"
        label="Team name"
        errorText="Nope."
        onClose={onClose}
        onSubmit={onSubmit}
      />
    )
    fireEvent.change(screen.getByLabelText('Team name'), { target: { value: 'X' } })
    fireEvent.click(screen.getByText('Create'))
    await waitFor(() => expect(screen.getByText('Nope.')).toBeInTheDocument())
    expect(onClose).not.toHaveBeenCalled()
  })

  it('does not submit a blank name', () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    render(<NameModal title="t" label="Name" onClose={vi.fn()} onSubmit={onSubmit} />)
    fireEvent.click(screen.getByText('Create'))
    expect(onSubmit).not.toHaveBeenCalled()
  })
})

describe('JoinTeamModal', () => {
  it('joins with the trimmed token and closes on success', async () => {
    const onJoin = vi.fn().mockResolvedValue(true)
    const onClose = vi.fn()
    render(<JoinTeamModal onClose={onClose} onJoin={onJoin} />)
    fireEvent.change(screen.getByLabelText('Invite token'), { target: { value: ' tok ' } })
    fireEvent.click(screen.getByText('Join'))
    await waitFor(() => expect(onJoin).toHaveBeenCalledWith('tok'))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('surfaces an error when the token is rejected', async () => {
    const onJoin = vi.fn().mockResolvedValue(false)
    render(<JoinTeamModal onClose={vi.fn()} onJoin={onJoin} />)
    fireEvent.change(screen.getByLabelText('Invite token'), { target: { value: 'bad' } })
    fireEvent.click(screen.getByText('Join'))
    await waitFor(() => expect(screen.getByText(/Couldn't join/)).toBeInTheDocument())
  })
})

describe('DeleteConfirmModal', () => {
  it('confirms deletion and closes on success', async () => {
    const onConfirm = vi.fn().mockResolvedValue(true)
    const onClose = vi.fn()
    render(<DeleteConfirmModal name="Rover" onClose={onClose} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete project' }))
    await waitFor(() => expect(onConfirm).toHaveBeenCalled())
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})

describe('named refusals (SOLUSDEV-244 / HOME H5)', () => {
  it('NameModal shows a plan limit with the upgrade path instead of "try again"', async () => {
    const onUpgrade = vi.fn()
    const onSubmit = vi
      .fn()
      .mockResolvedValue({ message: "You're at your collaborative-team limit.", upgrade: true })
    render(
      <NameModal
        title="New team"
        label="Team name"
        onClose={vi.fn()}
        onSubmit={onSubmit}
        onUpgrade={onUpgrade}
      />
    )
    await userEvent.type(screen.getByLabelText('Team name'), 'Rockets')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(await screen.findByTestId('plan-limit')).toHaveTextContent('collaborative-team limit')
    await userEvent.click(screen.getByRole('button', { name: 'Upgrade' }))
    expect(onUpgrade).toHaveBeenCalled()
  })

  it('JoinTeamModal names why a token was refused', async () => {
    const onJoin = vi.fn().mockResolvedValue({ message: 'This invite has expired.' })
    render(<JoinTeamModal onClose={vi.fn()} onJoin={onJoin} />)
    await userEvent.type(screen.getByLabelText('Invite token'), 'tok')
    await userEvent.click(screen.getByRole('button', { name: 'Join' }))
    expect(await screen.findByText('This invite has expired.')).toBeInTheDocument()
    expect(screen.queryByTestId('plan-limit')).toBeNull()
  })
})
