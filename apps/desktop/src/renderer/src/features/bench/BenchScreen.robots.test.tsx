// SOLUSDEV-319 — per-robot panels and the teleoperation bar on Live Bench.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { useEffect } from 'react'
import { BenchScreen } from './BenchScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { api } from '../../lib/api/client'
import type { BenchSession } from '../../lib/api/resources'

vi.mock('../../lib/api/client', () => ({
  api: { request: vi.fn(), requestPage: vi.fn() }
}))
vi.mock('./scene/ScenePanel', () => ({
  ScenePanel: ({ robotId }: { robotId?: string }) => <div>scene {robotId ?? 'all'}</div>
}))
vi.mock('./BenchCanvasHost', () => ({ BenchCanvasHost: () => null }))
vi.mock('./runs/RunsView', () => ({ RunsView: () => null }))
vi.mock('./DeviceBenchView', () => ({
  DeviceBenchView: ({
    deviceIds,
    showReasoning = true,
    reasoningOnly = false,
    onStreamChange
  }: {
    deviceIds: string[]
    showReasoning?: boolean
    reasoningOnly?: boolean
    onStreamChange?: (live: boolean) => void
  }) => {
    const streaming = deviceIds.includes('usb:A/1')
    useEffect(() => onStreamChange?.(streaming), [onStreamChange, streaming])
    if (reasoningOnly) return <span>LIVE REASONING over {deviceIds.join(',')}</span>
    return (
      <div>
        cards {deviceIds.join(',')}
        {showReasoning && <span>LIVE REASONING</span>}
      </div>
    )
  }
}))

const requestMock = vi.mocked(api.request)

function session(id: string, label: string, robot: string | null, ids: string[]): BenchSession {
  return {
    id,
    mode: robot ? 'real' : 'sim',
    provider: robot ? 'robot' : 'mujoco',
    status: 'active',
    link: 'streaming',
    label,
    created_at: '2026-10-30T00:00:00Z',
    ended_at: null,
    device: robot
      ? { serial_number: null, device_path: null, baud: null, robot_entity_id: robot }
      : null,
    device_ids: ids,
    counts: { ingested: 0, unresolved: 0 },
    last_summary: null
  }
}
const LEADER = session('s1', 'Robot lerobot leader (usb:A)', 'r1', ['usb:A/1'])
const FOLLOWER = session('s2', 'Robot lerobot follower (usb:B)', 'r2', ['usb:B/1'])
const SIM = session('s3', 'MuJoCo demo', null, ['demo/rod'])

function routeSessions(sessions: BenchSession[]): void {
  requestMock.mockImplementation(async (path: string) => {
    if (path.endsWith('/bench/teleop')) return null as never
    if (path.includes('/bench/sessions')) return sessions as never
    return [] as never
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
})

describe('BenchScreen robot panels', () => {
  it('gives each robot its own panel and keeps other devices in the single layout', async () => {
    routeSessions([FOLLOWER, SIM, LEADER])
    render(<BenchScreen />)
    const follower = await screen.findByRole('region', { name: 'lerobot follower' })
    const leader = screen.getByRole('region', { name: 'lerobot leader' })
    expect(within(follower).getByText('scene r2')).toBeInTheDocument()
    expect(within(follower).getByText('cards usb:B/1')).toBeInTheDocument()
    expect(within(leader).getByText('scene r1')).toBeInTheDocument()
    expect(within(leader).getByText('cards usb:A/1')).toBeInTheDocument()
    // The fallback holds only the non-robot device.
    expect(screen.getByText('cards demo/rod')).toBeInTheDocument()
    expect(screen.getByText('scene all')).toBeInTheDocument()
  })

  it('renders the project-wide live reasoning section once', async () => {
    routeSessions([FOLLOWER, SIM, LEADER])
    render(<BenchScreen />)
    await screen.findByRole('region', { name: 'lerobot leader' })
    expect(screen.getAllByText('LIVE REASONING')).toHaveLength(1)
  })

  it('keeps live reasoning, over every robot, when only robots are connected', async () => {
    routeSessions([FOLLOWER, LEADER])
    render(<BenchScreen />)
    await screen.findByRole('region', { name: 'lerobot leader' })
    const reasoning = screen.getAllByText(/LIVE REASONING/)
    expect(reasoning).toHaveLength(1)
    expect(reasoning[0]).toHaveTextContent('usb:A/1')
    expect(reasoning[0]).toHaveTextContent('usb:B/1')
  })

  it('shows the teleoperation bar only with two or more robot sessions', async () => {
    routeSessions([LEADER, SIM])
    const { unmount } = render(<BenchScreen />)
    await screen.findByRole('region', { name: 'lerobot leader' })
    expect(screen.queryByRole('region', { name: 'Teleoperation' })).not.toBeInTheDocument()
    unmount()
    routeSessions([FOLLOWER, LEADER])
    render(<BenchScreen />)
    expect(await screen.findByRole('region', { name: 'Teleoperation' })).toBeInTheDocument()
    expect((screen.getByLabelText('Leader') as HTMLSelectElement).value).toBe('s1')
    expect((screen.getByLabelText('Follower') as HTMLSelectElement).value).toBe('s2')
  })

  it('reports STREAMING when any panel streams', async () => {
    routeSessions([FOLLOWER, LEADER])
    render(<BenchScreen />)
    await waitFor(() => expect(screen.getByText('● STREAMING')).toBeInTheDocument())
  })

  it('shows the running teleop state from the poll', async () => {
    requestMock.mockImplementation(async (path: string) => {
      if (path.endsWith('/bench/teleop'))
        return {
          id: 't',
          state: 'running',
          leader: { session_id: 's1', label: LEADER.label },
          follower: { session_id: 's2', label: FOLLOWER.label },
          rate_hz: 30,
          started_at: 'x',
          stopped_at: null,
          stop_reason: null,
          pairs: []
        } as never
      if (path.includes('/bench/sessions')) return [FOLLOWER, LEADER] as never
      return [] as never
    })
    render(<BenchScreen />)
    expect(
      await screen.findByText('Teleoperating lerobot leader → lerobot follower · 30 Hz')
    ).toBeInTheDocument()
    const follower = screen.getByRole('region', { name: 'lerobot follower' })
    expect(within(follower).getByRole('button', { name: 'Release…' })).toBeDisabled()
  })

  it('keeps the legacy layout when no session is a saved robot', async () => {
    routeSessions([SIM])
    render(<BenchScreen />)
    expect(await screen.findByText('cards demo/rod')).toBeInTheDocument()
    expect(screen.getByText('scene all')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Teleoperation' })).not.toBeInTheDocument()
  })
})
