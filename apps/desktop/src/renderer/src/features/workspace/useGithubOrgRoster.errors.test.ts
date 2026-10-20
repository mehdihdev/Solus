// SOLUSDEV-317: assign / unassign rollback on every refusal, and invites.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as gh from '../../lib/api/resources.teamGithub'
import { ApiError } from '../../lib/api/envelope.types'
import { liveKeys, resetLiveRevisions } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'
import { ASSIGNED, FREE, NOOR } from './githubOrgRoster.fixtures'
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

function deps(): RosterDeps {
  return {
    teamId: 't1',
    enabled: true,
    inviteMember: vi.fn(),
    onMembersStale: vi.fn(),
    onLinkStale: vi.fn()
  }
}

async function ready(d: RosterDeps = deps()) {
  const hook = renderHook(() => useGithubOrgRoster(d))
  await waitFor(() => expect(hook.result.current.status).toBe('ready'))
  return hook
}

const refusal = (code: string, login?: string): ApiError =>
  new ApiError(409, code, 'm', login ? [{ github_id: 1, github_login: login }] : undefined)

beforeEach(() => {
  vi.resetAllMocks()
  resetLiveRevisions()
  mocked.list.mockResolvedValue({ items: [FREE, ASSIGNED], total: 2, cursor: null })
})

describe('useGithubOrgRoster — assign refusals roll back', () => {
  it.each([
    ['not_a_team_member', { key: 'not_a_team_member', vars: {} }],
    ['not_an_org_member', { key: 'assign_not_org_member', vars: {} }],
    ['github_identity_verified', { key: 'github_identity_verified', vars: { login: 'octo' } }],
    [
      'member_has_verified_github',
      { key: 'member_has_verified_github', vars: { name: 'Noor', other: 'noor-x' } }
    ],
    [
      'member_already_assigned',
      { key: 'member_already_assigned', vars: { name: 'Noor', other: 'noor-x' } }
    ],
    ['installation_suspended', { key: 'suspended', vars: {} }],
    ['internal_error', { key: 'assign_failed', vars: {} }]
  ])('%s', async (code, problem) => {
    mocked.assign.mockRejectedValue(refusal(code, 'noor-x'))
    const { result } = await ready()
    await act(() => result.current.actions.assign(7, NOOR))
    expect(result.current.items[0]).toEqual(FREE)
    expect(result.current.rows[7]).toMatchObject({ pending: false, error: problem })
  })

  it('refetches the members on not_a_team_member', async () => {
    const d = deps()
    mocked.assign.mockRejectedValue(refusal('not_a_team_member'))
    const { result } = await ready(d)
    await act(() => result.current.actions.assign(7, NOOR))
    expect(d.onMembersStale).toHaveBeenCalled()
  })

  it.each(['not_an_org_member', 'github_identity_verified'])(
    'refetches the roster on %s',
    async (code) => {
      mocked.assign.mockRejectedValue(refusal(code))
      const { result } = await ready()
      await act(() => result.current.actions.assign(7, NOOR))
      await waitFor(() => expect(mocked.list).toHaveBeenCalledTimes(2))
    }
  )

  it.each(['installation_missing', 'installation_suspended'])(
    'asks the card to refresh on %s',
    async (code) => {
      const d = deps()
      mocked.assign.mockRejectedValue(refusal(code))
      const { result } = await ready(d)
      await act(() => result.current.actions.assign(7, NOOR))
      expect(d.onLinkStale).toHaveBeenCalled()
    }
  )
})

describe('useGithubOrgRoster — unassign', () => {
  it('clears at once and announces', async () => {
    mocked.unassign.mockResolvedValue(undefined)
    const { result } = await ready()
    await act(() => result.current.actions.unassign(8))
    expect(result.current.items[1]).toMatchObject({
      assignment: null,
      solus_status: 'not_on_solus'
    })
    expect(result.current.rows[8].announce).toEqual({
      key: 'unassign_done',
      vars: { login: 'noor-a' }
    })
    expect(mocked.unassign).toHaveBeenCalledWith('t1', 8)
  })

  it('rolls back with an error on failure', async () => {
    mocked.unassign.mockRejectedValue(new Error('net'))
    const { result } = await ready()
    await act(() => result.current.actions.unassign(8))
    expect(result.current.items[1]).toEqual(ASSIGNED)
    expect(result.current.rows[8].error).toEqual({ key: 'assign_failed', vars: {} })
  })

  it('refetches silently on assignment_missing', async () => {
    mocked.unassign.mockRejectedValue(new ApiError(404, 'assignment_missing', 'm'))
    const { result } = await ready()
    await act(() => result.current.actions.unassign(8))
    expect(result.current.rows[8].error).toBeNull()
    await waitFor(() => expect(mocked.list).toHaveBeenCalledTimes(2))
  })
})

describe('useGithubOrgRoster — invite', () => {
  it('marks the row invited and hands back the token', async () => {
    const d = deps()
    vi.mocked(d.inviteMember).mockResolvedValue({ ok: true, token: 'tok' })
    const { result } = await ready(d)
    let outcome: unknown
    await act(async () => {
      outcome = await result.current.actions.invite(FREE)
    })
    expect(outcome).toEqual({ ok: true, token: 'tok' })
    expect(result.current.items[0].solus_status).toBe('invited')
  })

  it('keeps the row and names a plan limit on the row', async () => {
    const d = deps()
    vi.mocked(d.inviteMember).mockResolvedValue({
      ok: false,
      reason: 'plan_limit',
      limit: { code: 'plan_limit_reached', message: 'Upgrade to invite more.' } as never
    })
    const { result } = await ready(d)
    await act(async () => void (await result.current.actions.invite(FREE)))
    expect(result.current.items[0]).toEqual(FREE)
    expect(result.current.rows[7].error).toEqual({ limit: 'Upgrade to invite more.' })
  })

  it.each([
    ['not_an_org_member', 'not_an_org_member'],
    ['failed', 'invite_failed']
  ] as const)('names a %s invite refusal on the row', async (reason, key) => {
    const d = deps()
    vi.mocked(d.inviteMember).mockResolvedValue({ ok: false, reason })
    const { result } = await ready(d)
    await act(async () => void (await result.current.actions.invite(FREE)))
    expect(result.current.rows[7].error).toEqual({ key, vars: {} })
  })
})

describe('useGithubOrgRoster — races (review)', () => {
  it('a quiet load that supersedes the first and fails still ends in failed', async () => {
    let failFirst: (e: Error) => void = () => undefined
    mocked.list.mockImplementationOnce(() => new Promise((_, reject) => (failFirst = reject)))
    mocked.list.mockRejectedValueOnce(new Error('net'))
    const { result } = renderHook(() => useGithubOrgRoster(deps()))
    await bumpLive(liveKeys.team('t1'))
    await act(async () => failFirst(new Error('net')))
    await waitFor(() => expect(result.current.status).toBe('failed'))
  })

  it('ignores a Load more reply once a refetch replaced the page', async () => {
    mocked.list.mockResolvedValueOnce({ items: [FREE], total: 3, cursor: 'c2' })
    const { result } = await ready()
    let release: (p: gh.GithubMembersPage) => void = () => undefined
    mocked.list.mockImplementationOnce(() => new Promise((r) => (release = r)))
    mocked.list.mockResolvedValueOnce({ items: [FREE, ASSIGNED], total: 2, cursor: null })
    act(() => void result.current.actions.loadMore())
    await bumpLive(liveKeys.team('t1'))
    await waitFor(() => expect(result.current.cursor).toBeNull())
    await act(async () => release({ items: [ASSIGNED], total: 3, cursor: null }))
    expect(result.current.items.map((m) => m.github_id)).toEqual([7, 8])
  })

  it('ignores a second mutation on a row that is still pending', async () => {
    mocked.assign.mockImplementation(() => new Promise(() => undefined))
    const { result } = await ready()
    act(() => void result.current.actions.assign(7, NOOR))
    await act(() => result.current.actions.assign(7, NOOR))
    await act(() => result.current.actions.unassign(7))
    expect(mocked.assign).toHaveBeenCalledTimes(1)
    expect(mocked.unassign).not.toHaveBeenCalled()
  })

  it('a refetch keeps a pending row as it is on screen', async () => {
    mocked.assign.mockImplementation(() => new Promise(() => undefined))
    const { result } = await ready()
    act(() => void result.current.actions.assign(7, NOOR))
    await bumpLive(liveKeys.teamMembers('t1'))
    await waitFor(() => expect(mocked.list).toHaveBeenCalledTimes(2))
    expect(result.current.items[0].assignment?.user_id).toBe('u2')
  })
})
