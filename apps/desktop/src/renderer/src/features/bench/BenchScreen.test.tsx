import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { BenchScreen } from './BenchScreen'
import { useShellStore } from '../workspace/shellStore'
import { TELEM_JOINTS, TELEM_SYSTEM } from '../workspace/workspaceData.constants'

beforeEach(() => {
  useShellStore.getState().reset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('BenchScreen — telemetry', () => {
  it('renders every joint torque channel and all system vitals', () => {
    render(<BenchScreen onAskSol={vi.fn()} />)
    for (const joint of TELEM_JOINTS) {
      expect(screen.getByText(joint.l)).toBeInTheDocument()
    }
    for (const sys of TELEM_SYSTEM) {
      expect(screen.getByText(sys.l)).toBeInTheDocument()
    }
    expect(screen.getByText('JOINT TORQUES · 12 ACTUATORS')).toBeInTheDocument()
    expect(screen.getByText('ROBOT · TOP VIEW')).toBeInTheDocument()
  })

  it('streams while running and ticks telemetry without crashing', () => {
    vi.useFakeTimers()
    render(<BenchScreen onAskSol={vi.fn()} />)
    expect(screen.getByText('● STREAMING · 500 HZ')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(screen.getByText('● STREAMING · 500 HZ')).toBeInTheDocument()
  })

  it('pauses the stream when Pause is clicked', () => {
    render(<BenchScreen onAskSol={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(screen.getByText('○ PAUSED')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(screen.getByText('● STREAMING · 500 HZ')).toBeInTheDocument()
  })
})

describe('BenchScreen — anomaly', () => {
  it('shows the anomaly banner and fault markers when the anomaly is active', () => {
    useShellStore.getState().setAnomaly('active')
    render(<BenchScreen onAskSol={vi.fn()} />)
    expect(
      screen.getByText('Anomaly detected — τ_FL_knee oscillating at 4.2 Hz')
    ).toBeInTheDocument()
    expect(screen.getByText('1 FAULT')).toBeInTheDocument()
  })

  it('fires onAskSol("anomaly") from the banner', () => {
    useShellStore.getState().setAnomaly('active')
    const onAskSol = vi.fn()
    render(<BenchScreen onAskSol={onAskSol} />)
    fireEvent.click(screen.getByRole('button', { name: 'Ask SOL' }))
    expect(onAskSol).toHaveBeenCalledWith('anomaly')
  })

  it('dismisses the banner without clearing the anomaly', () => {
    useShellStore.getState().setAnomaly('active')
    render(<BenchScreen onAskSol={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss anomaly banner' }))
    expect(
      screen.queryByText('Anomaly detected — τ_FL_knee oscillating at 4.2 Hz')
    ).not.toBeInTheDocument()
    expect(useShellStore.getState().anomaly).toBe('active')
  })

  it('shows the resolved notice once the fix is flashed', () => {
    useShellStore.getState().setAnomaly('resolved')
    render(<BenchScreen onAskSol={vi.fn()} />)
    expect(screen.getByText(/Fix flashed — τ_FL_knee stable for 30 s/)).toBeInTheDocument()
  })

  it('auto-triggers the anomaly about 8 s after entering, once', () => {
    vi.useFakeTimers()
    render(<BenchScreen onAskSol={vi.fn()} />)
    expect(useShellStore.getState().anomaly).toBe('none')
    act(() => {
      vi.advanceTimersByTime(8000)
    })
    expect(useShellStore.getState().anomaly).toBe('active')
  })

  it('re-triggers the anomaly from the Inject anomaly control', () => {
    render(<BenchScreen onAskSol={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Inject anomaly' }))
    expect(useShellStore.getState().anomaly).toBe('active')
  })
})

describe('BenchScreen — Real mode pairing', () => {
  it('walks the pair flow: empty state, scan, found device, connect', () => {
    vi.useFakeTimers()
    render(<BenchScreen onAskSol={vi.fn()} />)
    fireEvent.click(screen.getByRole('radio', { name: 'Real' }))
    expect(screen.getByText('No hardware detected')).toBeInTheDocument()
    expect(screen.getByText('REAL · NO DEVICE')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pair device' }))
    expect(screen.getByText(/Scanning USB \+ mDNS…/)).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(1800)
    })
    expect(screen.getByText('Found 1 device')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))
    expect(screen.getByText('REAL · STRIDER-QD12 #A3 · USB-C')).toBeInTheDocument()
  })
})
