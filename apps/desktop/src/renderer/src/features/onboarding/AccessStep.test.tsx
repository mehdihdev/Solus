// SOLUSDEV-323 Access step (docs/wireflows/onboarding.md §4): every switch
// starts off, permissions are asked at the row that needs them with main's own
// pane, and the summon practice listens for a REAL double-Ctrl from main.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AccessStep } from './AccessStep'
import {
  SOL_STATE,
  fakeSolBridge,
  installSolBridge,
  uninstallSolBridge,
  type FakeSolBridge
} from '../sol/solWindow.fixtures'
import type { SolState } from '../../../../main/sol-window/solWindow'

const OFF: SolState = {
  ...SOL_STATE,
  screenIntelligence: false,
  capture: { mode: 'available', message: '' }
}

function mount(bridge: FakeSolBridge | null): { onNext: () => void; onBack: () => void } {
  if (bridge) installSolBridge(bridge)
  const onNext = vi.fn()
  const onBack = vi.fn()
  render(<AccessStep onNext={onNext} onBack={onBack} />)
  return { onNext, onBack }
}

afterEach(() => {
  uninstallSolBridge()
  vi.restoreAllMocks()
})

describe('AccessStep — outside the desktop app', () => {
  it('says these settings live in the desktop app and still continues', async () => {
    const { onNext } = mount(null)
    expect(screen.getByText(/live in the Solus desktop app/)).toBeInTheDocument()
    expect(screen.queryByRole('switch')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /continue/i }))
    expect(onNext).toHaveBeenCalledTimes(1)
  })
})

describe('AccessStep — See your screen', () => {
  let bridge: FakeSolBridge
  beforeEach(() => {
    bridge = fakeSolBridge(OFF)
  })

  it('starts off and offers "Not now — continue"', async () => {
    mount(bridge)
    const sw = await screen.findByRole('switch', { name: 'See your screen' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByRole('button', { name: 'Not now — continue' })).toBeInTheDocument()
  })

  it('turning it on goes through main (the source of truth)', async () => {
    mount(bridge)
    await userEvent.click(await screen.findByRole('switch', { name: 'See your screen' }))
    expect(bridge.setScreenIntelligence).toHaveBeenCalledWith(true)
  })

  it('asks for the permission at the row when capture is not available', async () => {
    bridge = fakeSolBridge({
      ...OFF,
      screenIntelligence: true,
      capture: { mode: 'needs-permission', message: 'Screen capture needs permission.' }
    } as SolState)
    mount(bridge)
    expect(await screen.findByText('Screen capture needs permission.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Open System Settings' }))
    expect(bridge.openCaptureSettings).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Recheck' }))
    expect(bridge.getState).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument()
  })

  it('says it is granted when capture is available', async () => {
    bridge = fakeSolBridge({ ...OFF, screenIntelligence: true })
    mount(bridge)
    expect(await screen.findByText('Screen access granted')).toBeInTheDocument()
  })
})

describe('AccessStep — summon practice', () => {
  it('ticks the row on a REAL double-Ctrl pushed from main', async () => {
    const bridge = fakeSolBridge({ ...OFF, hotkeysEnabled: true, hotkeys: null })
    mount(bridge)
    await screen.findByRole('switch', { name: 'See your screen' })
    expect(screen.queryByText(/one double-tap away/)).toBeNull()
    act(() => bridge.pushSummoned(Date.now()))
    expect(screen.getByText(/one double-tap away/)).toBeInTheDocument()
    for (const key of screen.getAllByText('ctrl'))
      expect(key).toHaveAttribute('data-pressed', 'true')
  })

  it('Show me opens the real SOL window', async () => {
    const bridge = fakeSolBridge(OFF)
    mount(bridge)
    await userEvent.click(await screen.findByRole('button', { name: 'Show me' }))
    expect(bridge.open).toHaveBeenCalledTimes(1)
  })

  it('shows the hotkey status instead of the practice when hotkeys are off', async () => {
    const bridge = fakeSolBridge({ ...OFF, hotkeysEnabled: false })
    mount(bridge)
    expect(await screen.findByText(/hotkeys are off/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show me' })).toBeInTheDocument()
  })

  it('stops listening when it unmounts', async () => {
    const bridge = fakeSolBridge(OFF)
    installSolBridge(bridge)
    const { unmount } = render(<AccessStep onNext={vi.fn()} onBack={vi.fn()} />)
    await screen.findByRole('switch', { name: 'See your screen' })
    unmount()
    expect(() => bridge.pushSummoned(1)).not.toThrow()
  })
})
