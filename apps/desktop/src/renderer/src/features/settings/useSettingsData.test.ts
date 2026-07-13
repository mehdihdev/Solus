// Settings data hook: parallel load of profile/settings/subscription, offline
// fallback, tolerant of a missing subscription, and optimistic mutations that
// revert + surface the API error envelope on failure.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useSettingsData } from './useSettingsData'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSettingsStore } from '../../store/settingsStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getMe: vi.fn(),
    getSettings: vi.fn(),
    getSubscription: vi.fn(),
    updateSolMode: vi.fn(),
    updateConsent: vi.fn(),
    updateProfile: vi.fn()
  }
})

const ME: resources.Me = {
  id: 'u1',
  email: 'maya@strider.dev',
  name: 'Maya K',
  avatar_url: null,
  created_at: '2026-07-01T00:00:00Z',
  teams: []
}
const SETTINGS: resources.UserSettings = {
  sol_mode: 'guide',
  data_collection_consent: true,
  onboarding_step: 'done'
}
const SUB: resources.Subscription = {
  user_id: 'u1',
  plan: 'pro',
  status: 'trialing',
  limits: { max_integrations: null, max_projects: null, max_teams: null },
  expires_at: '2026-07-22T00:00:00Z',
  seat_count: 3
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useSettingsStore.setState({ solMode: 'Guide' })
  vi.mocked(resources.getMe).mockResolvedValue(ME)
  vi.mocked(resources.getSettings).mockResolvedValue(SETTINGS)
  vi.mocked(resources.getSubscription).mockResolvedValue(SUB)
})

describe('useSettingsData — loading', () => {
  it('is offline when the workspace is not linked', () => {
    const { result } = renderHook(() => useSettingsData())
    expect(result.current.status).toBe('offline')
  })

  it('loads profile, consent, and subscription when linked', async () => {
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.profile?.name).toBe('Maya K')
    expect(result.current.consent).toBe(true)
    expect(result.current.subscription?.plan).toBe('pro')
  })

  it('reconciles SOL mode from the backend into the local store', async () => {
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    vi.mocked(resources.getSettings).mockResolvedValue({ ...SETTINGS, sol_mode: 'expert' })
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(useSettingsStore.getState().solMode).toBe('Expert')
  })

  it('stays ready when the subscription is missing (404)', async () => {
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    vi.mocked(resources.getSubscription).mockRejectedValue(
      new ApiError(404, 'not_found', 'No subscription')
    )
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.subscription).toBeNull()
  })

  it('is offline when the core profile load fails', async () => {
    useWorkspaceStore.setState({ linked: true, teamId: 't1' })
    vi.mocked(resources.getSettings).mockRejectedValue(new ApiError(500, 'server', 'boom'))
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })
})

describe('useSettingsData — SOL mode mutation', () => {
  beforeEach(() => useWorkspaceStore.setState({ linked: true, teamId: 't1' }))

  it('persists a mode change to the backend and the local store', async () => {
    vi.mocked(resources.updateSolMode).mockResolvedValue({})
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.setSolMode('Expert')
    })
    expect(vi.mocked(resources.updateSolMode)).toHaveBeenCalledWith('Expert')
    expect(useSettingsStore.getState().solMode).toBe('Expert')
  })

  it('reverts the local store and surfaces the error on failure', async () => {
    vi.mocked(resources.updateSolMode).mockRejectedValue(
      new ApiError(403, 'forbidden', 'Not allowed')
    )
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.setSolMode('Expert')
    })
    expect(useSettingsStore.getState().solMode).toBe('Guide')
    expect(result.current.errors.sol_mode).toBe('Not allowed')
  })
})

describe('useSettingsData — consent mutation', () => {
  beforeEach(() => useWorkspaceStore.setState({ linked: true, teamId: 't1' }))

  it('optimistically flips consent and persists it', async () => {
    vi.mocked(resources.updateConsent).mockResolvedValue({
      ...SETTINGS,
      data_collection_consent: false
    })
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.setConsent(false)
    })
    expect(vi.mocked(resources.updateConsent)).toHaveBeenCalledWith(false)
    expect(result.current.consent).toBe(false)
  })

  it('reverts consent and surfaces the error on failure', async () => {
    vi.mocked(resources.updateConsent).mockRejectedValue(new ApiError(500, 'server', 'save failed'))
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.setConsent(false)
    })
    expect(result.current.consent).toBe(true)
    expect(result.current.errors.consent).toBe('save failed')
  })
})

describe('useSettingsData — profile name mutation', () => {
  beforeEach(() => useWorkspaceStore.setState({ linked: true, teamId: 't1' }))

  it('saves a new display name', async () => {
    vi.mocked(resources.updateProfile).mockResolvedValue({ ...ME, name: 'Ada' })
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let ok = false
    await act(async () => {
      ok = await result.current.actions.updateName('Ada')
    })
    expect(ok).toBe(true)
    expect(vi.mocked(resources.updateProfile)).toHaveBeenCalledWith({ name: 'Ada' })
    expect(result.current.profile?.name).toBe('Ada')
  })

  it('rejects a blank name without calling the API', async () => {
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let ok = true
    await act(async () => {
      ok = await result.current.actions.updateName('   ')
    })
    expect(ok).toBe(false)
    expect(vi.mocked(resources.updateProfile)).not.toHaveBeenCalled()
    expect(result.current.errors.name).toBeTruthy()
  })

  it('surfaces the error envelope when the save fails', async () => {
    vi.mocked(resources.updateProfile).mockRejectedValue(
      new ApiError(422, 'validation_error', 'Name too long')
    )
    const { result } = renderHook(() => useSettingsData())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.updateName('Ada')
    })
    expect(result.current.errors.name).toBe('Name too long')
  })
})
