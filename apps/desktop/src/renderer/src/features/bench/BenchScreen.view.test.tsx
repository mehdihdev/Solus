// SOLUSDEV-319 — Live Bench mounts the team-shared view: it fetches GET /bench/view, renders
// the shared surfaces, and a viewer gets read-only controls (wireflow live-bench-view.md §8).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EMPTY_BENCH_VIEW, type BenchView } from '@solus/shared-types'
import { BenchScreen } from './BenchScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { api } from '../../lib/api/client'
import { resetBenchViewStore } from './view/useBenchView'

vi.mock('../../lib/api/client', () => ({
  api: { request: vi.fn(), requestPage: vi.fn() },
  apiBaseUrl: 'http://api.test',
  apiToken: async () => null
}))
vi.mock('./scene/ScenePanel', () => ({ ScenePanel: () => null }))
vi.mock('./BenchCanvasHost', () => ({ BenchCanvasHost: () => null }))
vi.mock('./runs/RunsView', () => ({ RunsView: () => null }))
vi.mock('./DeviceBenchView', () => ({ DeviceBenchView: () => null }))

const requestMock = vi.mocked(api.request)
const VIEW: BenchView = {
  ...EMPTY_BENCH_VIEW,
  version: 2,
  updated_at: '2026-10-31T00:00:00Z',
  display: [
    {
      target: { kind: 'signal', device_id: 'usb:1/3', signal: 'pos' },
      pinned: false,
      hidden: true,
      order: null,
      unit: null,
      limits: null,
      plot_group: null
    }
  ]
}

function route(role: string): void {
  requestMock.mockImplementation(async (path: string) => {
    if (path === '/projects/p1/bench/view') return VIEW as never
    if (path === '/me' || path.endsWith('/users/me'))
      return {
        id: 'u',
        email: 'u@example.test',
        name: null,
        avatar_url: null,
        created_at: '',
        teams: [
          { team_id: 't1', name: 'T', role, is_personal: false, plan_status: '', trial_ends_at: '' }
        ]
      } as never
    return [] as never
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  resetBenchViewStore()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
  useWorkspaceStore.setState({
    linked: true,
    project: { id: 'p1', name: 'Rover', teamId: 't1' }
  })
})

describe('BenchScreen shared view', () => {
  it('fetches the view and shows the hidden list', async () => {
    route('member')
    render(<BenchScreen />)
    expect(await screen.findByRole('button', { name: 'Hidden signals (1)' })).toBeInTheDocument()
    expect(requestMock).toHaveBeenCalledWith('/projects/p1/bench/view')
    expect(await screen.findByRole('button', { name: '+ Derived signal' })).toBeInTheDocument()
  })

  it('keeps a viewer read-only', async () => {
    route('viewer')
    render(<BenchScreen />)
    expect(await screen.findByRole('button', { name: 'Hidden signals (1)' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Derived signal' })).not.toBeInTheDocument()
  })
})
