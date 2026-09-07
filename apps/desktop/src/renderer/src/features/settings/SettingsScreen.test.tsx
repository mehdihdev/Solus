import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SettingsScreen } from './SettingsScreen'
import type { SettingsData } from './useSettingsData'
import type { TeamData } from '../team/useTeamData'
import { fakeBridge } from '../extensions/frame/testing/fixtures'
import * as bridge from '../../lib/desktopBridge'

const settingsData = vi.fn<() => SettingsData>()
const teamData = vi.fn<() => TeamData>()

vi.mock('./useSettingsData', () => ({ useSettingsData: () => settingsData() }))
vi.mock('../preferences/PreferencesCard', () => ({
  PreferencesCard: () => <div data-testid="preferences-card" />
}))
vi.mock('../team/useTeamData', () => ({ useTeamData: () => teamData() }))
vi.mock('../../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/desktopBridge')>()
  return { ...actual, getDesktopExtensionsBridge: vi.fn() }
})

function settings(overrides: Partial<SettingsData> = {}): SettingsData {
  return {
    status: 'ready',
    profile: {
      id: 'u1',
      email: 'maya@strider.dev',
      name: 'Maya K',
      avatar_url: null,
      created_at: '',
      teams: []
    },
    consent: true,
    subscription: {
      user_id: 'u1',
      plan: 'basic',
      status: 'trialing',
      limits: { max_projects: 3, max_teams: 2 },
      expires_at: null,
      seat_count: 1
    },
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

function team(status: TeamData['status'] = 'ready'): TeamData {
  return {
    status,
    team: {
      id: 't1',
      name: 'Strider Robotics',
      is_personal: false,
      plan_status: 'trial',
      settings: { notify_project_created: true },
      created_at: '',
      member_count: 1,
      role: 'owner'
    },
    loadMoreActivity: vi.fn(async () => undefined),
    teams: [],
    myRole: 'owner',
    actions: {
      updateTeam: vi.fn(async () => true),
      deleteTeam: vi.fn(async () => true),
      createTeam: vi.fn(async () => true),
      joinTeam: vi.fn(async () => null),
      createProject: vi.fn(async () => null),
      refresh: vi.fn(async () => undefined)
    }
  } as TeamData
}

beforeEach(() => {
  vi.clearAllMocks()
  settingsData.mockReturnValue(settings())
  teamData.mockReturnValue(team())
  // Default: the browser preview (no Electron bridge).
  vi.mocked(bridge.getDesktopExtensionsBridge).mockReturnValue(null)
})

describe('SettingsScreen', () => {
  it('shows a spinner while settings load', () => {
    settingsData.mockReturnValue(settings({ status: 'loading' }))
    render(<SettingsScreen />)
    expect(screen.getByTestId('settings-loading')).toBeInTheDocument()
  })

  it('hosts the "How you engineer" document (HOME H3, moved from Home in SOLUSDEV-253)', () => {
    render(<SettingsScreen />)
    expect(screen.getByTestId('preferences-card')).toBeInTheDocument()
  })

  it('renders every section when online', () => {
    render(<SettingsScreen />)
    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByText('Profile')).toBeInTheDocument()
    expect(screen.getByText('SOL')).toBeInTheDocument()
    expect(screen.getByText('Appearance')).toBeInTheDocument()
    expect(screen.getByText('Privacy')).toBeInTheDocument()
    expect(screen.getByText('Billing')).toBeInTheDocument()
    expect(screen.getByText('Integrations')).toBeInTheDocument()
    // Members live on Home since SOLUSDEV-244 / HOME H5; Settings keeps Team.
    expect(screen.queryByText('Members')).toBeNull()
    expect(screen.getByText('Team')).toBeInTheDocument()
  })

  it('hides account + team sections and shows a sign-in notice when offline', () => {
    settingsData.mockReturnValue(settings({ status: 'offline', profile: null, subscription: null }))
    teamData.mockReturnValue(team('offline'))
    render(<SettingsScreen />)
    // Local sections still render.
    expect(screen.getByText('Appearance')).toBeInTheDocument()
    expect(screen.getByText('Integrations')).toBeInTheDocument()
    // Account/team sections are gated.
    expect(screen.queryByText('Profile')).not.toBeInTheDocument()
    expect(screen.queryByText('Billing')).not.toBeInTheDocument()
    expect(screen.queryByText('Members')).not.toBeInTheDocument()
    expect(screen.getByText(/Sign in/)).toBeInTheDocument()
  })

  it('shows the Developer section only under the desktop extensions bridge', () => {
    // Browser preview: no folder picker to offer, so no section at all.
    const { unmount } = render(<SettingsScreen />)
    expect(screen.queryByText('Developer')).not.toBeInTheDocument()
    unmount()

    vi.mocked(bridge.getDesktopExtensionsBridge).mockReturnValue(fakeBridge())
    render(<SettingsScreen />)
    expect(screen.getByText('Developer')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load unpacked extension…' })).toBeInTheDocument()
  })

  it('keeps the Developer section when offline — it needs the desktop, not the API', () => {
    settingsData.mockReturnValue(settings({ status: 'offline', profile: null, subscription: null }))
    teamData.mockReturnValue(team('offline'))
    vi.mocked(bridge.getDesktopExtensionsBridge).mockReturnValue(fakeBridge())
    render(<SettingsScreen />)
    expect(screen.getByText('Developer')).toBeInTheDocument()
  })

  it('omits the team section while the team is still loading', () => {
    teamData.mockReturnValue(team('loading'))
    render(<SettingsScreen />)
    expect(screen.queryByText('Team')).not.toBeInTheDocument()
    expect(screen.getByText('Profile')).toBeInTheDocument()
  })
})
