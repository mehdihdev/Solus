// SOLUSDEV-233: custom-instruction load/save with revert-on-failure.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useCustomInstruction } from './useCustomInstruction'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getSettings: vi.fn(), updateCustomInstruction: vi.fn() }
})
const getSettings = vi.mocked(resources.getSettings)
const updateCustomInstruction = vi.mocked(resources.updateCustomInstruction)

const SETTINGS: resources.UserSettings = {
  sol_mode: 'guide',
  sol_custom_instruction: 'Prefer metric units.',
  data_collection_consent: false,
  onboarding_step: 'done'
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true })
  getSettings.mockResolvedValue(SETTINGS)
})

describe('useCustomInstruction', () => {
  it('loads the saved note', async () => {
    const { result } = renderHook(() => useCustomInstruction())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.instruction).toBe('Prefer metric units.')
  })

  it('saves optimistically and clears with null', async () => {
    updateCustomInstruction.mockResolvedValue(SETTINGS)
    const { result } = renderHook(() => useCustomInstruction())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.save('Flag servo limits.  ')).toBe(true)
    })
    expect(updateCustomInstruction).toHaveBeenCalledWith('Flag servo limits.')
    expect(result.current.instruction).toBe('Flag servo limits.')
    await act(async () => {
      expect(await result.current.save('   ')).toBe(true)
    })
    expect(updateCustomInstruction).toHaveBeenLastCalledWith(null)
    expect(result.current.instruction).toBeNull()
  })

  it('reverts when the save fails', async () => {
    updateCustomInstruction.mockRejectedValue(new Error('422'))
    const { result } = renderHook(() => useCustomInstruction())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      expect(await result.current.save('New note')).toBe(false)
    })
    expect(result.current.instruction).toBe('Prefer metric units.')
  })

  it('is offline when the workspace is not linked', async () => {
    useWorkspaceStore.setState({ linked: false })
    const { result } = renderHook(() => useCustomInstruction())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(getSettings).not.toHaveBeenCalled()
  })
})
