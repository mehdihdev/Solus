// Live Bench: mounts the LB-05 LiveBenchWidget scoped to the shared focus
// (SOLUSDEV-70 wiring). The honesty rules from SOLUSDEV-152 still bind: every
// state a user can see states what is actually true — no fabricated devices,
// signals, or REAL/streaming labels, and no telemetry claim without data.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BenchScreen } from './BenchScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { api } from '../../lib/api/client'
import type { Entity } from '../../lib/api/resources'

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

function seedFocusedProject(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
  useFocusStore.setState({
    focusedEntityId: 'e1',
    status: 'ready',
    cache: { 'p1:e1@1': { entities: [E1], edges: [], truncated: false } }
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
})

describe('BenchScreen — empty states', () => {
  it('asks for a project when none is open, without touching the API', () => {
    render(<BenchScreen />)
    expect(screen.getByText('NO PROJECT OPEN')).toBeInTheDocument()
    expect(requestMock).not.toHaveBeenCalled()
  })

  it('asks for a focus when a project is open but nothing is focused', () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    render(<BenchScreen />)
    expect(screen.getByText('Nothing is focused')).toBeInTheDocument()
    expect(screen.getByText('NO PART FOCUSED')).toBeInTheDocument()
    expect(requestMock).not.toHaveBeenCalled()
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

describe('BenchScreen — focused', () => {
  it('mounts the Live Bench widget scoped to the focused entity', async () => {
    seedFocusedProject()
    requestMock.mockImplementation(async (path: string) =>
      path.includes('/bench/recent/') ? ({ entity_id: 'e1', signals: [] } as never) : ([] as never)
    )
    render(<BenchScreen />)
    await waitFor(() => expect(requestMock).toHaveBeenCalledWith('/projects/p1/bench/recent/e1'))
    // No telemetry for the part → the widget's own honest empty state.
    expect(
      await screen.findByText(/No telemetry yet for elbow motor — nothing is streaming\./)
    ).toBeInTheDocument()
  })
})
