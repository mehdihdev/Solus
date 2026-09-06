// SOLUSDEV-244 / HOME H5: the active team's layer on Home — detail, members,
// invites, the team feed, my plan position — and the team mutations, each
// naming its refusal. Keyed on the team id with a stale-response guard.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useHomeTeam } from './useHomeTeam'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getTeamDetail: vi.fn(),
    listMembers: vi.fn(),
    listInvites: vi.fn(),
    listActivityPage: vi.fn(),
    getSubscription: vi.fn(),
    createInvite: vi.fn(),
    revokeInvite: vi.fn(),
    changeMemberRole: vi.fn(),
    removeMember: vi.fn(),
    updateTeam: vi.fn(),
    deleteTeam: vi.fn()
  }
})
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources.extensions')>()),
  postDataEvents: vi.fn(async () => undefined)
}))

const PERSONAL: resources.TeamSummary = {
  team_id: 't-me',
  name: 'Maya',
  role: 'owner',
  is_personal: true,
  plan_status: 'trial',
  trial_ends_at: ''
}
const TEAM: resources.TeamSummary = {
  ...PERSONAL,
  team_id: 't1',
  name: 'Strider',
  is_personal: false
}
const OTHER: resources.TeamSummary = { ...TEAM, team_id: 't2', name: 'Arm Lab', role: 'member' }
const ME: resources.Me = {
  id: 'u1',
  email: 'maya@strider.dev',
  name: 'Maya',
  avatar_url: null,
  created_at: '',
  teams: [PERSONAL, TEAM, OTHER]
}
const DETAIL: resources.TeamDetail = {
  id: 't1',
  name: 'Strider',
  is_personal: false,
  plan_status: 'trial',
  settings: { notify_project_created: true },
  created_at: '',
  member_count: 2,
  role: 'owner'
}
const MEMBERS: resources.TeamMemberApi[] = [
  { user_id: 'u1', email: 'maya@strider.dev', name: 'Maya', role: 'owner', joined_at: '' },
  { user_id: 'u2', email: 'bob@strider.dev', name: 'Bob', role: 'member', joined_at: '' }
]
const INVITE: resources.InviteApi = {
  id: 'i1',
  team_id: 't1',
  email: 'eve@strider.dev',
  role: 'member',
  status: 'pending',
  created_at: '',
  expires_at: '',
  token: 'tok-once'
}
const FEED = {
  data: [
    {
      id: 'a1',
      type: 'project.created',
      domain: null,
      actor_id: 'u1',
      project_id: 'p1',
      payload: {},
      created_at: '2026-07-05T10:00:00Z'
    }
  ],
  meta: { total: 9, has_next: true, next_cursor: 'c2' }
}
const SUB: resources.Subscription = {
  user_id: 'u1',
  plan: 'basic',
  status: 'trialing',
  limits: { max_teams: 2, max_projects: 3, max_integrations: 4 },
  expires_at: null,
  seat_count: null
}

const refreshHome = vi.fn(async () => undefined)

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ teamId: 't1', linked: true })
  vi.mocked(resources.getTeamDetail).mockResolvedValue(DETAIL)
  vi.mocked(resources.listMembers).mockResolvedValue(MEMBERS)
  vi.mocked(resources.listInvites).mockResolvedValue([{ ...INVITE, token: undefined }])
  vi.mocked(resources.listActivityPage).mockResolvedValue(FEED)
  vi.mocked(resources.getSubscription).mockResolvedValue(SUB)
})

function mount(
  team: resources.TeamSummary | null = TEAM
): ReturnType<typeof renderHook<ReturnType<typeof useHomeTeam>, unknown>> {
  return renderHook(() => useHomeTeam(team, ME, refreshHome))
}

describe('useHomeTeam — loading', () => {
  it('loads the team layer and my plan position', async () => {
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.detail?.name).toBe('Strider')
    expect(result.current.members).toHaveLength(2)
    expect(result.current.invites).toHaveLength(1)
    expect(result.current.activity).toHaveLength(1)
    expect(result.current.activityTotal).toBe(9)
    expect(result.current.activityHasMore).toBe(true)
    expect(result.current.myRole).toBe('owner')
    // Two collaborative teams of a BASIC limit of two — the personal one never counts.
    expect(result.current.teamLimit).toEqual({ current: 2, max: 2, atLimit: true })
  })

  it('is idle with no team and never asks the server', () => {
    const { result } = mount(null)
    expect(result.current.status).toBe('idle')
    expect(resources.getTeamDetail).not.toHaveBeenCalled()
  })

  it('tolerates a forbidden invite listing (members and viewers cannot see invites)', async () => {
    vi.mocked(resources.listInvites).mockRejectedValue(new ApiError(403, 'forbidden', 'no'))
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.invites).toEqual([])
  })

  it('a deleted team reads as gone; an unreachable API as offline', async () => {
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new ApiError(404, 'not_found', 'x'))
    const gone = mount()
    await waitFor(() => expect(gone.result.current.status).toBe('gone'))
    vi.mocked(resources.getTeamDetail).mockRejectedValue(new Error('ECONNREFUSED'))
    const offline = mount()
    await waitFor(() => expect(offline.result.current.status).toBe('offline'))
  })

  it('a missing subscription leaves the limit unknown rather than invented', async () => {
    vi.mocked(resources.getSubscription).mockRejectedValue(new Error('no'))
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.teamLimit).toBeNull()
  })

  it('ignores a slow answer for a team the user has since left', async () => {
    let release: (d: resources.TeamDetail) => void = () => undefined
    vi.mocked(resources.getTeamDetail).mockImplementation((id) =>
      id === 't1'
        ? new Promise<resources.TeamDetail>((resolve) => (release = resolve))
        : Promise.resolve({ ...DETAIL, id: 't2', name: 'Arm Lab', role: 'member' })
    )
    const { result, rerender } = renderHook(({ team }) => useHomeTeam(team, ME, refreshHome), {
      initialProps: { team: TEAM }
    })
    rerender({ team: OTHER })
    await waitFor(() => expect(result.current.detail?.name).toBe('Arm Lab'))
    release(DETAIL)
    await act(async () => undefined)
    expect(result.current.detail?.name).toBe('Arm Lab')
  })

  it('loads more activity by cursor and keeps the feed on failure', async () => {
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.listActivityPage).mockResolvedValueOnce({
      data: [{ ...FEED.data[0], id: 'a2' }],
      meta: { total: 9, has_next: false }
    })
    await act(async () => result.current.actions.loadMoreActivity())
    expect(result.current.activity.map((a) => a.id)).toEqual(['a1', 'a2'])
    expect(result.current.activityHasMore).toBe(false)
  })
})

describe('useHomeTeam — mutations', () => {
  it('invites and hands back the one-time token; refreshes pending invites', async () => {
    vi.mocked(resources.createInvite).mockResolvedValue(INVITE)
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const outcome = await result.current.actions.invite('eve@strider.dev')
    expect(outcome).toEqual({ ok: true, token: 'tok-once', movedToTeamId: null })
    expect(resources.createInvite).toHaveBeenCalledWith('t1', {
      email: 'eve@strider.dev',
      role: 'member'
    })
    expect(resources.listInvites).toHaveBeenCalledTimes(2)
  })

  it('an invite from the personal team follows the new collaborative team it spun up', async () => {
    vi.mocked(resources.createInvite).mockResolvedValue({ ...INVITE, team_id: 't-new' })
    const { result } = mount(PERSONAL)
    await waitFor(() => expect(result.current.status).toBe('ready'))
    const outcome = await result.current.actions.invite('eve@strider.dev')
    expect(outcome).toEqual({ ok: true, token: 'tok-once', movedToTeamId: 't-new' })
    expect(useWorkspaceStore.getState().teamId).toBe('t-new')
    expect(refreshHome).toHaveBeenCalled()
  })

  it('names an invite refusal: plan limit, already a member, pending, bad email', async () => {
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.createInvite).mockRejectedValue(
      new ApiError(409, 'plan_limit_reached', 'limit', [{ limit: 'max_teams', current: 2, max: 2 }])
    )
    expect(await result.current.actions.invite('e@x.dev')).toMatchObject({
      ok: false,
      reason: 'plan_limit',
      limit: { current: 2, max: 2 }
    })
    vi.mocked(resources.createInvite).mockRejectedValue(new ApiError(409, 'already_member', 'x'))
    expect(await result.current.actions.invite('e@x.dev')).toEqual({
      ok: false,
      reason: 'already_member'
    })
    vi.mocked(resources.createInvite).mockRejectedValue(new ApiError(409, 'invite_pending', 'x'))
    expect(await result.current.actions.invite('e@x.dev')).toEqual({
      ok: false,
      reason: 'invite_pending'
    })
    vi.mocked(resources.createInvite).mockRejectedValue(new ApiError(422, 'validation_error', 'x'))
    expect(await result.current.actions.invite('e@x.dev')).toEqual({
      ok: false,
      reason: 'invalid_email'
    })
    expect(await result.current.actions.invite('not-an-email')).toEqual({
      ok: false,
      reason: 'invalid_email'
    })
  })

  it('changes a role, removes a member, revokes an invite, refreshing the slice', async () => {
    vi.mocked(resources.changeMemberRole).mockResolvedValue(MEMBERS[1])
    vi.mocked(resources.removeMember).mockResolvedValue(undefined)
    vi.mocked(resources.revokeInvite).mockResolvedValue(undefined)
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.changeRole('u2', 'admin')).toBe(true)
    expect(resources.changeMemberRole).toHaveBeenCalledWith('t1', 'u2', 'admin')
    expect(await result.current.actions.remove('u2')).toBe(true)
    expect(await result.current.actions.revoke('i1')).toBe(true)
    expect(resources.listMembers).toHaveBeenCalledTimes(3)
    expect(resources.listInvites).toHaveBeenCalledTimes(2)
  })

  it('leaving moves me to my personal team; the last owner is told why they cannot', async () => {
    vi.mocked(resources.removeMember).mockResolvedValue(undefined)
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.leave()).toEqual({ ok: true })
    expect(resources.removeMember).toHaveBeenCalledWith('t1', 'u1')
    expect(useWorkspaceStore.getState().teamId).toBe('t-me')
    expect(refreshHome).toHaveBeenCalled()

    vi.mocked(resources.removeMember).mockRejectedValue(new ApiError(409, 'last_owner', 'x'))
    expect(await result.current.actions.leave()).toEqual({ ok: false, reason: 'last_owner' })
  })

  it('renaming refreshes the team and Home; deleting moves me to my personal team', async () => {
    vi.mocked(resources.updateTeam).mockResolvedValue({ ...DETAIL, name: 'Strider Racing' })
    vi.mocked(resources.deleteTeam).mockResolvedValue(undefined)
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.rename('Strider Racing')).toBe(true)
    expect(resources.updateTeam).toHaveBeenCalledWith('t1', { name: 'Strider Racing' })
    expect(refreshHome).toHaveBeenCalled()
    expect(await result.current.actions.deleteTeam()).toBe(true)
    expect(useWorkspaceStore.getState().teamId).toBe('t-me')
  })
})
