import { StrictMode } from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Onboarding } from './Onboarding'
import { useOnboardingStore } from './onboardingStore'
import { useSettingsStore } from '../../store/settingsStore'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as provisioning from './provisioning'
import * as sync from './onboardingSync'
import * as buildProgress from './buildProgress'

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

// The Build step reads real sync progress; its own tests cover the API. Here
// it resolves to the honest empty result so the flow completes offline.
vi.mock('./buildProgress', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./buildProgress')>()
  return { ...actual, runBuildProgress: vi.fn() }
})

async function renderOnboarding(strict = false): Promise<void> {
  const tree = (
    <MemoryRouter>
      <Onboarding />
    </MemoryRouter>
  )
  render(strict ? <StrictMode>{tree}</StrictMode> : tree)
  // The container shows a splash until the server step hydrates.
  await screen.findByText('MAYA@STRIDER.DEV')
}

function setupOnboarding(): void {
  vi.clearAllMocks()
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
  vi.mocked(buildProgress.runBuildProgress).mockResolvedValue({ lines: [] })
}

describe('Onboarding flow — navigation', () => {
  beforeEach(setupOnboarding)

  it('opens on the About step', async () => {
    await renderOnboarding()
    expect(screen.getByRole('heading', { name: 'What are you building?' })).toBeInTheDocument()
    expect(screen.getByText('MAYA@STRIDER.DEV')).toBeInTheDocument()
  })

  it('offers no template robots — real sources are the only path', async () => {
    await renderOnboarding()
    expect(screen.queryByText(/template robot/i)).toBeNull()
    expect(screen.queryByText('Quadruped')).toBeNull()
    expect(screen.queryByText(/STARTING POINT/)).toBeNull()
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

  it('Continue advances to the Connect step', async () => {
    await renderOnboarding()
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    expect(screen.getByRole('heading', { name: 'Connect your tools' })).toBeInTheDocument()
    expect(screen.getByText('0 OF 2 CONNECTED (2+ RECOMMENDED)')).toBeInTheDocument()
  })
})

describe('Onboarding flow — build + provisioning', () => {
  beforeEach(setupOnboarding)

  it('provisions the real workspace when the build begins (Maximal wiring)', async () => {
    vi.mocked(provisioning.ensureWorkspace).mockResolvedValue({
      linked: true,
      teamId: 't1',
      project: { id: 'p1', name: 'Strider' }
    })
    useOnboardingStore.getState().setDescription('Strider quadruped')
    await renderOnboarding()
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Skip for now' }))

    expect(provisioning.ensureWorkspace).toHaveBeenCalledWith(
      expect.objectContaining({ description: 'Strider quadruped', solMode: 'Guide' })
    )
    // The async provision result lands in the workspace store.
    await vi.waitFor(() => {
      expect(useWorkspaceStore.getState().project).toEqual({ id: 'p1', name: 'Strider' })
    })
    expect(useWorkspaceStore.getState().linked).toBe(true)
  })

  it('completes the build honestly with no fabricated log when offline', async () => {
    await renderOnboarding()
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Skip for now' }))

    await vi.waitFor(() => expect(useOnboardingStore.getState().buildDone).toBe(true))
    // Unlinked workspace: no API reads, no invented numbers.
    expect(buildProgress.runBuildProgress).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().buildLog).toEqual([])
    expect(screen.queryByText(/247 nodes/)).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: /Open workspace/ }))
    expect(useAuthStore.getState().onboarded).toBe(true)
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
    expect(await screen.findByRole('heading', { name: 'Connect your tools' })).toBeInTheDocument()
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
    useOnboardingStore.getState().setStep(2)
    await renderOnboarding()
    await vi.waitFor(() => expect(useOnboardingStore.getState().buildDone).toBe(true))
    await userEvent.click(screen.getByRole('button', { name: /Open workspace/ }))
    expect(sync.persistOnboardingStep).toHaveBeenCalledWith('done')
    expect(useAuthStore.getState().onboarded).toBe(true)
  })
})

describe('Onboarding flow — StrictMode', () => {
  beforeEach(setupOnboarding)

  it('finishes the build under StrictMode double-mounting', async () => {
    // Regression: the Build step must re-run its progress read on every mount
    // (StrictMode cleanup cancels the first run) or it never completes.
    useOnboardingStore.getState().setStep(2)
    await renderOnboarding(true)
    await vi.waitFor(() => expect(useOnboardingStore.getState().buildDone).toBe(true))
    expect(screen.getByRole('button', { name: /Open workspace/ })).toBeInTheDocument()
  })

  it('hydrates past the splash under StrictMode double-mounting', async () => {
    // Regression: a once-only ref guard + cancelled-cleanup combination left
    // the second StrictMode mount with no hydration and an eternal spinner.
    await renderOnboarding(true)
    expect(
      await screen.findByRole('heading', { name: 'What are you building?' })
    ).toBeInTheDocument()
  })
})
