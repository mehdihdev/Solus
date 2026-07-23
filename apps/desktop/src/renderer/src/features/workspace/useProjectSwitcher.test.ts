// Topbar project switcher data (SOLUSDEV-164): the signed-in user's active
// projects grouped by team, so they can jump between projects without going
// back Home. Degrades to an empty list offline (dev bypass / unreachable API).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useProjectSwitcher } from './useProjectSwitcher'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getMe: vi.fn(), listProjects: vi.fn() }
})

const TEAM = {
  team_id: 't1',
  name: 'Acme',
  role: 'member' as const,
  is_personal: false
} as resources.TeamSummary

const PROJECT = (id: string, archived = false): resources.Project =>
  ({
    id,
    team_id: 't1',
    name: `P-${id}`,
    description: null,
    archived_at: archived ? '2026-01-01' : null,
    created_at: '',
    updated_at: ''
  }) as resources.Project

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
})

describe('useProjectSwitcher', () => {
  it('is offline (empty) when not authenticated', () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    const { result } = renderHook(() => useProjectSwitcher())
    expect(result.current.status).toBe('offline')
    expect(vi.mocked(resources.getMe)).not.toHaveBeenCalled()
  })

  it('groups active projects by team, dropping archived ones', async () => {
    vi.mocked(resources.getMe).mockResolvedValue({
      id: 'u1',
      email: 'a@b.dev',
      name: null,
      avatar_url: null,
      created_at: '',
      teams: [TEAM]
    })
    vi.mocked(resources.listProjects).mockResolvedValue([PROJECT('1'), PROJECT('2', true)])
    const { result } = renderHook(() => useProjectSwitcher())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.groups).toHaveLength(1)
    expect(result.current.groups[0].team.name).toBe('Acme')
    expect(result.current.groups[0].projects).toHaveLength(1)
    expect(result.current.groups[0].projects[0].id).toBe('1')
  })

  it('degrades to offline when the API is unreachable', async () => {
    vi.mocked(resources.getMe).mockRejectedValue(new Error('unreachable'))
    const { result } = renderHook(() => useProjectSwitcher())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.groups).toEqual([])
  })
})
