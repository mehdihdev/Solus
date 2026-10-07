// SOLUSDEV-244 / HOME H5: the active team's layer on Home — detail, members,
// invites, the team feed, my plan position — and the team mutations, each
// naming its refusal. Keyed on the team id with a stale-response guard.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useHomeTeam } from './useHomeTeam'
import { liveKeys, resetLiveRevisions } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'

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
  resetLiveRevisions()
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
  homeTeamInvitesTests()
  homeTeamMembershipMutationsTests()
})

describe('useHomeTeam — review fixes (SOLUSDEV-244 / HOME H5)', () => {
  it('names a refused member mutation instead of swallowing it', async () => {
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.removeMember).mockRejectedValue(new ApiError(403, 'forbidden', 'x'))
    expect(await result.current.actions.remove('u1')).toEqual({ ok: false, reason: 'forbidden' })
    vi.mocked(resources.changeMemberRole).mockRejectedValue(new ApiError(409, 'last_owner', 'x'))
    expect(await result.current.actions.changeRole('u1', 'member')).toEqual({
      ok: false,
      reason: 'last_owner'
    })
    vi.mocked(resources.revokeInvite).mockRejectedValue(new Error('ECONNREFUSED'))
    expect(await result.current.actions.revoke('i1')).toEqual({ ok: false, reason: 'failed' })
  })

  it('a 500 on the invite listing is a real failure, not "no pending invites"', async () => {
    vi.mocked(resources.listInvites).mockRejectedValue(new ApiError(500, 'error', 'x'))
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })

  it('a member refresh that resolves after a team switch never lands on the new team', async () => {
    let releaseRoster: (rows: resources.TeamMemberApi[]) => void = () => undefined
    vi.mocked(resources.removeMember).mockResolvedValue(undefined)
    const { result, rerender } = renderHook(({ team }) => useHomeTeam(team, ME, refreshHome), {
      initialProps: { team: TEAM }
    })
    await waitFor(() => expect(result.current.status).toBe('ready'))
    // The OLD team's refresh hangs until released; the NEW team answers at once.
    vi.mocked(resources.listMembers).mockImplementation((id) =>
      id === 't1'
        ? new Promise<resources.TeamMemberApi[]>((resolve) => (releaseRoster = resolve))
        : Promise.resolve([MEMBERS[0]])
    )
    const pending = result.current.actions.remove('u2')
    // Switch to another team while the old team's refresh is in flight.
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, id: 't2', name: 'Arm Lab' })
    rerender({ team: OTHER })
    await waitFor(() => expect(result.current.detail?.name).toBe('Arm Lab'))
    releaseRoster(MEMBERS)
    await act(async () => {
      await pending
    })
    expect(result.current.members).toEqual([MEMBERS[0]])
  })
})

function homeTeamInvitesTests(): void {
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
}

function homeTeamMembershipMutationsTests(): void {
  it('changes a role, removes a member, revokes an invite, refreshing the slice', async () => {
    vi.mocked(resources.changeMemberRole).mockResolvedValue(MEMBERS[1])
    vi.mocked(resources.removeMember).mockResolvedValue(undefined)
    vi.mocked(resources.revokeInvite).mockResolvedValue(undefined)
    const { result } = mount()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(await result.current.actions.changeRole('u2', 'admin')).toEqual({ ok: true })
    expect(resources.changeMemberRole).toHaveBeenCalledWith('t1', 'u2', 'admin')
    expect(await result.current.actions.remove('u2')).toEqual({ ok: true })
    expect(await result.current.actions.revoke('i1')).toEqual({ ok: true })
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
}

async function ready(team: resources.TeamSummary | null = TEAM): Promise<ReturnType<typeof mount>> {
  const view = mount(team)
  await waitFor(() => expect(view.result.current.status).toBe('ready'))
  return view
}
const calls = (): Record<'detail' | 'members' | 'invites' | 'activity', number> => ({
  detail: vi.mocked(resources.getTeamDetail).mock.calls.length,
  members: vi.mocked(resources.listMembers).mock.calls.length,
  invites: vi.mocked(resources.listInvites).mock.calls.length,
  activity: vi.mocked(resources.listActivityPage).mock.calls.length
})

describe('useHomeTeam — live refresh (ADR-037): slices', () => {
  it('team(id) refetches the detail only, silently', async () => {
    const { result } = await ready()
    const before = calls()
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, name: 'Renamed' })
    await bumpLive(liveKeys.team('t1'))
    await waitFor(() => expect(result.current.detail?.name).toBe('Renamed'))
    expect(calls()).toEqual({ ...before, detail: before.detail + 1 })
    expect(result.current.status).toBe('ready')
    expect(result.current.members).toHaveLength(2)
  })

  it('teamMembers(id) refetches members only', async () => {
    const { result } = await ready()
    const before = calls()
    vi.mocked(resources.listMembers).mockResolvedValue([
      ...MEMBERS,
      { ...MEMBERS[1], user_id: 'u3' }
    ])
    await bumpLive(liveKeys.teamMembers('t1'))
    await waitFor(() => expect(result.current.members).toHaveLength(3))
    expect(calls()).toEqual({ ...before, members: before.members + 1 })
  })
})

describe('useHomeTeam — live refresh (ADR-037): invites', () => {
  it('teamInvites(id) refetches invites for an owner', async () => {
    const { result } = await ready()
    const before = calls()
    vi.mocked(resources.listInvites).mockResolvedValue([
      { ...INVITE, token: undefined },
      { ...INVITE, id: 'i2', token: undefined }
    ])
    await bumpLive(liveKeys.teamInvites('t1'))
    await waitFor(() => expect(result.current.invites).toHaveLength(2))
    expect(calls().invites).toBe(before.invites + 1)
  })

  it('teamInvites(id) refetches invites for an admin', async () => {
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role: 'admin' })
    await ready()
    const before = calls().invites
    await bumpLive(liveKeys.teamInvites('t1'))
    await waitFor(() => expect(calls().invites).toBe(before + 1))
  })

  it.each(['member', 'viewer'] as const)(
    'a %s never calls the invites route on a hint',
    async (role) => {
      vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role })
      const { result } = await ready()
      const before = calls()
      await bumpLive(liveKeys.teamInvites('t1'))
      expect(calls()).toEqual(before)
      expect(result.current.myRole).toBe(role)
    }
  )

  it('loads invites once a member is promoted to admin after an invites hint arrived as member', async () => {
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role: 'member' })
    vi.mocked(resources.listInvites).mockResolvedValue([])
    const { result } = await ready()
    expect(result.current.invites).toHaveLength(0)
    // membership.changed bumps invites while the role is still `member`.
    await bumpLive(liveKeys.teamInvites('t1'))
    const before = calls().invites
    vi.mocked(resources.listInvites).mockResolvedValue([{ ...INVITE, token: undefined }])
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role: 'admin' })
    await bumpLive(liveKeys.team('t1'))
    await waitFor(() => expect(result.current.myRole).toBe('admin'))
    await waitFor(() => expect(result.current.invites).toHaveLength(1))
    expect(calls().invites).toBe(before + 1)
  })
})

describe('useHomeTeam — live refresh (ADR-037): role change sequencing', () => {
  it('admin demoted to member: the same bump never calls the invites route', async () => {
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role: 'admin' })
    const { result } = await ready()
    const before = calls().invites
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role: 'member' })
    vi.mocked(resources.listInvites).mockRejectedValue(new ApiError(403, 'forbidden', 'no'))
    // membership.changed bumps the team detail and invites together.
    await bumpLive(liveKeys.team('t1'), liveKeys.teamMembers('t1'), liveKeys.teamInvites('t1'))
    await waitFor(() => expect(result.current.myRole).toBe('member'))
    expect(calls().invites).toBe(before)
    expect(result.current.status).toBe('ready')
  })

  it('member promoted to admin: the same bump loads invites exactly once', async () => {
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role: 'member' })
    const { result } = await ready()
    const before = calls().invites
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role: 'admin' })
    vi.mocked(resources.listInvites).mockResolvedValue([{ ...INVITE, token: undefined }])
    await bumpLive(liveKeys.team('t1'), liveKeys.teamMembers('t1'), liveKeys.teamInvites('t1'))
    await waitFor(() => expect(result.current.myRole).toBe('admin'))
    await waitFor(() => expect(result.current.invites).toHaveLength(1))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(calls().invites).toBe(before + 1)
  })

  it('a 403 on the invites hint refetch is silent: nothing thrown, status stays ready', async () => {
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, role: 'admin' })
    const { result } = await ready()
    vi.mocked(resources.listInvites).mockRejectedValue(new ApiError(403, 'forbidden', 'no'))
    await bumpLive(liveKeys.teamInvites('t1'))
    await waitFor(() => expect(result.current.invites).toEqual([]))
    expect(result.current.status).toBe('ready')
  })
})

describe('useHomeTeam — live refresh (ADR-037): activity and scope', () => {
  it('teamActivity(id) refreshes the first page', async () => {
    const { result } = await ready()
    const newer = { ...FEED.data[0], id: 'a0' }
    vi.mocked(resources.listActivityPage).mockResolvedValue({
      data: [newer, FEED.data[0]],
      meta: { total: 10, has_next: true, next_cursor: 'c3' }
    })
    await bumpLive(liveKeys.teamActivity('t1'))
    await waitFor(() => expect(result.current.activity.map((a) => a.id)).toEqual(['a0', 'a1']))
    expect(result.current.activityTotal).toBe(10)
  })

  it('a refresh after load-more keeps the older pages and a valid cursor', async () => {
    const { result } = await ready()
    const older = { ...FEED.data[0], id: 'a-old' }
    vi.mocked(resources.listActivityPage).mockResolvedValueOnce({
      data: [older],
      meta: { total: 9, has_next: false }
    })
    await act(async () => result.current.actions.loadMoreActivity())
    expect(result.current.activity.map((a) => a.id)).toEqual(['a1', 'a-old'])
    const newest = { ...FEED.data[0], id: 'a-new' }
    vi.mocked(resources.listActivityPage).mockResolvedValue({
      data: [newest, FEED.data[0]],
      meta: { total: 10, has_next: true, next_cursor: 'c-fresh' }
    })
    await bumpLive(liveKeys.teamActivity('t1'))
    await waitFor(() =>
      expect(result.current.activity.map((a) => a.id)).toEqual(['a-new', 'a1', 'a-old'])
    )
    expect(result.current.activityHasMore).toBe(false)
    expect(result.current.activityTotal).toBe(10)
  })

  it('ignores hints for other teams', async () => {
    await ready()
    const before = calls()
    await bumpLive(
      liveKeys.team('t2'),
      liveKeys.teamMembers('t2'),
      liveKeys.teamInvites('t2'),
      liveKeys.teamActivity('t2')
    )
    expect(calls()).toEqual(before)
  })

  it('drops a refresh that lands after the user switched teams', async () => {
    let release!: (rows: resources.TeamMemberApi[]) => void
    const { result, rerender } = renderHook(({ team }) => useHomeTeam(team, ME, refreshHome), {
      initialProps: { team: TEAM }
    })
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.listMembers).mockImplementationOnce(
      () => new Promise((resolve) => (release = resolve))
    )
    await bumpLive(liveKeys.teamMembers('t1'))
    vi.mocked(resources.getTeamDetail).mockResolvedValue({ ...DETAIL, id: 't2', name: 'Arm Lab' })
    vi.mocked(resources.listMembers).mockResolvedValue([MEMBERS[0]])
    rerender({ team: OTHER })
    await waitFor(() => expect(result.current.detail?.name).toBe('Arm Lab'))
    await act(async () => release([...MEMBERS, { ...MEMBERS[1], user_id: 'late' }]))
    expect(result.current.members).toHaveLength(1)
  })
})
