import { StrictMode } from 'react'
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
import * as sync from './onboardingSync'

// Keep provisioning deterministic and offline; its own unit tests cover the API.
// ConnectStep also calls ensureWorkspace on mount, so both entry points are
// mocked here.
vi.mock('./provisioning', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./provisioning')>()
  return { ...actual, ensureWorkspace: vi.fn(), provisionWorkspace: vi.fn() }
})

// Server-side step persistence (FND-08) is unit-tested in onboardingSync.test;
// here it defaults to the offline path so the flow behaves like dev bypass.
vi.mock('./onboardingSync', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./onboardingSync')>()
  return { ...actual, hydrateOnboarding: vi.fn(), persistOnboardingStep: vi.fn() }
})

async function renderOnboarding(): Promise<void> {
  render(
    <MemoryRouter>
      <Onboarding />
    </MemoryRouter>
  )
  // The container shows a splash until the server step hydrates.
  await screen.findByText('MAYA@STRIDER.DEV')
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
  vi.mocked(sync.hydrateOnboarding).mockResolvedValue({ status: 'offline' })
  vi.mocked(sync.persistOnboardingStep).mockResolvedValue(undefined)
}

describe('Onboarding flow — navigation', () => {
  beforeEach(setupOnboarding)

  it('opens on the About step', async () => {
    await renderOnboarding()
    expect(screen.getByRole('heading', { name: 'What are you building?' })).toBeInTheDocument()
    expect(screen.getByText('MAYA@STRIDER.DEV')).toBeInTheDocument()
  })

  it('records the project description', async () => {
    await renderOnboarding()
    await userEvent.type(screen.getByLabelText('Project description'), 'a quadruped')
    expect(useOnboardingStore.getState().description).toBe('a quadruped')
  })

  it('lets the user choose Expert SOL mode (ADR-016)', async () => {
    await renderOnboarding()
    await userEvent.click(screen.getByRole('radio', { name: 'Expert' }))
    expect(useSettingsStore.getState().solMode).toBe('Expert')
  })

  it('connect path advances to the Connect step', async () => {
    await renderOnboarding()
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    expect(screen.getByRole('heading', { name: 'Connect your tools' })).toBeInTheDocument()
    expect(screen.getByText('0 OF 4 CONNECTED (2+ RECOMMENDED)')).toBeInTheDocument()
  })
})

describe('Onboarding flow — build + provisioning', () => {
  beforeEach(setupOnboarding)

  it('template path pre-connects sources and jumps to Build', async () => {
    await renderOnboarding()
    await userEvent.click(screen.getByText('Start from a template robot'))
    await userEvent.click(screen.getByText('Quadruped'))
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    expect(useOnboardingStore.getState().step).toBe(2)
    expect(Object.keys(useOnboardingStore.getState().connections)).toHaveLength(4)
    expect(screen.getByRole('heading', { name: /Building your context model/ })).toBeInTheDocument()
  })

  it('disables Continue on the template path until a robot is picked', async () => {
    await renderOnboarding()
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
    await renderOnboarding()
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
      // findBy* polls with timers, which are frozen here — render manually and
      // flush the hydration microtask instead.
      render(
        <MemoryRouter>
          <Onboarding />
        </MemoryRouter>
      )
      await act(async () => {})
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


describe('Onboarding flow — server-persisted resume (FND-08)', () => {
  beforeEach(setupOnboarding)

  it('resumes mid-flow at the server-saved step after a reload', async () => {
    vi.mocked(sync.hydrateOnboarding).mockResolvedValue({ status: 'resume', step: 1 })
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>
    )
    expect(
      await screen.findByRole('heading', { name: 'Connect your tools' })
    ).toBeInTheDocument()
    expect(useOnboardingStore.getState().step).toBe(1)
  })

  it('sends a server-side-done user straight to the workspace', async () => {
    vi.mocked(sync.hydrateOnboarding).mockResolvedValue({ status: 'done' })
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>
    )
    await vi.waitFor(() => {
      expect(useAuthStore.getState().onboarded).toBe(true)
    })
    // Never renders the flow — the user lands on the homepage route instead.
    expect(screen.queryByRole('heading', { name: 'What are you building?' })).toBeNull()
  })

  it('persists each step transition', async () => {
    await renderOnboarding()
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    expect(sync.persistOnboardingStep).toHaveBeenCalledWith('connect')
  })

  it('persists done on completion', async () => {
    vi.useFakeTimers()
    try {
      useOnboardingStore.getState().setStep(2)
      render(
        <MemoryRouter>
          <Onboarding />
        </MemoryRouter>
      )
      await act(async () => {})
      await act(async () => {
        vi.advanceTimersByTime(8000)
      })
      const openButton = screen.getByRole('button', { name: /Open workspace/ })
      await act(async () => {
        openButton.click()
      })
      expect(sync.persistOnboardingStep).toHaveBeenCalledWith('done')
      expect(useAuthStore.getState().onboarded).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })
})


describe('Onboarding flow — StrictMode', () => {
  beforeEach(setupOnboarding)

  it('finishes the build under StrictMode (timers rescheduled on remount)', async () => {
    // Regression: BuildStep's once-only ref left the second StrictMode mount
    // with no timers (the first mount's cleanup cleared them) — the build spun
    // on "working…" forever and Open workspace never appeared.
    vi.useFakeTimers()
    try {
      useOnboardingStore.getState().setStep(2)
      render(
        <StrictMode>
          <MemoryRouter>
            <Onboarding />
          </MemoryRouter>
        </StrictMode>
      )
      await act(async () => {})
      await act(async () => {
        vi.advanceTimersByTime(8000)
      })
      expect(useOnboardingStore.getState().buildDone).toBe(true)
      expect(screen.getByRole('button', { name: /Open workspace/ })).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('hydrates past the splash under StrictMode double-mounting', async () => {
    // Regression: a once-only ref guard + cancelled-cleanup combination left
    // the second StrictMode mount with no hydration and an eternal spinner.
    render(
      <StrictMode>
        <MemoryRouter>
          <Onboarding />
        </MemoryRouter>
      </StrictMode>
    )
    expect(
      await screen.findByRole('heading', { name: 'What are you building?' })
    ).toBeInTheDocument()
  })
})
