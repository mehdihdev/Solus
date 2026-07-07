import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectStep } from './ConnectStep'
import { useOnboardingStore } from './onboardingStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSettingsStore } from '../../store/settingsStore'
import * as provisioning from './provisioning'
import * as githubConnect from './githubConnect'
import * as bridgeModule from '../../lib/desktopBridge'
import type { GithubRepo } from '../../lib/api/resources'

vi.mock('./provisioning', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./provisioning')>()
  return { ...actual, ensureWorkspace: vi.fn() }
})

vi.mock('./githubConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./githubConnect')>()
  return { ...actual, runGithubConnect: vi.fn() }
})

const mockedEnsure = vi.mocked(provisioning.ensureWorkspace)
const mockedRun = vi.mocked(githubConnect.runGithubConnect)

function reset(): void {
  useOnboardingStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useSettingsStore.setState({ solMode: 'Guide' })
  vi.clearAllMocks()
  mockedEnsure.mockResolvedValue({ linked: false })
  mockedRun.mockResolvedValue({ ok: true })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ConnectStep — workspace bootstrap', () => {
  beforeEach(reset)

  it('ensures a workspace on mount, reusing any existing project', async () => {
    useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'X' }, linked: true })
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    expect(mockedEnsure).toHaveBeenCalledWith({
      description: '',
      solMode: 'Guide',
      existing: { teamId: 't1', project: { id: 'p1', name: 'X' } }
    })
  })
})

describe('ConnectStep — GitHub routing', () => {
  beforeEach(reset)

  it('drives the REAL connector when linked + bridge present', async () => {
    const bridge = {
      getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
      awaitGithub: vi.fn(async () => ({ code: 'cd' }))
    }
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(bridge)
    mockedEnsure.mockResolvedValue({ linked: true, teamId: 't1', project: { id: 'p1', name: 'X' } })

    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    // The mount effect linked the workspace.
    await vi.waitFor(() => expect(useWorkspaceStore.getState().linked).toBe(true))

    await userEvent.click(screen.getByText('GitHub'))

    await vi.waitFor(() => expect(mockedRun).toHaveBeenCalledTimes(1))
    const [, projectId, options] = mockedRun.mock.calls[0]
    expect(projectId).toBe('p1')
    expect(options).toEqual({ redirectUri: 'http://127.0.0.1:9/cb' })
  })

  it('falls back to the SIMULATED tile when there is no bridge (dev/web)', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    mockedEnsure.mockResolvedValue({ linked: true, teamId: 't1', project: { id: 'p1', name: 'X' } })

    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    await userEvent.click(screen.getByText('GitHub'))

    expect(mockedRun).not.toHaveBeenCalled()
    // The simulated flow marks the tile busy immediately.
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')
  })

  it('falls back to simulated when the workspace never linked', async () => {
    const bridge = {
      getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
      awaitGithub: vi.fn(async () => ({ code: 'cd' }))
    }
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(bridge)
    mockedEnsure.mockResolvedValue({ linked: false })

    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    await userEvent.click(screen.getByText('GitHub'))

    expect(mockedRun).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')
  })

  it('renders a repo picker when a busy github state carries repos', async () => {
    const repos: GithubRepo[] = [
      { full_name: 'a/one', default_branch: 'main', private: false },
      { full_name: 'a/two', default_branch: 'main', private: false }
    ]
    useOnboardingStore.getState().setConnection('github', {
      phase: 'busy',
      stepIdx: 0,
      label: 'Choose a repository to index…',
      sourceId: 's1',
      repos
    })
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    const picker = await screen.findByLabelText('Choose a repository')
    expect(picker).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'a/two' })).toBeInTheDocument()
  })
})

describe('ConnectStep — skip path (FND-08)', () => {
  beforeEach(reset)

  it('offers Skip for now with zero connections and it triggers the build', async () => {
    const onBuild = vi.fn()
    await act(async () => {
      render(<ConnectStep onBuild={onBuild} />)
    })
    const skip = screen.getByRole('button', { name: 'Skip for now' })
    expect(skip).toBeEnabled()
    await userEvent.click(skip)
    expect(onBuild).toHaveBeenCalledTimes(1)
  })

  it('keeps the primary build button gated until enough sources connect', async () => {
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    expect(screen.getByRole('button', { name: /Build context model/ })).toBeDisabled()
  })

  it('hides Skip once the recommended sources are connected', async () => {
    useOnboardingStore.getState().completeConnect('github')
    useOnboardingStore.getState().completeConnect('kicad')
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    expect(screen.queryByRole('button', { name: 'Skip for now' })).toBeNull()
    expect(screen.getByRole('button', { name: /Build context model/ })).toBeEnabled()
  })
})
