// Live Bench honest empty state (SOLUSDEV-152). The prototype's synthesized
// telemetry, fake device pairing, and simulated signals labelled REAL are
// gone; the live surface arrives with the Live Bench tickets (SOLUSDEV-121+).
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BenchScreen } from './BenchScreen'

describe('BenchScreen — honest empty state', () => {
  it('says what Live Bench will show and what populates it', () => {
    render(<BenchScreen />)
    expect(screen.getByText(/Live Bench isn't streaming yet/)).toBeInTheDocument()
    expect(
      screen.getByText(/joint telemetry, system vitals, and anomaly detection/i)
    ).toBeInTheDocument()
    expect(screen.getByText('NO DEVICE CONNECTED')).toBeInTheDocument()
  })

  it('contains no fabricated devices, signals, or REAL/streaming labels', () => {
    const { container } = render(<BenchScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/STRIDER/i)
    expect(text).not.toMatch(/500 HZ/)
    expect(text).not.toMatch(/STREAMING/)
    expect(text).not.toMatch(/fw 0\.9\.2/)
    expect(text).not.toMatch(/τ_/)
    expect(text).not.toMatch(/Inject anomaly/)
    expect(text).not.toMatch(/GAZEBO/)
  })

  it('renders no fake toolbar controls (Sim/Real, pause, pairing)', () => {
    render(<BenchScreen />)
    expect(screen.queryByRole('radio', { name: 'Real' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pair device' })).not.toBeInTheDocument()
  })
})
