// SOLUSDEV-317: the org members roster with optimistic assign / unassign.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as gh from '../../lib/api/resources.teamGithub'
import { liveKeys, resetLiveRevisions } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'
import { ASSIGNED, FREE, NOOR, SERVER_ASSIGNMENT } from './githubOrgRoster.fixtures'
import { useGithubOrgRoster, type RosterDeps } from './useGithubOrgRoster'

vi.mock('../../lib/api/resources.teamGithub', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources.teamGithub')>()),
  listTeamGithubMembers: vi.fn(),
  assignGithubMember: vi.fn(),
  unassignGithubMember: vi.fn()
}))

const mocked = {
  list: vi.mocked(gh.listTeamGithubMembers),
  assign: vi.mocked(gh.assignGithubMember),
  unassign: vi.mocked(gh.unassignGithubMember)
}

function deps(over: Partial<RosterDeps> = {}): RosterDeps {
  return {
    teamId: 't1',
    enabled: true,
    inviteMember: vi.fn(),
    onMembersStale: vi.fn(),
    onLinkStale: vi.fn(),
    ...over
  }
}

async function ready(d: RosterDeps = deps()) {
  const hook = renderHook((p: RosterDeps) => useGithubOrgRoster(p), { initialProps: d })
  await waitFor(() => expect(hook.result.current.status).toBe('ready'))
  return hook
}

beforeEach(() => {
  vi.resetAllMocks()
  resetLiveRevisions()
  mocked.list.mockResolvedValue({ items: [FREE, ASSIGNED], total: 2, cursor: null })
})

describe('useGithubOrgRoster — loading', () => {
  it('never lists the roster when disabled (non-managers)', () => {
    const { result } = renderHook(() => useGithubOrgRoster(deps({ enabled: false })))
    expect(result.current.status).toBe('idle')
    expect(mocked.list).not.toHaveBeenCalled()
  })

  it('loads the first page with its total and cursor', async () => {
    mocked.list.mockResolvedValue({ items: [FREE], total: 9, cursor: 'c2' })
    const { result } = await ready()
    expect(result.current.items).toEqual([FREE])
    expect(result.current.total).toBe(9)
    expect(result.current.cursor).toBe('c2')
    expect(mocked.list).toHaveBeenCalledWith('t1', { limit: 50 })
  })

  it('appends the next page on loadMore', async () => {
    mocked.list.mockResolvedValueOnce({ items: [FREE], total: 2, cursor: 'c2' })
    mocked.list.mockResolvedValueOnce({ items: [ASSIGNED], total: 2, cursor: null })
    const { result } = await ready()
    await act(() => result.current.actions.loadMore())
    expect(result.current.items.map((m) => m.github_id)).toEqual([7, 8])
    expect(result.current.cursor).toBeNull()
    expect(mocked.list).toHaveBeenLastCalledWith('t1', { cursor: 'c2', limit: 50 })
  })

  it('fails honestly and recovers on retry', async () => {
    mocked.list.mockRejectedValueOnce(new Error('net'))
    const { result } = renderHook(() => useGithubOrgRoster(deps()))
    await waitFor(() => expect(result.current.status).toBe('failed'))
    await act(() => result.current.actions.retry())
    expect(result.current.status).toBe('ready')
    expect(result.current.items).toHaveLength(2)
  })
})

describe('useGithubOrgRoster — live', () => {
  it.each([liveKeys.teamMembers('t1'), liveKeys.team('t1')])(
    'refetches quietly on %s, keeping every loaded row',
    async (key) => {
      const { result } = await ready()
      mocked.list.mockResolvedValue({ items: [ASSIGNED], total: 1, cursor: null })
      await bumpLive(key)
      await waitFor(() => expect(result.current.items).toEqual([ASSIGNED]))
      expect(result.current.status).toBe('ready')
      expect(mocked.list).toHaveBeenLastCalledWith('t1', { limit: 50 })
    }
  )

  it('drops a stale page after a team switch', async () => {
    let release: (v: gh.GithubMembersPage) => void = () => undefined
    mocked.list.mockImplementationOnce(() => new Promise((r) => (release = r)))
    const hook = renderHook((p: RosterDeps) => useGithubOrgRoster(p), { initialProps: deps() })
    hook.rerender(deps({ teamId: 't2' }))
    await waitFor(() => expect(hook.result.current.status).toBe('ready'))
    await act(async () => release({ items: [FREE], total: 1, cursor: null }))
    expect(hook.result.current.items).toEqual([FREE, ASSIGNED])
  })
})

describe('useGithubOrgRoster — assign', () => {
  it('shows the assignment at once, then the server copy, and announces it', async () => {
    let release: (a: gh.GithubAssignment) => void = () => undefined
    mocked.assign.mockImplementation(() => new Promise((r) => (release = r)))
    const { result } = await ready()
    act(() => void result.current.actions.assign(7, NOOR))
    const row = result.current.items[0]
    expect(row.solus_status).toBe('member')
    expect(row.assignment).toMatchObject({ user_id: 'u2', name: 'Noor', source: 'admin' })
    expect(result.current.rows[7].pending).toBe(true)
    await act(async () => release(SERVER_ASSIGNMENT))
    expect(result.current.items[0].assignment).toEqual(SERVER_ASSIGNMENT)
    expect(result.current.rows[7]).toMatchObject({ pending: false, error: null })
    expect(result.current.rows[7].announce).toEqual({
      key: 'assign_done',
      vars: { login: 'octo', name: 'Noor' }
    })
    expect(mocked.assign).toHaveBeenCalledWith('t1', 7, 'u2')
  })

  it('never blocks other rows while one is pending', async () => {
    mocked.assign.mockImplementation(() => new Promise(() => undefined))
    const { result } = await ready()
    act(() => void result.current.actions.assign(7, NOOR))
    expect(result.current.rows[8]).toBeUndefined()
  })

  it('drops the result of an assign whose team changed mid-flight', async () => {
    let release: (a: gh.GithubAssignment) => void = () => undefined
    mocked.assign.mockImplementation(() => new Promise((r) => (release = r)))
    const hook = await ready()
    act(() => void hook.result.current.actions.assign(7, NOOR))
    hook.rerender(deps({ teamId: 't2' }))
    await waitFor(() => expect(hook.result.current.status).toBe('ready'))
    await act(async () => release(SERVER_ASSIGNMENT))
    expect(hook.result.current.items[0]).toEqual(FREE)
    expect(hook.result.current.rows[7]).toBeUndefined()
  })
})
