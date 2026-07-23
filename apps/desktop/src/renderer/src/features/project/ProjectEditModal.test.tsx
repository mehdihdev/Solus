// Edit-project modal (SOLUSDEV-164): rename and re-describe a project from its
// Overview hub.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectEditModal } from './ProjectEditModal'

describe('ProjectEditModal', () => {
  it('prefills the current name and description', () => {
    render(
      <ProjectEditModal
        initialName="Rover MK2"
        initialDescription="a quadruped"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />
    )
    expect(screen.getByLabelText('Project name')).toHaveValue('Rover MK2')
    expect(screen.getByLabelText('Description')).toHaveValue('a quadruped')
  })

  it('submits the edited name and description', async () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    const onClose = vi.fn()
    render(
      <ProjectEditModal
        initialName="Rover MK2"
        initialDescription=""
        onClose={onClose}
        onSubmit={onSubmit}
      />
    )
    const name = screen.getByLabelText('Project name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Rover MK3')
    await userEvent.type(screen.getByLabelText('Description'), 'a hexapod')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledWith('Rover MK3', 'a hexapod')
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('does not submit an empty name', async () => {
    const onSubmit = vi.fn().mockResolvedValue(true)
    render(
      <ProjectEditModal
        initialName="Rover MK2"
        initialDescription=""
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />
    )
    await userEvent.clear(screen.getByLabelText('Project name'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('keeps the modal open and shows an error when the save fails', async () => {
    const onSubmit = vi.fn().mockResolvedValue(false)
    const onClose = vi.fn()
    render(
      <ProjectEditModal
        initialName="Rover MK2"
        initialDescription=""
        onClose={onClose}
        onSubmit={onSubmit}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/couldn't save/i)).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
