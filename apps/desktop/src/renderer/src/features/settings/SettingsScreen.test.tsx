import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsScreen } from './SettingsScreen'
import type { SettingsData } from './useSettingsData'
import type { TeamData } from '../team/useTeamData'
import type { AccountConnectionsData } from '../workspace/useAccountConnections'
import { fakeBridge } from '../extensions/frame/testing/fixtures'
import { fakeSolBridge, SOL_STATE } from '../sol/solWindow.fixtures'
import * as bridge from '../../lib/desktopBridge'
import {
  settingsData as buildSettings,
  subscription,
  teamData as buildTeam
} from './settings.fixtures'
import { useShellStore } from '../workspace/shellStore'

const settingsData = vi.fn<() => SettingsData>()
const teamData = vi.fn<() => TeamData>()
const accountsData = vi.fn<() => AccountConnectionsData>()

vi.mock('./useSettingsData', () => ({ useSettingsData: () => settingsData() }))
vi.mock('./useCredits', () => ({ useCredits: () => ({ balance: 1840, unlimited: false }) }))
vi.mock('../preferences/PreferencesCard', () => ({
  PreferencesCard: () => <div data-testid="preferences-card" />
}))
vi.mock('../team/useTeamData', () => ({ useTeamData: () => teamData() }))
vi.mock('../workspace/useAccountConnections', () => ({
  useAccountConnections: () => accountsData()
}))
vi.mock('../../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/desktopBridge')>()
  return { ...actual, getDesktopExtensionsBridge: vi.fn(), getDesktopSolBridge: vi.fn() }
})

function accounts(overrides: Partial<AccountConnectionsData> = {}): AccountConnectionsData {
  return {
    status: 'ready',
    connections: [],
    legacy: [],
    refresh: vi.fn(async () => undefined),
    revoke: vi.fn(async () => true),
    move: vi.fn(async () => true),
    ...overrides
  }
}

const BLOCKED = {
  ...SOL_STATE,
  capture: {
    mode: 'needs-permission' as const,
    message: 'Screen capture needs the Screen Recording permission for Solus.',
    settingsUrl: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'
  }
}

const region = (name: string): HTMLElement => screen.getByRole('region', { name })

beforeEach(() => {
  vi.clearAllMocks()
  useShellStore.getState().reset()
  settingsData.mockReturnValue(buildSettings())
  teamData.mockReturnValue(buildTeam())
  accountsData.mockReturnValue(accounts())
  // Default: the browser preview (no Electron bridges).
  vi.mocked(bridge.getDesktopExtensionsBridge).mockReturnValue(null)
  vi.mocked(bridge.getDesktopSolBridge).mockReturnValue(null)
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  delete (Element.prototype as Partial<Element>).scrollIntoView
})

describe('SettingsScreen — layout', () => {
  it('shows a spinner while settings load', () => {
    settingsData.mockReturnValue(buildSettings({ status: 'loading' }))
    render(<SettingsScreen />)
    expect(screen.getByTestId('settings-loading')).toBeInTheDocument()
  })

  it('renders every section, sidebar and page, when online', () => {
    render(<SettingsScreen />)
    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    for (const name of [
      'Profile',
      'SOL',
      'Appearance',
      'Plan & usage',
      'Connected tools',
      'Team',
      'Privacy & data',
      'About & legal'
    ]) {
      expect(region(name)).toBeInTheDocument()
    }
    expect(screen.getByTestId('preferences-card')).toBeInTheDocument()
    expect(screen.queryByText(/density/i)).toBeNull()
    expect(screen.queryByText('Onshape panel')).toBeNull()
  })

  it('hides account + team sections and shows a sign-in notice when offline', () => {
    settingsData.mockReturnValue(
      buildSettings({ status: 'offline', profile: null, subscription: null })
    )
    teamData.mockReturnValue(buildTeam({ status: 'offline' }))
    accountsData.mockReturnValue(accounts({ status: 'offline' }))
    render(<SettingsScreen />)
    expect(region('Appearance')).toBeInTheDocument()
    expect(region('About & legal')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Profile' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Plan & usage' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Connected tools' })).toBeNull()
    expect(screen.getByText(/Sign in/)).toBeInTheDocument()
  })

  it('shows Developer only under the desktop extensions bridge, online or not', () => {
    const { unmount } = render(<SettingsScreen />)
    expect(screen.queryByRole('region', { name: 'Developer' })).toBeNull()
    unmount()
    vi.mocked(bridge.getDesktopExtensionsBridge).mockReturnValue(fakeBridge())
    settingsData.mockReturnValue(buildSettings({ status: 'offline', profile: null }))
    render(<SettingsScreen />)
    expect(region('Developer')).toBeInTheDocument()
  })

  it('omits the team section while the team is still loading', () => {
    teamData.mockReturnValue(buildTeam({ status: 'loading' }))
    render(<SettingsScreen />)
    expect(screen.queryByRole('region', { name: 'Team' })).toBeNull()
    expect(region('Profile')).toBeInTheDocument()
  })
})

describe('SettingsScreen — sidebar', () => {
  it('scrolls to the section a nav entry names', async () => {
    render(<SettingsScreen />)
    const nav = screen.getByRole('navigation', { name: 'Settings sections' })
    await userEvent.click(within(nav).getByRole('button', { name: 'Appearance' }))
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    expect(vi.mocked(Element.prototype.scrollIntoView).mock.contexts[0]).toBe(region('Appearance'))
  })

  it('filters both the nav and the page as the user types', async () => {
    render(<SettingsScreen />)
    await userEvent.type(screen.getByRole('searchbox', { name: 'Find a setting' }), 'theme')
    expect(region('Appearance')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Profile' })).toBeNull()
    const nav = screen.getByRole('navigation', { name: 'Settings sections' })
    expect(within(nav).queryByRole('button', { name: 'Profile' })).toBeNull()
  })

  it('lists only the sections the page actually shows', () => {
    settingsData.mockReturnValue(buildSettings({ status: 'offline', profile: null }))
    render(<SettingsScreen />)
    const nav = screen.getByRole('navigation', { name: 'Settings sections' })
    expect(within(nav).queryByRole('button', { name: 'Profile' })).toBeNull()
    expect(within(nav).getByRole('button', { name: 'Appearance' })).toBeInTheDocument()
  })
})

describe('SettingsScreen — needs attention', () => {
  it('turns a blocked capture into an action card that opens the pane through main', async () => {
    const sol = fakeSolBridge(BLOCKED)
    vi.mocked(bridge.getDesktopSolBridge).mockReturnValue(sol)
    render(<SettingsScreen />)
    expect(
      await screen.findByRole('group', { name: "SOL can't see your screen yet" })
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Needs attention/ })).toHaveTextContent('1')
    await userEvent.click(screen.getByRole('button', { name: 'Open Screen Recording settings' }))
    expect(sol.openCaptureSettings).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Turn off screen capture' }))
    expect(sol.setScreenIntelligence).toHaveBeenCalledWith(false)
  })

  it('drops the Needs attention entry while a search hides the cards', async () => {
    vi.mocked(bridge.getDesktopSolBridge).mockReturnValue(fakeSolBridge(BLOCKED))
    render(<SettingsScreen />)
    expect(await screen.findByRole('button', { name: /Needs attention/ })).toBeInTheDocument()
    await userEvent.type(screen.getByRole('searchbox', { name: 'Find a setting' }), 'theme')
    expect(screen.queryByRole('button', { name: /Needs attention/ })).toBeNull()
  })

  it('counts down an ending trial and routes to Billing', async () => {
    const onNavigate = vi.fn()
    settingsData.mockReturnValue(
      buildSettings({
        subscription: subscription({
          expires_at: new Date(Date.now() + 5 * 86_400_000).toISOString()
        })
      })
    )
    render(<SettingsScreen onNavigate={onNavigate} />)
    expect(screen.getByText(/Your trial ends in 5 days/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Choose a plan' }))
    expect(onNavigate).toHaveBeenCalledWith('billing')
  })
})

describe('SettingsScreen — links out', () => {
  it('Open team page lands on Home’s team pane', async () => {
    const onNavigate = vi.fn()
    render(<SettingsScreen onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole('button', { name: /Open team page/ }))
    expect(useShellStore.getState().homeView).toBe('members')
    expect(onNavigate).toHaveBeenCalledWith('home')
  })

  it('Connect a tool lands on Home › Connected accounts', async () => {
    const onNavigate = vi.fn()
    render(<SettingsScreen onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole('button', { name: 'Connect a tool' }))
    expect(useShellStore.getState().homeView).toBe('accounts')
    expect(onNavigate).toHaveBeenCalledWith('home')
  })

  it('Open Billing goes to the Billing page', async () => {
    const onNavigate = vi.fn()
    render(<SettingsScreen onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole('button', { name: /Open Billing/ }))
    expect(onNavigate).toHaveBeenCalledWith('billing')
  })
})
