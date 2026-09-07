// The Simulation tab of Home's connected-accounts card (SOLUSDEV-244): the
// open project's bench inventory, started and stopped through that project's
// bench routes. No project or no API ⇒ honest copy, never a fabricated row.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SimulationPanel } from './SimulationPanel'
import * as resources from '../../lib/api/resources'
import * as localHook from '../project/localconnections/useLocalConnections'
import { ApiError } from '../../lib/api/envelope.types'
import type { BenchSession, BenchSources } from '../../lib/api/resources'

vi.mock('../project/localconnections/useLocalConnections', () => ({
  useLocalConnections: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, createBenchSession: vi.fn(), stopBenchSession: vi.fn() }
})

const ROVER = { id: 'p1', name: 'Rover', teamId: 't1' }

function sources(overrides: Partial<BenchSources> = {}): BenchSources {
  return {
    runner: { available: true, reason: null },
    simulators: [
      { kind: 'mujoco', available: true, reason: null },
      { kind: 'isaac', available: false, reason: 'No live adapter for Isaac Sim.' }
    ],
    devices: [],
    ...overrides
  }
}

function session(overrides: Partial<BenchSession> = {}): BenchSession {
  return {
    id: 's1',
    mode: 'sim',
    provider: 'mujoco',
    status: 'active',
    link: 'streaming',
    label: 'MuJoCo demo',
    created_at: '',
    ended_at: null,
    device: null,
    device_ids: [],
    counts: { ingested: 12, unresolved: 0 },
    last_summary: null,
    ...overrides
  }
}

function mockLocal(data: localHook.LocalConnections | null): ReturnType<typeof vi.fn> {
  const refresh = vi.fn()
  vi.mocked(localHook.useLocalConnections).mockReturnValue({ data, refresh })
  return refresh
}

beforeEach(() => {
  vi.mocked(resources.createBenchSession).mockReset()
  vi.mocked(resources.stopBenchSession).mockReset()
})

describe('SimulationPanel', () => {
  it('asks for an open project before offering any start', () => {
    mockLocal(null)
    render(<SimulationPanel currentProject={null} />)
    expect(screen.getByText(/Open a project to run a simulation/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
    expect(localHook.useLocalConnections).toHaveBeenCalledWith(null)
  })

  it('says the API is unreachable rather than inventing simulators', () => {
    mockLocal(null)
    render(<SimulationPanel currentProject={ROVER} />)
    expect(screen.getByText(/can't reach its API/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
    expect(localHook.useLocalConnections).toHaveBeenCalledWith('p1')
  })

  it("lists the project's simulators with the backend's own availability", () => {
    mockLocal({ sources: sources(), sessions: [] })
    render(<SimulationPanel currentProject={ROVER} />)
    expect(screen.getByText('Runs in Rover')).toBeInTheDocument()
    expect(screen.getByText('MuJoCo')).toBeInTheDocument()
    expect(screen.getByText('Isaac Sim')).toBeInTheDocument()
    expect(screen.getByText('No live adapter for Isaac Sim.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start MuJoCo demo scene' })).toBeEnabled()
  })

  it('starts a MuJoCo session on the open project and refreshes', async () => {
    const refresh = mockLocal({ sources: sources(), sessions: [] })
    vi.mocked(resources.createBenchSession).mockResolvedValue(session())
    render(<SimulationPanel currentProject={ROVER} />)
    await userEvent.click(screen.getByRole('button', { name: 'Start MuJoCo demo scene' }))
    await waitFor(() =>
      expect(resources.createBenchSession).toHaveBeenCalledWith('p1', {
        mode: 'sim',
        config: { provider: 'mujoco' }
      })
    )
    expect(refresh).toHaveBeenCalled()
  })

  it("surfaces the backend's refusal in place", async () => {
    mockLocal({ sources: sources(), sessions: [] })
    vi.mocked(resources.createBenchSession).mockRejectedValue(
      new ApiError(409, 'too_many_sessions', 'too many')
    )
    render(<SimulationPanel currentProject={ROVER} />)
    await userEvent.click(screen.getByRole('button', { name: 'Start MuJoCo demo scene' }))
    expect(await screen.findByText(/Session limit reached/)).toBeInTheDocument()
  })

  it('disables every start with the runner reason when livebench is missing', () => {
    mockLocal({
      sources: sources({ runner: { available: false, reason: 'livebench not installed' } }),
      sessions: []
    })
    render(<SimulationPanel currentProject={ROVER} />)
    expect(screen.getByRole('button', { name: 'Start MuJoCo demo scene' })).toBeDisabled()
    expect(screen.getAllByText('livebench not installed').length).toBeGreaterThan(0)
  })

  it('shows the active session under its simulator and stops it through the project', async () => {
    const refresh = mockLocal({ sources: sources(), sessions: [session()] })
    vi.mocked(resources.stopBenchSession).mockResolvedValue(session({ status: 'ended' }))
    render(<SimulationPanel currentProject={ROVER} />)
    expect(screen.getByText('STREAMING')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Stop MuJoCo demo' }))
    expect(resources.stopBenchSession).toHaveBeenCalledWith('p1', 's1')
    await waitFor(() => expect(refresh).toHaveBeenCalled())
  })
})
