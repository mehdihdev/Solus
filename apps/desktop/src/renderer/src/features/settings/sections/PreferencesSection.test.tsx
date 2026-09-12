import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PreferencesSection } from './PreferencesSection'
import { useSettingsStore } from '../../../store/settingsStore'
import type { SettingsData } from '../useSettingsData'
import type { SolBridge } from '../../../lib/desktopBridge'
import type { SolState } from '../../../../../main/sol-window/solWindow'

function data(overrides: Partial<SettingsData> = {}): SettingsData {
  return {
    status: 'ready',
    profile: null,
    consent: true,
    subscription: null,
    errors: { sol_mode: null, consent: null, name: null },
    actions: {
      setSolMode: vi.fn(async () => true),
      setConsent: vi.fn(async () => true),
      updateName: vi.fn(async () => true),
      refresh: vi.fn(async () => undefined)
    },
    ...overrides
  }
}

beforeEach(() => {
  useSettingsStore.setState({
    solMode: 'Guide',
    theme: 'dark',
    accent: 'amber',
    density: 'regular'
  })
})

describe('PreferencesSection — SOL mode', () => {
  it('reflects the current mode from the store', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<PreferencesSection data={data()} />)
    const control = screen.getByLabelText('Answer mode')
    expect(control).toHaveTextContent('Expert')
  })

  it('persists a mode change through the backend action', async () => {
    const setSolMode = vi.fn(async () => true)
    render(<PreferencesSection data={data({ actions: { ...data().actions, setSolMode } })} />)
    await userEvent.click(screen.getByText('Expert'))
    expect(setSolMode).toHaveBeenCalledWith('Expert')
  })

  it('shows the SOL-mode error inline', () => {
    render(
      <PreferencesSection
        data={data({ errors: { sol_mode: 'Not allowed', consent: null, name: null } })}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Not allowed')
  })

  it('falls back to a local-only mode change when offline', async () => {
    const setSolMode = vi.fn(async () => true)
    render(
      <PreferencesSection
        data={data({ status: 'offline', actions: { ...data().actions, setSolMode } })}
      />
    )
    await userEvent.click(screen.getByText('Expert'))
    expect(setSolMode).not.toHaveBeenCalled()
    expect(useSettingsStore.getState().solMode).toBe('Expert')
  })
})

describe('PreferencesSection — appearance (local)', () => {
  it('changes the theme in the local store', async () => {
    render(<PreferencesSection data={data()} />)
    await userEvent.selectOptions(screen.getByLabelText('Theme'), 'light')
    expect(useSettingsStore.getState().theme).toBe('light')
  })

  it('changes the density in the local store', async () => {
    render(<PreferencesSection data={data()} />)
    await userEvent.click(screen.getByText('compact'))
    expect(useSettingsStore.getState().density).toBe('compact')
  })
})

// SOLUSDEV-252 S3: the desktop SOL rows (action mode, sees-your-screen,
// hold-Ctrl gestures) drive window.solus.sol — faked here, absent in a browser.

const solWindow = window as unknown as { solus?: { sol?: SolBridge } }

function solState(overrides: Partial<SolState> = {}): SolState {
  return {
    actionMode: 'guide',
    screenIntelligence: false,
    hotkeysEnabled: true,
    alwaysOnTop: false,
    capture: { mode: 'available', message: '' },
    hotkeys: null,
    lastRegionRefused: false,
    ...overrides
  }
}

function fakeSolBridge(state: SolState | null): {
  bridge: SolBridge
  push: (next: SolState) => void
} {
  const listeners = new Set<(s: SolState) => void>()
  const bridge: SolBridge = {
    getState: vi.fn(async () => state),
    setMode: vi.fn(async (mode) => (state ? { ...state, actionMode: mode } : null)),
    setScreenIntelligence: vi.fn(async (on) =>
      state ? { ...state, screenIntelligence: on } : null
    ),
    setHotkeys: vi.fn(async (on) => (state ? { ...state, hotkeysEnabled: on } : null)),
    setAlwaysOnTop: vi.fn(async () => state),
    open: vi.fn(async () => state),
    onState: vi.fn((handler) => {
      listeners.add(handler)
      return () => listeners.delete(handler)
    }),
    onRegion: vi.fn(() => () => undefined)
  }
  return { bridge, push: (next) => listeners.forEach((l) => l(next)) }
}

describe('PreferencesSection — desktop SOL rows (SOLUSDEV-252)', () => {
  afterEach(() => {
    delete solWindow.solus
  })

  it('outside Electron, says the rows live in the desktop app and renders no controls', () => {
    render(<PreferencesSection data={data()} />)
    expect(screen.getByText(/Available in the desktop app/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Action mode')).toBeNull()
    expect(screen.queryByRole('switch', { name: 'SOL sees your screen' })).toBeNull()
  })

  it('reflects the desktop state and keeps the ADR-016 Answer mode row', async () => {
    solWindow.solus = { sol: fakeSolBridge(solState({ actionMode: 'do' })).bridge }
    render(<PreferencesSection data={data()} />)
    expect(await screen.findByLabelText('Action mode')).toHaveTextContent('Build')
    expect(screen.getByRole('radio', { name: 'Build' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByLabelText('Answer mode')).toHaveTextContent('Guide')
    expect(screen.getByRole('switch', { name: 'SOL sees your screen' })).toHaveAttribute(
      'aria-checked',
      'false'
    )
    expect(screen.getByRole('switch', { name: 'Hold-Ctrl gestures' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    // Wireflow §D copy, verbatim.
    expect(
      screen.getByText(
        /When on, SOL can take a picture of your screen when you summon it or circle something, uses it for that one question, and then discards it\. Nothing is saved unless you file it\. Off means SOL never captures\./
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Lets SOL notice a double-tap of Ctrl and a Ctrl-held circle anywhere on screen. Off keeps only the keyboard shortcuts.'
      )
    ).toBeInTheDocument()
    expect(screen.queryByText(/Available in the desktop app/)).toBeNull()
  })

  it('drives the bridge: Build → setMode("do"), the two switches → their setters, and shows the reply', async () => {
    const { bridge } = fakeSolBridge(solState())
    solWindow.solus = { sol: bridge }
    render(<PreferencesSection data={data()} />)
    await userEvent.click(await screen.findByRole('radio', { name: 'Build' }))
    expect(bridge.setMode).toHaveBeenCalledWith('do')
    expect(await screen.findByRole('radio', { name: 'Build' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    await userEvent.click(screen.getByRole('switch', { name: 'SOL sees your screen' }))
    expect(bridge.setScreenIntelligence).toHaveBeenCalledWith(true)
    await userEvent.click(screen.getByRole('switch', { name: 'Hold-Ctrl gestures' }))
    expect(bridge.setHotkeys).toHaveBeenCalledWith(false)
  })

  it('shows the platform note and the settings URL as text when capture is not available', async () => {
    solWindow.solus = {
      sol: fakeSolBridge(
        solState({
          capture: {
            mode: 'needs-permission',
            message: 'Screen capture needs the Screen Recording permission.',
            settingsUrl:
              'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'
          }
        })
      ).bridge
    }
    render(<PreferencesSection data={data()} />)
    expect(
      await screen.findByText(/Screen capture needs the Screen Recording permission\./)
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /x-apple\.systempreferences:com\.apple\.preference\.security\?Privacy_ScreenCapture/
      )
    ).toBeInTheDocument()
  })

  it('follows sol:state pushes from main (tray or another window flipped the mode)', async () => {
    const { bridge, push } = fakeSolBridge(solState())
    solWindow.solus = { sol: bridge }
    render(<PreferencesSection data={data()} />)
    expect(await screen.findByLabelText('Action mode')).toHaveTextContent('Guide')
    act(() => push(solState({ actionMode: 'do', screenIntelligence: true })))
    expect(screen.getByRole('radio', { name: 'Build' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('switch', { name: 'SOL sees your screen' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
  })

  it('reports a rejected change in plain language instead of an unhandled rejection', async () => {
    const { bridge } = fakeSolBridge(solState())
    vi.mocked(bridge.setHotkeys).mockRejectedValueOnce(new Error('ipc closed'))
    solWindow.solus = { sol: bridge }
    render(<PreferencesSection data={data()} />)
    await userEvent.click(await screen.findByRole('switch', { name: 'Hold-Ctrl gestures' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/didn't accept that change/)
  })

  it('says so when the desktop app returns no state instead of rendering nothing', async () => {
    solWindow.solus = { sol: fakeSolBridge(null).bridge }
    render(<PreferencesSection data={data()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/SOL settings didn't load/)
    expect(screen.queryByLabelText('Action mode')).toBeNull()
  })
})
