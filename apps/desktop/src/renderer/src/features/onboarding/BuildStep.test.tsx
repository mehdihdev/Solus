// The Build step never fabricates results (SOLUSDEV-152): it streams REAL sync
// progress via buildProgress, shows the real entity count, and completes with
// an honest empty state when the workspace never linked (offline/dev bypass).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BuildStep } from './BuildStep'
import { useOnboardingStore, type BuildLine } from './onboardingStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as buildProgress from './buildProgress'

vi.mock('./buildProgress', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./buildProgress')>()
  return { ...actual, runBuildProgress: vi.fn() }
})

const mockedRun = vi.mocked(buildProgress.runBuildProgress)

beforeEach(() => {
  useOnboardingStore.getState().reset()
  useWorkspaceStore.getState().reset()
  vi.clearAllMocks()
  mockedRun.mockResolvedValue({ lines: [] })
})

afterEach(() => {
  vi.restoreAllMocks()
})

function linkWorkspace(): void {
  useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'X' }, linked: true })
}

describe('BuildStep — unlinked workspace (offline/dev bypass)', () => {
  it('completes immediately with an honest empty state and never calls the API', async () => {
    await act(async () => {
      render(<BuildStep onComplete={vi.fn()} />)
    })
    expect(mockedRun).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().buildDone).toBe(true)
    expect(screen.getByText(/No sources are syncing/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open workspace/ })).toBeInTheDocument()
    // The fabricated summary is gone for good.
    expect(screen.queryByText(/247 nodes/)).toBeNull()
    expect(screen.queryByText(/cross-domain links/)).toBeNull()
  })

  it('lets the user open the workspace', async () => {
    const onComplete = vi.fn()
    await act(async () => {
      render(<BuildStep onComplete={onComplete} />)
    })
    await userEvent.click(screen.getByRole('button', { name: /Open workspace/ }))
    expect(onComplete).toHaveBeenCalledTimes(1)
  })
})

describe('BuildStep — linked workspace (real sync progress)', () => {
  it('streams the real per-source sync lines and the real entity count', async () => {
    linkWorkspace()
    const lines: BuildLine[] = [
      { name: 'strider-fw', detail: '214 entities · 12 relations', state: 'ok' },
      { name: 'power-board', detail: 'Bad netlist header', state: 'failed' }
    ]
    mockedRun.mockImplementation(async (deps) => {
      deps.onLines(lines)
      return { lines, entityCount: 226 }
    })

    await act(async () => {
      render(<BuildStep onComplete={vi.fn()} />)
    })

    expect(mockedRun).toHaveBeenCalledTimes(1)
    expect(mockedRun.mock.calls[0][1]).toBe('p1')
    expect(screen.getByText('strider-fw')).toBeInTheDocument()
    expect(screen.getByText('214 entities · 12 relations')).toBeInTheDocument()
    // A failed sync is shown honestly, not hidden behind a checkmark.
    expect(screen.getByText('Bad netlist header')).toBeInTheDocument()
    // The real graph count replaces the fabricated echo.
    expect(screen.getByText(/226 entities in your graph/i)).toBeInTheDocument()
    expect(useOnboardingStore.getState().buildDone).toBe(true)
    expect(useOnboardingStore.getState().buildEntityCount).toBe(226)
  })

  it('shows an honest done state when the project has no sources', async () => {
    linkWorkspace()
    mockedRun.mockResolvedValue({ lines: [] })

    await act(async () => {
      render(<BuildStep onComplete={vi.fn()} />)
    })

    expect(useOnboardingStore.getState().buildDone).toBe(true)
    expect(screen.getByText(/No sources are syncing/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open workspace/ })).toBeInTheDocument()
  })

  it('stays honest when the progress read itself fails', async () => {
    linkWorkspace()
    mockedRun.mockResolvedValue({ lines: [], error: 'API unreachable' })

    await act(async () => {
      render(<BuildStep onComplete={vi.fn()} />)
    })

    // Still completes (the workspace is never gated) with no fabricated log.
    expect(useOnboardingStore.getState().buildDone).toBe(true)
    expect(useOnboardingStore.getState().buildLog).toEqual([])
    expect(screen.getByRole('button', { name: /Open workspace/ })).toBeInTheDocument()
  })
})
