import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { SolScreen } from './SolScreen'
import { useShellStore } from '../workspace/shellStore'
import { useSettingsStore } from '../../store/settingsStore'

function renderSol(overrides?: { onOpenAlert?: () => void; onStartTour?: () => void }): {
  onOpenAlert: ReturnType<typeof vi.fn>
  onStartTour: ReturnType<typeof vi.fn>
} {
  const onOpenAlert = vi.fn()
  const onStartTour = vi.fn()
  render(
    <SolScreen
      onOpenAlert={overrides?.onOpenAlert ?? onOpenAlert}
      onStartTour={overrides?.onStartTour ?? onStartTour}
    />
  )
  return { onOpenAlert, onStartTour }
}

beforeEach(() => {
  useShellStore.getState().reset()
  useSettingsStore.setState({ solMode: 'Guide' })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('SolScreen — messages', () => {
  it('shows the empty-state prompt when there is no chat', () => {
    renderSol()
    expect(screen.getByText(/Ask SOL anything about your robot/)).toBeInTheDocument()
  })

  it('renders a scripted sol message with Guide text and the diagnosis card', () => {
    useShellStore.getState().appendChat({ role: 'sol', scriptKey: 'anomaly' })
    renderSol()
    expect(screen.getByText(/chain I followed/)).toBeInTheDocument()
    expect(screen.getByText('DIAGNOSIS')).toBeInTheDocument()
    expect(
      screen.getByText(
        'FL knee torque ripple driven by a firmware ↔ gate-driver interface mismatch'
      )
    ).toBeInTheDocument()
  })

  it('re-renders the Expert text when the mode is switched', () => {
    useShellStore.getState().appendChat({ role: 'sol', scriptKey: 'anomaly' })
    renderSol()
    fireEvent.click(screen.getByRole('radio', { name: 'Expert' }))
    expect(useSettingsStore.getState().solMode).toBe('Expert')
    expect(screen.getByText(/per-rev disturbance, not loop instability/)).toBeInTheDocument()
    expect(screen.queryByText(/chain I followed/)).not.toBeInTheDocument()
  })

  it('renders the cross-domain evidence chips', () => {
    useShellStore.getState().appendChat({ role: 'sol', scriptKey: 'anomaly' })
    renderSol()
    expect(screen.getByText('EVIDENCE FROM THE GRAPH')).toBeInTheDocument()
    for (const label of ['ELECTRICAL', 'SOFTWARE', 'RUNTIME', 'MECHANICAL']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText('motor_driver.c L84–112')).toBeInTheDocument()
  })
})

describe('SolScreen — followups', () => {
  it('appends the followup question and answer to the chat', () => {
    vi.useFakeTimers()
    const shell = useShellStore.getState()
    shell.appendChat({ role: 'sol', scriptKey: 'alertq' })
    shell.appendChat({ role: 'sol', scriptKey: 'hello' })
    shell.appendChat({ role: 'sol', scriptKey: 'anomaly' })
    renderSol()
    fireEvent.click(screen.getByText(/Why exactly 4\.2 Hz/))
    expect(useShellStore.getState().chat).toHaveLength(4)
    act(() => {
      vi.advanceTimersByTime(1400)
    })
    expect(useShellStore.getState().chat).toHaveLength(5)
    expect(screen.getByText(/Each stride loads the knee twice/)).toBeInTheDocument()
  })
})

describe('SolScreen — apply fix / flash', () => {
  it('runs the flash steps then resolves alert a1 and the anomaly', () => {
    vi.useFakeTimers()
    useShellStore.getState().setAnomaly('active')
    useShellStore.getState().appendChat({ role: 'sol', scriptKey: 'anomaly' })
    renderSol()
    fireEvent.click(screen.getByRole('button', { name: 'Apply & flash to robot' }))
    expect(screen.getByText(/Compiling firmware/)).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(3 * 1100 + 600)
    })
    expect(screen.getByText(/alert resolved/)).toBeInTheDocument()
    expect(useShellStore.getState().resolved.a1).toBe(true)
    expect(useShellStore.getState().anomaly).toBe('resolved')
  })

  it('opens alert a1 from Review diff', () => {
    useShellStore.getState().appendChat({ role: 'sol', scriptKey: 'anomaly' })
    const { onOpenAlert } = renderSol()
    fireEvent.click(screen.getByRole('button', { name: 'Review diff' }))
    expect(onOpenAlert).toHaveBeenCalledWith('a1')
  })
})

describe('SolScreen — input', () => {
  it('routes free text matching a script to that script', () => {
    vi.useFakeTimers()
    renderSol()
    fireEvent.change(screen.getByPlaceholderText('Ask about a signal, a change, a part…'), {
      target: { value: 'why is the knee oscillating?' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(screen.getByText('why is the knee oscillating?')).toBeInTheDocument()
    expect(screen.getByText(/tracing FL knee through 4 domains…/)).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(1700)
    })
    expect(
      screen.getByText(
        'FL knee torque ripple driven by a firmware ↔ gate-driver interface mismatch'
      )
    ).toBeInTheDocument()
  })

  it('falls back to the hello script for unmatched text', () => {
    vi.useFakeTimers()
    renderSol()
    fireEvent.change(screen.getByPlaceholderText('Ask about a signal, a change, a part…'), {
      target: { value: 'good morning' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    act(() => {
      vi.advanceTimersByTime(1700)
    })
    expect(screen.getByText(/I sit on top of your project/)).toBeInTheDocument()
  })

  it('sends a suggested question chip as a scripted exchange', () => {
    vi.useFakeTimers()
    renderSol()
    fireEvent.click(screen.getByText(/τ_FL_knee is oscillating at ~4\.2 Hz/))
    act(() => {
      vi.advanceTimersByTime(1700)
    })
    expect(screen.getByText(/chain I followed/)).toBeInTheDocument()
  })

  it('starts the guided tour from the tour chip', () => {
    const { onStartTour } = renderSol()
    fireEvent.click(screen.getByText(/Show me how to investigate the U4 alert/))
    expect(onStartTour).toHaveBeenCalled()
  })
})
