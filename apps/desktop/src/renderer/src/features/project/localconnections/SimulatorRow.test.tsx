// SOLUSDEV-72 — simulator rows: an available simulator gets real start
// controls; an unavailable one plainly states the backend's reason and is
// unstartable. Isaac never pretends to have an in-app start.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SimulatorRow } from './SimulatorRow'
import type { BenchSimulator } from '../../../lib/api/resources'

function sim(overrides: Partial<BenchSimulator> = {}): BenchSimulator {
  return { kind: 'mujoco', available: true, reason: null, ...overrides }
}

function renderRow(
  simulator: BenchSimulator,
  overrides: Partial<React.ComponentProps<typeof SimulatorRow>> = {}
): { onStart: ReturnType<typeof vi.fn> } {
  const onStart = vi.fn(async () => null)
  render(
    <SimulatorRow
      simulator={simulator}
      sessions={[]}
      disabledReason={null}
      onStart={onStart}
      onStop={vi.fn()}
      {...overrides}
    />
  )
  return { onStart }
}

describe('SimulatorRow — mujoco', () => {
  it('starts the builtin demo scene in one click', async () => {
    const { onStart } = renderRow(sim())
    fireEvent.click(screen.getByRole('button', { name: 'Start MuJoCo demo scene' }))
    await waitFor(() => expect(onStart).toHaveBeenCalledWith({ provider: 'mujoco' }))
  })

  it('surfaces the start failure text', async () => {
    const onStart = vi.fn(async () => 'Session limit reached — stop an active session first.')
    render(
      <SimulatorRow
        simulator={sim()}
        sessions={[]}
        disabledReason={null}
        onStart={onStart}
        onStop={vi.fn()}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Start MuJoCo demo scene' }))
    expect(
      await screen.findByText('Session limit reached — stop an active session first.')
    ).toBeInTheDocument()
  })
})

describe('SimulatorRow — gazebo', () => {
  it('needs topics before it can start, then sends them split', async () => {
    const { onStart } = renderRow(sim({ kind: 'gazebo' }))
    const start = screen.getByRole('button', { name: 'Start Gazebo' })
    expect(start).toBeDisabled()
    fireEvent.change(screen.getByRole('textbox', { name: 'Gazebo topics' }), {
      target: { value: '/imu, /joint_states' }
    })
    fireEvent.click(start)
    await waitFor(() =>
      expect(onStart).toHaveBeenCalledWith({
        provider: 'gazebo',
        topics: ['/imu', '/joint_states']
      })
    )
  })

  it('is unstartable with the plain reason when unavailable', () => {
    renderRow(sim({ kind: 'gazebo', available: false, reason: 'gz CLI not on PATH' }))
    expect(screen.getByText('gz CLI not on PATH')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start Gazebo' })).toBeDisabled()
    expect(screen.getByRole('textbox', { name: 'Gazebo topics' })).toBeDisabled()
  })
})

describe('SimulatorRow — mcap replay', () => {
  it('needs a server-side path before it can start', async () => {
    const { onStart } = renderRow(sim({ kind: 'mcap-replay' }))
    const start = screen.getByRole('button', { name: 'Start MCAP replay' })
    expect(start).toBeDisabled()
    fireEvent.change(screen.getByRole('textbox', { name: 'MCAP path under the bench data root' }), {
      target: { value: 'runs/2026-08-01.mcap' }
    })
    fireEvent.click(start)
    await waitFor(() =>
      expect(onStart).toHaveBeenCalledWith({
        provider: 'mcap-replay',
        mcap_path: 'runs/2026-08-01.mcap'
      })
    )
  })
})

describe('SimulatorRow — isaac', () => {
  it('renders the availability reason honestly and offers no start control', () => {
    renderRow(
      sim({
        kind: 'isaac',
        available: false,
        reason: 'no live adapter; stream via the Isaac direct script or replay an MCAP recording'
      })
    )
    expect(
      screen.getByText(
        'no live adapter; stream via the Isaac direct script or replay an MCAP recording'
      )
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /start/i })).not.toBeInTheDocument()
  })
})

describe('SimulatorRow — runner unavailable', () => {
  it('disables everything with the runner reason', () => {
    renderRow(sim(), { disabledReason: 'livebench is not installed on the server' })
    expect(screen.getByText('livebench is not installed on the server')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start MuJoCo demo scene' })).toBeDisabled()
  })
})
