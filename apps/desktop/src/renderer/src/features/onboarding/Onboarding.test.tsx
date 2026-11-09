import { StrictMode } from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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
import { endOnboardingReplay, isOnboardingReplay, startOnboardingReplay } from './onboardingReplay'

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
  return {
    ...actual,
    hydrateOnboarding: vi.fn(),
    persistOnboardingStep: vi.fn(),
    persistSolMode: vi.fn()
  }
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
  vi.mocked(sync.persistSolMode).mockResolvedValue(undefined)
  vi.mocked(buildProgress.runBuildProgress).mockResolvedValue({ lines: [] })
}

/** Walk from Meet to the given heading through the real buttons. */
async function walkTo(target: 'project' | 'voice' | 'access' | 'connect'): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: /Let’s set up/ }))
  if (target === 'project') return
  await userEvent.click(screen.getByRole('button', { name: /Continue|Skip — name it later/ }))
  if (target === 'voice') return
  await userEvent.click(screen.getByRole('button', { name: /^Use (Guide|Expert)/ }))
  if (target === 'access') return
  await userEvent.click(screen.getByRole('button', { name: /continue/i }))
}

describe('Onboarding flow — SOL walks you in (SOLUSDEV-323)', () => {
  beforeEach(setupOnboarding)

  it('opens on Meet with SOL introducing itself', async () => {
    await renderOnboarding()
    expect(screen.getByRole('heading', { name: 'Hi — I’m SOL.' })).toBeInTheDocument()
    expect(screen.getByText('MAYA@STRIDER.DEV')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Step 1 of 6' })).toBeInTheDocument()
  })

  it('walks Meet → Project → Voice → Access → Connect, persisting each step', async () => {
    await renderOnboarding()
    await walkTo('project')
    expect(screen.getByRole('heading', { name: 'What are you building?' })).toBeInTheDocument()
    expect(sync.persistOnboardingStep).toHaveBeenLastCalledWith('about')
    await userEvent.click(screen.getByRole('button', { name: /Skip — name it later/ }))
    expect(screen.getByRole('heading', { name: 'How should I talk to you?' })).toBeInTheDocument()
    expect(sync.persistOnboardingStep).toHaveBeenLastCalledWith('voice')
    await userEvent.click(screen.getByRole('button', { name: /^Use Guide/ }))
    expect(
      screen.getByRole('heading', { name: 'Want me to see what you see?' })
    ).toBeInTheDocument()
    expect(sync.persistOnboardingStep).toHaveBeenLastCalledWith('access')
    await userEvent.click(screen.getByRole('button', { name: /continue/i }))
    expect(screen.getByRole('heading', { name: 'Plug in your tools.' })).toBeInTheDocument()
    expect(sync.persistOnboardingStep).toHaveBeenLastCalledWith('connect')
    expect(screen.getByText('0 CONNECTED · 2+ RECOMMENDED')).toBeInTheDocument()
  })

  it('Back returns to the previous step', async () => {
    await renderOnboarding()
    await walkTo('voice')
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('heading', { name: 'What are you building?' })).toBeInTheDocument()
  })

  it('Skip setup finishes onboarding from any step after Meet', async () => {
    await renderOnboarding()
    expect(screen.queryByRole('button', { name: 'Skip setup' })).toBeNull()
    await walkTo('project')
    await userEvent.click(screen.getByRole('button', { name: 'Skip setup' }))
    await vi.waitFor(() => expect(useAuthStore.getState().onboarded).toBe(true))
    expect(sync.persistOnboardingStep).toHaveBeenCalledWith('done')
  })
})

describe('Onboarding flow — Project step', () => {
  beforeEach(setupOnboarding)

  it('records the project description and previews the real project name', async () => {
    await renderOnboarding()
    await walkTo('project')
    await userEvent.type(screen.getByLabelText('Project description'), 'Strider quadruped. ROS 2')
    expect(useOnboardingStore.getState().description).toBe('Strider quadruped. ROS 2')
    // The same name provisioning will create (deriveProjectName).
    expect(screen.getByLabelText('Project name')).toHaveValue('Strider quadruped')
  })

  it('lets the user edit the project name, which then stops following the description', async () => {
    await renderOnboarding()
    await walkTo('project')
    await userEvent.type(screen.getByLabelText('Project description'), 'Strider quadruped')
    const name = screen.getByLabelText('Project name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Strider MK2')
    expect(useOnboardingStore.getState().projectName).toBe('Strider MK2')
    await userEvent.type(screen.getByLabelText('Project description'), '. ROS 2')
    expect(name).toHaveValue('Strider MK2')
  })

  it('an example puts the name back to following the description', async () => {
    await renderOnboarding()
    await walkTo('project')
    await userEvent.type(screen.getByLabelText('Project name'), ' custom')
    await userEvent.click(screen.getByRole('button', { name: 'FSAE BMS' }))
    expect(useOnboardingStore.getState().projectName).toBeNull()
    expect(screen.getByLabelText('Project name')).toHaveValue(
      'An FSAE battery management board in KiCad with CAN telemetry to the pit laptop'
    )
  })

  it('lights the worlds it hears as you type', async () => {
    await renderOnboarding()
    await walkTo('project')
    const software = screen.getByText('Software').closest('[data-on]')
    expect(software).toHaveAttribute('data-on', 'false')
    await userEvent.type(screen.getByLabelText('Project description'), 'STM32 firmware')
    expect(software).toHaveAttribute('data-on', 'true')
    expect(screen.getByText('Mechanical').closest('[data-on]')).toHaveAttribute('data-on', 'false')
  })

  it('an example only fills the description — no template project (SOLUSDEV-152)', async () => {
    await renderOnboarding()
    await walkTo('project')
    await userEvent.click(screen.getByRole('button', { name: 'Robot arm' }))
    expect(useOnboardingStore.getState().description).toMatch(/robot arm/i)
    expect(provisioning.ensureWorkspace).not.toHaveBeenCalled()
    expect(screen.queryByText(/template robot/i)).toBeNull()
  })
})

describe('Onboarding flow — Voice step', () => {
  beforeEach(setupOnboarding)

  it('lets the user choose Expert SOL mode and previews the terse answer (ADR-016)', async () => {
    await renderOnboarding()
    await walkTo('voice')
    expect(screen.getByRole('radio', { name: /Guide/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText(/CONCEPT · I²C ADDRESSES/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: /Expert/ }))
    expect(useSettingsStore.getState().solMode).toBe('Expert')
    expect(screen.queryByText(/CONCEPT · I²C ADDRESSES/)).toBeNull()
    expect(screen.getByRole('button', { name: /^Use Expert/ })).toBeInTheDocument()
    // Saved to the server at once — Skip setup must not lose it (review #3).
    expect(sync.persistSolMode).toHaveBeenCalledWith('Expert')
  })

  it('moves between the voices with the arrow keys (radio group, roving focus)', async () => {
    await renderOnboarding()
    await walkTo('voice')
    const guide = screen.getByRole('radio', { name: /Guide/ })
    const expert = screen.getByRole('radio', { name: /Expert/ })
    expect(guide).toHaveAttribute('tabindex', '0')
    expect(expert).toHaveAttribute('tabindex', '-1')
    guide.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(useSettingsStore.getState().solMode).toBe('Expert')
    expect(expert).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(useSettingsStore.getState().solMode).toBe('Guide')
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
    await walkTo('connect')
    await userEvent.click(screen.getByRole('button', { name: 'Skip for now' }))

    expect(provisioning.ensureWorkspace).toHaveBeenCalledWith(
      expect.objectContaining({
        description: 'Strider quadruped',
        name: 'Strider quadruped',
        solMode: 'Guide'
      })
    )
    await vi.waitFor(() => {
      expect(useWorkspaceStore.getState().project).toMatchObject({ id: 'p1', name: 'Strider' })
    })
    expect(useWorkspaceStore.getState().linked).toBe(true)
    expect(sync.persistOnboardingStep).toHaveBeenLastCalledWith('build')
  })

  it('completes the build honestly with no fabricated log when offline', async () => {
    await renderOnboarding()
    await walkTo('connect')
    await userEvent.click(screen.getByRole('button', { name: 'Skip for now' }))

    await vi.waitFor(() => expect(useOnboardingStore.getState().buildDone).toBe(true))
    expect(buildProgress.runBuildProgress).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().buildLog).toEqual([])
    expect(screen.queryAllByTestId('ob-graph-node')).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: /Open workspace/ }))
    expect(useAuthStore.getState().onboarded).toBe(true)
    expect(useOnboardingStore.getState().landingHint).toBe(true)
  })
})

describe('Onboarding flow — server-persisted resume (FND-08)', () => {
  beforeEach(setupOnboarding)

  it('resumes mid-flow at the server-saved step after a reload', async () => {
    vi.mocked(sync.hydrateOnboarding).mockResolvedValue({ status: 'resume', step: 4 })
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>
    )
    expect(await screen.findByRole('heading', { name: 'Plug in your tools.' })).toBeInTheDocument()
    expect(useOnboardingStore.getState().step).toBe(4)
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
    expect(screen.queryByRole('heading', { name: 'Hi — I’m SOL.' })).toBeNull()
  })

  it('persists done on completion', async () => {
    useOnboardingStore.getState().setStep(5)
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
    useOnboardingStore.getState().setStep(5)
    await renderOnboarding(true)
    await vi.waitFor(() => expect(useOnboardingStore.getState().buildDone).toBe(true))
    expect(screen.getByRole('button', { name: /Open workspace/ })).toBeInTheDocument()
  })

  it('hydrates past the splash under StrictMode double-mounting', async () => {
    await renderOnboarding(true)
    expect(await screen.findByRole('heading', { name: 'Hi — I’m SOL.' })).toBeInTheDocument()
  })
})

describe('Onboarding flow — dev replay (pnpm dev:onboarding)', () => {
  beforeEach(setupOnboarding)
  afterEach(endOnboardingReplay)

  it('starts at Meet even when the server says onboarding is done', async () => {
    startOnboardingReplay()
    useOnboardingStore.getState().setStep(4)
    vi.mocked(sync.hydrateOnboarding).mockResolvedValue({ status: 'done' })
    await renderOnboarding()
    expect(screen.getByRole('heading', { name: 'Hi — I’m SOL.' })).toBeInTheDocument()
    expect(useOnboardingStore.getState().step).toBe(0)
    expect(useAuthStore.getState().onboarded).toBe(false)
  })

  it('ends the replay when the flow finishes, so the workspace stays reachable', async () => {
    startOnboardingReplay()
    await renderOnboarding()
    await walkTo('project')
    await userEvent.click(screen.getByRole('button', { name: 'Skip setup' }))
    await vi.waitFor(() => expect(useAuthStore.getState().onboarded).toBe(true))
    expect(isOnboardingReplay()).toBe(false)
  })
})

describe('Onboarding header — window chrome', () => {
  beforeEach(setupOnboarding)
  const w = window as unknown as { solus?: { platform?: string } }
  afterEach(() => {
    delete w.solus
  })

  it('clears the macOS traffic lights and drags the window, controls excluded', async () => {
    w.solus = { platform: 'darwin' }
    await renderOnboarding()
    const header = screen.getByTestId('ob-header')
    expect(header).toHaveAttribute('data-inset', 'mac')
    expect(header).toHaveClass('app-drag')
    await walkTo('project')
    expect(
      screen.getByRole('button', { name: 'Skip setup' }).closest('.app-no-drag')
    ).not.toBeNull()
  })

  it('shows no logo in the header — the macOS lights sit there alone', async () => {
    w.solus = { platform: 'darwin' }
    await renderOnboarding()
    expect(within(screen.getByTestId('ob-header')).queryByText('SOLUS')).toBeNull()
    expect(screen.getByTestId('ob-brand')).toHaveTextContent('SOLUS')
  })

  it('centres the macOS lights in its header while mounted, and restores them after', async () => {
    const setWindowChrome = vi.fn()
    ;(w as { solus?: Record<string, unknown> }).solus = { platform: 'darwin', setWindowChrome }
    const { unmount } = render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>
    )
    await screen.findByText('MAYA@STRIDER.DEV')
    expect(setWindowChrome).toHaveBeenLastCalledWith('onboarding')
    unmount()
    expect(setWindowChrome).toHaveBeenLastCalledWith('title')
  })

  it('keeps the plain inset off macOS', async () => {
    await renderOnboarding()
    expect(screen.getByTestId('ob-header')).toHaveAttribute('data-inset', 'none')
  })
})
