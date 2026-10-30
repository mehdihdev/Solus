// CUSTOM INSTRUCTIONS: the per-account standing instruction, labelled as such.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { CustomInstructionCard } from './CustomInstructionCard'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getSettings: vi.fn(), updateCustomInstruction: vi.fn() }
})
const getSettings = vi.mocked(resources.getSettings)
const updateCustomInstruction = vi.mocked(resources.updateCustomInstruction)

const SETTINGS: resources.UserSettings = {
  sol_mode: 'guide',
  sol_custom_instruction: null,
  data_collection_consent: false,
  onboarding_step: 'done'
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true })
  getSettings.mockResolvedValue(SETTINGS)
})

describe('CustomInstructionCard', () => {
  it('says the instruction applies account-wide, and adds then saves one', async () => {
    updateCustomInstruction.mockResolvedValue(SETTINGS)
    render(<CustomInstructionCard />)
    expect(screen.getByText('CUSTOM INSTRUCTIONS')).toBeInTheDocument()
    expect(screen.getByText(/Applies to every chat on this account/)).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Add' }))
    await userEvent.type(screen.getByLabelText('Custom instruction'), 'Prefer metric units.')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(updateCustomInstruction).toHaveBeenCalledWith('Prefer metric units.')
    )
    expect(screen.getByText('Prefer metric units.')).toBeInTheDocument()
  })

  it('keeps the editor open with an error when the save fails', async () => {
    updateCustomInstruction.mockRejectedValue(new Error('422'))
    render(<CustomInstructionCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add' }))
    await userEvent.type(screen.getByLabelText('Custom instruction'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/Couldn.t save/)).toBeInTheDocument()
    expect(screen.getByLabelText('Custom instruction')).toBeInTheDocument()
  })
})
