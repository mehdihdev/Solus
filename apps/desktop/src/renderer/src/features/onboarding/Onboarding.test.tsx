import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Onboarding } from './Onboarding'
import { useOnboardingStore } from './onboardingStore'
import { useSettingsStore } from '../../store/settingsStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as provisioning from './provisioning'

// Keep provisioning deterministic and offline; its own unit tests cover the API.
// ConnectStep also calls ensureWorkspace on mount, so both entry points are
// mocked here.
vi.mock('./provisioning', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./provisioning')>()
  return { ...actual, ensureWorkspace: vi.fn(), provisionWorkspace: vi.fn() }
})

function renderOnboarding(): void {
  render(
    <MemoryRouter>
      <Onboarding />
    </MemoryRouter>
  )
}

function setupOnboarding(): void {
  useOnboardingStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useSettingsStore.setState({ solMode: 'Guide' })
  useAuthStore.setState({
    status: 'authenticated',
    user: { email: 'maya@strider.dev' },
    onboarded: false
  })
  vi.mocked(provisioning.ensureWorkspace).mockResolvedValue({ linked: false })
}

describe('Onboarding flow — navigation', () => {
  beforeEach(setupOnboarding)

  it('opens on the About step', () => {
    renderOnboarding()
    expect(screen.getByRole('heading', { name: 'What are you building?' })).toBeInTheDocument()
    expect(screen.getByText('MAYA@STRIDER.DEV')).toBeInTheDocument()
  })

  it('records the project description', async () => {
    renderOnboarding()
    await userEvent.type(screen.getByLabelText('Project description'), 'a quadruped')
    expect(useOnboardingStore.getState().description).toBe('a quadruped')
  })

  it('lets the user choose Expert SOL mode (ADR-016)', async () => {
    renderOnboarding()
    await userEvent.click(screen.getByRole('radio', { name: 'Expert' }))
    expect(useSettingsStore.getState().solMode).toBe('Expert')
  })

  it('connect path advances to the Connect step', async () => {
    renderOnboarding()
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    expect(screen.getByRole('heading', { name: 'Connect your tools' })).toBeInTheDocument()
    expect(screen.getByText('0 OF 4 CONNECTED (NEED 2+)')).toBeInTheDocument()
  })
})

describe('Onboarding flow — build + provisioning', () => {
  beforeEach(setupOnboarding)

  it('template path pre-connects sources and jumps to Build', async () => {
    renderOnboarding()
    await userEvent.click(screen.getByText('Start from a template robot'))
    await userEvent.click(screen.getByText('Quadruped'))
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    expect(useOnboardingStore.getState().step).toBe(2)
    expect(Object.keys(useOnboardingStore.getState().connections)).toHaveLength(4)
    expect(screen.getByRole('heading', { name: /Building your context model/ })).toBeInTheDocument()
  })

  it('disables Continue on the template path until a robot is picked', async () => {
    renderOnboarding()
    await userEvent.click(screen.getByText('Start from a template robot'))
    expect(screen.getByRole('button', { name: /Continue/ })).toBeDisabled()
  })

  it('provisions the real workspace when the build begins (Maximal wiring)', async () => {
    vi.mocked(provisioning.ensureWorkspace).mockResolvedValue({
      linked: true,
      teamId: 't1',
      project: { id: 'p1', name: 'Strider' }
    })
    useOnboardingStore.getState().setDescription('Strider quadruped')
    renderOnboarding()
    await userEvent.click(screen.getByText('Start from a template robot'))
    await userEvent.click(screen.getByText('Quadruped'))
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))

    expect(provisioning.ensureWorkspace).toHaveBeenCalledWith({
      description: 'Strider quadruped',
      solMode: 'Guide',
      existing: { teamId: null, project: null }
    })
    // The async provision result lands in the workspace store.
    await vi.waitFor(() => {
      expect(useWorkspaceStore.getState().project).toEqual({ id: 'p1', name: 'Strider' })
    })
    expect(useWorkspaceStore.getState().linked).toBe(true)
  })

  it('finishes the build and marks onboarding complete', async () => {
    vi.useFakeTimers()
    try {
      useOnboardingStore.getState().setStep(2)
      renderOnboarding()
      await act(async () => {
        vi.advanceTimersByTime(8000)
      })
      expect(useOnboardingStore.getState().buildDone).toBe(true)
      const openButton = screen.getByRole('button', { name: /Open workspace/ })
      await act(async () => {
        openButton.click()
      })
      expect(useAuthStore.getState().onboarded).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })
})
