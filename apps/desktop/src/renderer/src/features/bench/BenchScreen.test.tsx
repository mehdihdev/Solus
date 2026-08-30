// Live Bench: mounts the LB-05 LiveBenchWidget scoped to the shared focus
// (SOLUSDEV-70 wiring); without a focus it renders a device-keyed telemetry
// view for streaming sessions (SOLUSDEV-72), and an ACTIONABLE honest empty
// state when nothing is streaming. The honesty rules from SOLUSDEV-152 still
// bind: no fabricated devices, signals, or REAL/streaming labels.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BenchScreen } from './BenchScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { api } from '../../lib/api/client'
import type { BenchSession, Entity } from '../../lib/api/resources'

vi.mock('../../lib/api/client', () => ({
  api: { request: vi.fn(), requestPage: vi.fn() }
}))

const requestMock = vi.mocked(api.request)

const E1: Entity = {
  id: 'e1',
  type: 'part',
  domain: 'mechanical',
  name: 'elbow motor',
  source_key: 'onshape:e1'
}

const SESSION: BenchSession = {
  id: 's1',
  mode: 'sim',
  provider: 'mujoco',
  status: 'active',
  link: 'streaming',
  label: 'MuJoCo demo scene',
  created_at: '2026-08-16T00:00:00Z',
  ended_at: null,
  device: null,
  device_ids: ['demo/rod'],
  counts: { ingested: 123, unresolved: 0 },
  last_summary: null
}

function seedProject(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
}

function seedFocusedProject(): void {
  seedProject()
  useFocusStore.setState({
    focusedEntityId: 'e1',
    status: 'ready',
    cache: { 'p1:e1@1': { entities: [E1], edges: [], truncated: false } }
  })
}

/** Route the mocked client by path: sessions, device-recent, entity telemetry. */
function routeApi(options: { sessions?: BenchSession[] } = {}): void {
  requestMock.mockImplementation(async (path: string) => {
    if (path.includes('/bench/sessions')) return (options.sessions ?? []) as never
    if (path.includes('/bench/device-recent')) {
      // The batched route: {devices: [...]}, one entry per requested id.
      return {
        devices: [
          {
            device_id: 'demo/rod',
            resolved_entity_id: null,
            signals: [
              {
                signal: 'qvel',
                points: [{ timestamp: new Date().toISOString(), value: 1.25 }]
              }
            ]
          }
        ]
      } as never
    }
    if (path.includes('/bench/recent/')) return { entity_id: 'e1', signals: [] } as never
    return [] as never
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
  routeApi()
})

describe('BenchScreen — empty states', () => {
  it('asks for a project when none is open, without touching the API', () => {
    render(<BenchScreen />)
    expect(screen.getByText('NO PROJECT OPEN')).toBeInTheDocument()
    expect(requestMock).not.toHaveBeenCalled()
  })

  it('with no focus and nothing streaming, offers Connect a device honestly', async () => {
    seedProject()
    const onNavigate = vi.fn()
    render(<BenchScreen onNavigate={onNavigate} />)
    // The session check ran and found nothing — the copy says so.
    await waitFor(() =>
      expect(requestMock).toHaveBeenCalledWith('/projects/p1/bench/sessions?status=active')
    )
    expect(await screen.findByText('NOTHING STREAMING')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Connect a device' }))
    expect(onNavigate).toHaveBeenCalledWith('sources')
  })

  it('contains no fabricated devices, signals, or REAL/streaming labels', () => {
    const { container } = render(<BenchScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/STRIDER/i)
    expect(text).not.toMatch(/500 HZ/)
    expect(text).not.toMatch(/STREAMING/)
    expect(text).not.toMatch(/NO DEVICE CONNECTED/)
    expect(text).not.toMatch(/τ_/)
    expect(text).not.toMatch(/Inject anomaly/)
  })
})

describe('BenchScreen — device-keyed view (SOLUSDEV-72)', () => {
  it('renders per-device telemetry from active sessions when nothing is focused', async () => {
    seedProject()
    routeApi({ sessions: [SESSION] })
    render(<BenchScreen />)
    // The device from the active session gets its own panel with recent values.
    expect(await screen.findByText('demo/rod')).toBeInTheDocument()
    await waitFor(() =>
      expect(requestMock).toHaveBeenCalledWith(
        '/projects/p1/bench/device-recent?device_id=demo%2Frod&limit=60'
      )
    )
    expect(await screen.findByText(/qvel: 1\.25/)).toBeInTheDocument()
  })
})

describe('BenchScreen — focused', () => {
  it('mounts the Live Bench widget scoped to the focused entity', async () => {
    seedFocusedProject()
    render(<BenchScreen />)
    await waitFor(() => expect(requestMock).toHaveBeenCalledWith('/projects/p1/bench/recent/e1'))
    // No telemetry for the part → the widget's own honest empty state.
    expect(
      await screen.findByText(/No telemetry yet for elbow motor — nothing is streaming\./)
    ).toBeInTheDocument()
  })
})
