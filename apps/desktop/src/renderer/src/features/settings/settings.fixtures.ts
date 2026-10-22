// Shared Settings test data (SOLUSDEV-318): one SettingsData / TeamData builder
// instead of a copy per section test.
import { vi } from 'vitest'
import type { SettingsData } from './useSettingsData'
import type { TeamData } from '../team/useTeamData'
import type { Subscription, TeamRole } from '../../lib/api/resources'

export function subscription(overrides: Partial<Subscription> = {}): Subscription {
  return {
    user_id: 'u1',
    plan: 'basic',
    status: 'trialing',
    limits: { max_projects: 3, max_teams: 2, max_integrations: 4 },
    expires_at: null,
    seat_count: 1,
    ...overrides
  }
}

export function settingsData(overrides: Partial<SettingsData> = {}): SettingsData {
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
    subscription: subscription(),
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

export function teamData(overrides: Partial<TeamData> = {}, role: TeamRole = 'owner'): TeamData {
  return {
    status: 'ready',
    team: {
      id: 't1',
      name: 'Strider Robotics',
      is_personal: false,
      plan_status: 'trial',
      settings: { notify_project_created: true },
      created_at: '',
      member_count: 6,
      role
    },
    teams: [],
    myRole: role,
    actions: {
      updateTeam: vi.fn(async () => true),
      deleteTeam: vi.fn(async () => true),
      refresh: vi.fn(async () => undefined)
    },
    ...overrides
  } as TeamData
}
