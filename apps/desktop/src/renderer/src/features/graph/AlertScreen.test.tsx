import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AlertScreen } from './AlertScreen'
import { ALERTS } from '../workspace/workspaceData.constants'
import { useShellStore } from '../workspace/shellStore'
import { useSettingsStore } from '../../store/settingsStore'

const a1 = ALERTS[0]

interface Overrides {
  alertId?: string
  onBack?: () => void
  onAskSol?: (key: string) => void
}

function renderAlert(overrides: Overrides = {}): void {
  render(
    <AlertScreen
      alertId={overrides.alertId ?? 'a1'}
      onBack={overrides.onBack ?? vi.fn()}
      onAskSol={overrides.onAskSol ?? vi.fn()}
    />
  )
}

beforeEach(() => {
  useShellStore.getState().reset()
  useSettingsStore.setState({ solMode: 'Guide' })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AlertScreen — content', () => {
  it('renders the alert title, change summary, and affected files', () => {
    renderAlert()
    expect(
      screen.getByRole('heading', { name: 'Motor driver swap breaks firmware pin map' })
    ).toBeInTheDocument()
    expect(screen.getByText('Component swapped on strider_main board')).toBeInTheDocument()
    expect(screen.getByText('AFFECTED CODE · 3 FILES')).toBeInTheDocument()
    for (const file of a1.files) {
      expect(screen.getAllByText(file.path).length).toBeGreaterThan(0)
    }
  })

  it('routes the header Ask SOL action to the alert script', async () => {
    const onAskSol = vi.fn()
    renderAlert({ onAskSol })
    await userEvent.click(screen.getByRole('button', { name: /Ask SOL about this/ }))
    expect(onAskSol).toHaveBeenCalledWith('alertq')
  })

  it('fires onBack from the back control', async () => {
    const onBack = vi.fn()
    renderAlert({ onBack })
    await userEvent.click(screen.getByText('Back'))
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('renders a fallback with a back control for unknown alerts', async () => {
    const onBack = vi.fn()
    renderAlert({ alertId: 'nope', onBack })
    expect(screen.getByText('Alert not found.')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Back'))
    expect(onBack).toHaveBeenCalledTimes(1)
  })
})

describe('AlertScreen — SOL mode (ADR-016)', () => {
  it('defaults the why-explanation to the Guide text', () => {
    renderAlert()
    expect(screen.getByText(a1.why.guide)).toBeInTheDocument()
  })

  it('defaults to the Expert text when settings say Expert', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    renderAlert()
    expect(screen.getByText(a1.why.expert)).toBeInTheDocument()
    expect(screen.queryByText(a1.why.guide)).toBeNull()
  })

  it('switches the why-text via the segmented control', async () => {
    renderAlert()
    await userEvent.click(screen.getByRole('radio', { name: 'Expert' }))
    expect(screen.getByText(a1.why.expert)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'Guide' }))
    expect(screen.getByText(a1.why.guide)).toBeInTheDocument()
  })
})

describe('AlertScreen — fix flow', () => {
  it('applies the fix through the staged steps and resolves the alert', () => {
    vi.useFakeTimers()
    renderAlert()
    fireEvent.click(screen.getByRole('button', { name: 'Apply fix' }))
    expect(screen.getByText('Creating branch fix/u4-pin-map…')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(4 * 850 + 500)
    })
    expect(useShellStore.getState().resolved['a1']).toBe(true)
    expect(
      screen.getByText(/Patch applied — PR strider-fw#144 awaiting review/)
    ).toBeInTheDocument()
    expect(screen.getByText('RESOLVED')).toBeInTheDocument()
  })

  it('creates an issue, sets the toast, and disables the button', async () => {
    renderAlert()
    await userEvent.click(screen.getByRole('button', { name: 'Create issue' }))
    expect(useShellStore.getState().toast).toEqual({
      kind: 'ok',
      title: 'Issue #144 created in strider-fw',
      body: 'Linked to this alert with the full cross-domain trace attached.'
    })
    expect(screen.getByRole('button', { name: /#144 created/ })).toBeDisabled()
  })

  it('mounts already-resolved alerts in the resolved state', () => {
    renderAlert({ alertId: 'a3' })
    expect(screen.getByText('RESOLVED')).toBeInTheDocument()
    expect(screen.getByText(/Resolved 3d ago by Marcus Hale — fix merged in/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply fix' })).toBeNull()
  })

  it('mounts alerts resolved earlier in the session in the resolved state', () => {
    useShellStore.getState().resolveAlert('a1')
    renderAlert()
    expect(screen.getByText('RESOLVED')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply fix' })).toBeNull()
  })
})
