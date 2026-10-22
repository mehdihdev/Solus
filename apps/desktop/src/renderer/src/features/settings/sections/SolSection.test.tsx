import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SolSection } from './SolSection'
import { useDesktopSol } from '../useDesktopSol'
import { useSettingsStore } from '../../../store/settingsStore'
import { fakeSolBridge, SOL_STATE } from '../../sol/solWindow.fixtures'
import { settingsData } from '../settings.fixtures'
import type { SettingsData } from '../useSettingsData'
import type { SolBridge } from '../../../lib/desktopBridge'
import type { SolState } from '../../../../../main/sol-window/solWindow'

function Harness({
  data,
  bridge
}: {
  data: SettingsData
  bridge: SolBridge | null
}): React.JSX.Element {
  const sol = useDesktopSol(bridge)
  return <SolSection data={data} sol={sol} onFixCapture={vi.fn()} />
}

const off: SolState = { ...SOL_STATE, screenIntelligence: false }

beforeEach(() => {
  useSettingsStore.setState({ solMode: 'Guide', theme: 'dark', accent: 'amber' })
})

describe('SolSection — answer mode (ADR-016)', () => {
  it('reflects the current mode from the store', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<Harness data={settingsData()} bridge={null} />)
    expect(screen.getByLabelText('Answer mode')).toHaveTextContent('Expert')
  })

  it('persists a mode change through the backend action', async () => {
    const data = settingsData()
    render(<Harness data={data} bridge={null} />)
    await userEvent.click(screen.getByText('Expert'))
    expect(data.actions.setSolMode).toHaveBeenCalledWith('Expert')
  })

  it('shows the SOL-mode error inline', () => {
    const data = settingsData({ errors: { sol_mode: 'Not allowed', consent: null, name: null } })
    render(<Harness data={data} bridge={null} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Not allowed')
  })

  it('falls back to a local-only mode change when offline', async () => {
    const data = settingsData({ status: 'offline' })
    render(<Harness data={data} bridge={null} />)
    await userEvent.click(screen.getByText('Expert'))
    expect(data.actions.setSolMode).not.toHaveBeenCalled()
    expect(useSettingsStore.getState().solMode).toBe('Expert')
  })
})

describe('SolSection — desktop rows (SOLUSDEV-252)', () => {
  it('outside Electron, says the rows live in the desktop app and renders no controls', () => {
    render(<Harness data={settingsData()} bridge={null} />)
    expect(screen.getByText(/Available in the desktop app/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Action mode')).toBeNull()
  })

  it('reflects the desktop state with the wireflow §D copy under its label', async () => {
    render(<Harness data={settingsData()} bridge={fakeSolBridge({ ...off, actionMode: 'do' })} />)
    expect(await screen.findByLabelText('Action mode')).toHaveTextContent('Build')
    expect(screen.getByRole('switch', { name: 'SOL sees your screen' })).toHaveAttribute(
      'aria-checked',
      'false'
    )
    expect(screen.getByRole('switch', { name: 'Hold-Ctrl gestures' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    expect(
      screen.getByText(
        /When on, SOL can take a picture of your screen when you summon it or circle something, uses it for that one question, and then discards it\. Nothing is saved unless you file it\. Off means SOL never captures\./
      )
    ).toBeInTheDocument()
  })

  it('drives the bridge: Build → setMode("do"), the switches → their setters', async () => {
    const bridge = fakeSolBridge(off)
    render(<Harness data={settingsData()} bridge={bridge} />)
    await userEvent.click(await screen.findByRole('radio', { name: 'Build' }))
    expect(bridge.setMode).toHaveBeenCalledWith('do')
    await userEvent.click(screen.getByRole('switch', { name: 'SOL sees your screen' }))
    expect(bridge.setScreenIntelligence).toHaveBeenCalledWith(true)
    await userEvent.click(screen.getByRole('switch', { name: 'Hold-Ctrl gestures' }))
    expect(bridge.setHotkeys).toHaveBeenCalledWith(false)
  })

  it('tags the switch and offers the fix when capture is blocked — no raw URL text', async () => {
    const blocked: SolState = {
      ...SOL_STATE,
      capture: {
        mode: 'needs-permission',
        message: 'Screen capture needs the Screen Recording permission.',
        settingsUrl: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'
      }
    }
    const onFixCapture = vi.fn()
    function Blocked(): React.JSX.Element {
      const sol = useDesktopSol(fakeSolBridge(blocked))
      return <SolSection data={settingsData()} sol={sol} onFixCapture={onFixCapture} />
    }
    render(<Blocked />)
    expect(await screen.findByText('Permission needed')).toBeInTheDocument()
    expect(screen.queryByText(/x-apple\.systempreferences/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'How to fix' }))
    expect(onFixCapture).toHaveBeenCalled()
  })

  it('follows sol:state pushes from main', async () => {
    const bridge = fakeSolBridge(off)
    render(<Harness data={settingsData()} bridge={bridge} />)
    expect(await screen.findByLabelText('Action mode')).toHaveTextContent('Guide')
    act(() => bridge.pushState({ ...off, actionMode: 'do' }))
    expect(screen.getByRole('radio', { name: 'Build' })).toHaveAttribute('aria-checked', 'true')
  })

  it('reports a rejected change in plain language', async () => {
    const bridge = fakeSolBridge(off)
    vi.mocked(bridge.setHotkeys).mockRejectedValueOnce(new Error('ipc closed'))
    render(<Harness data={settingsData()} bridge={bridge} />)
    await userEvent.click(await screen.findByRole('switch', { name: 'Hold-Ctrl gestures' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/didn't accept that change/)
  })
})
