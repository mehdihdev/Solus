// SOLUSDEV-216 T9: the team's GitHub installation layer on Home.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as gh from '../../lib/api/resources.teamGithub'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { liveKeys, resetLiveRevisions } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'
import { useTeamGithub } from './useTeamGithub'
import * as flow from './githubInstallFlow'

vi.mock('../../lib/api/resources.teamGithub', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources.teamGithub')>()),
  getTeamInstallation: vi.fn(),
  listTeamGithubRepos: vi.fn(),
  listTeamGithubMembers: vi.fn(),
  unlinkTeamInstallation: vi.fn(),
  startGithubInstall: vi.fn(),
  completeGithubInstall: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  createInvite: vi.fn()
}))
vi.mock('./githubInstallFlow', () => ({ runGithubInstall: vi.fn() }))
vi.mock('../../lib/desktopBridge', () => ({ getDesktopOAuthBridge: () => null }))

const INSTALLATION: gh.TeamInstallation = {
  id: 'i1',
  provider: 'github',
  account_login: 'fsae-ev',
  account_type: 'Organization',
  account_avatar_url: null,
  repository_selection: 'all',
  status: 'active',
  linked_by: { user_id: 'u1', name: 'Maya K' },
  linked_at: '2026-10-01T00:00:00Z',
  html_url: 'https://github.com/fsae-ev',
  manage_url: 'https://github.com/organizations/fsae-ev/settings/installations/1'
}
const MEMBER: gh.GithubOrgMember = {
  github_id: 7,
  github_login: 'octo',
  avatar_url: 'https://avatars.example/7',
  solus_status: 'not_on_solus'
}

const mocked = {
  installation: vi.mocked(gh.getTeamInstallation),
  repos: vi.mocked(gh.listTeamGithubRepos),
  members: vi.mocked(gh.listTeamGithubMembers),
  unlink: vi.mocked(gh.unlinkTeamInstallation),
  invite: vi.mocked(resources.createInvite),
  run: vi.mocked(flow.runGithubInstall)
}

beforeEach(() => {
  vi.resetAllMocks()
  resetLiveRevisions()
  mocked.installation.mockResolvedValue(INSTALLATION)
  mocked.repos.mockResolvedValue({ items: [], total: 6, cursor: null })
})

describe('useTeamGithub', () => {
  it('stays idle and makes no request without a collaborative team', () => {
    const { result } = renderHook(() => useTeamGithub(null))
    expect(result.current.status).toBe('idle')
    expect(mocked.installation).not.toHaveBeenCalled()
  })

  it('loads the installation and the repo count from the listing meta', async () => {
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.installation).toEqual(INSTALLATION)
    expect(result.current.repoCount).toBe(6)
    expect(mocked.repos).toHaveBeenCalledWith('t1', { limit: 1 })
  })

  it('has no installation and skips the repo count when unlinked', async () => {
    mocked.installation.mockResolvedValue(null)
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.installation).toBeNull()
    expect(mocked.repos).not.toHaveBeenCalled()
  })

  it('flags github_app_unconfigured instead of failing', async () => {
    mocked.installation.mockRejectedValue(new ApiError(503, 'github_app_unconfigured', 'x'))
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.unconfigured).toBe(true)
    expect(result.current.installation).toBeNull()
  })

  it('goes offline on an unrelated failure', async () => {
    mocked.installation.mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })

  it('keeps the repo count null when only the count fails', async () => {
    mocked.repos.mockRejectedValue(new Error('x'))
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.repoCount).toBeNull()
  })

  it('refetches quietly when team.updated arrives for this team', async () => {
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    mocked.installation.mockResolvedValue({ ...INSTALLATION, status: 'suspended' })
    await bumpLive(liveKeys.team('t1'))
    await waitFor(() => expect(result.current.installation?.status).toBe('suspended'))
    expect(result.current.status).toBe('ready')
  })

  it('ignores a live hint for another team', async () => {
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    mocked.installation.mockClear()
    await bumpLive(liveKeys.team('t2'))
    expect(mocked.installation).not.toHaveBeenCalled()
  })

  it('link(): a linked outcome refetches the card', async () => {
    mocked.installation.mockResolvedValueOnce(null)
    mocked.run.mockResolvedValue({ kind: 'linked', installation: INSTALLATION })
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.link()
    })
    await waitFor(() => expect(result.current.installation).toEqual(INSTALLATION))
    expect(result.current.notice).toBeNull()
  })

  it('link(): requested leaves a pending notice and no installation', async () => {
    mocked.installation.mockResolvedValue(null)
    mocked.run.mockResolvedValue({ kind: 'requested' })
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.link()
    })
    expect(result.current.notice).toEqual({ kind: 'requested' })
    expect(result.current.linking).toBe(false)
  })

  it('link(): a refusal is kept as the notice, and a new attempt clears it', async () => {
    mocked.installation.mockResolvedValue(null)
    mocked.run.mockResolvedValueOnce({ kind: 'refused', code: 'already_linked', limit: null })
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.link()
    })
    expect(result.current.notice).toMatchObject({ kind: 'refused', code: 'already_linked' })
    mocked.run.mockResolvedValueOnce({ kind: 'cancelled' })
    await act(async () => {
      await result.current.actions.link()
    })
    expect(result.current.notice).toEqual({ kind: 'cancelled' })
  })

  it('unlink(): returns the disconnected count and clears the installation', async () => {
    mocked.unlink.mockResolvedValue({ disabled_sources: 2, manage_url: 'https://github.com/m' })
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    mocked.installation.mockResolvedValue(null)
    let outcome: Awaited<ReturnType<typeof result.current.actions.unlink>> | undefined
    await act(async () => {
      outcome = await result.current.actions.unlink()
    })
    expect(outcome).toEqual({ ok: true, disabledSources: 2, manageUrl: 'https://github.com/m' })
    await waitFor(() => expect(result.current.installation).toBeNull())
  })

  it('unlink(): a failure is reported, not thrown', async () => {
    mocked.unlink.mockRejectedValue(new Error('x'))
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let outcome: unknown
    await act(async () => {
      outcome = await result.current.actions.unlink()
    })
    expect(outcome).toEqual({ ok: false })
    expect(result.current.installation).toEqual(INSTALLATION)
  })

  it('loadRoster() passes the cursor and returns the page', async () => {
    mocked.members.mockResolvedValue({ items: [MEMBER], total: 1, cursor: 'c2' })
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let page: unknown
    await act(async () => {
      page = await result.current.actions.loadRoster('c1')
    })
    expect(mocked.members).toHaveBeenCalledWith('t1', { cursor: 'c1' })
    expect(page).toEqual({ ok: true, items: [MEMBER], cursor: 'c2' })
  })

  it('loadRoster() reports a failure', async () => {
    mocked.members.mockRejectedValue(new Error('x'))
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let page: unknown
    await act(async () => {
      page = await result.current.actions.loadRoster()
    })
    expect(page).toEqual({ ok: false })
  })

  it('inviteMember() posts the GitHub target as role member and returns the token', async () => {
    mocked.invite.mockResolvedValue({ id: 'inv', team_id: 't1', token: 'tok-1' } as never)
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let outcome: unknown
    await act(async () => {
      outcome = await result.current.actions.inviteMember(MEMBER)
    })
    expect(mocked.invite).toHaveBeenCalledWith('t1', {
      github_user_id: 7,
      github_login: 'octo',
      role: 'member'
    })
    expect(outcome).toEqual({ ok: true, token: 'tok-1' })
  })

  it('inviteMember() names not_an_org_member and plan limits', async () => {
    const { result } = renderHook(() => useTeamGithub('t1'))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    mocked.invite.mockRejectedValueOnce(new ApiError(422, 'not_an_org_member', 'x'))
    let outcome: unknown
    await act(async () => {
      outcome = await result.current.actions.inviteMember(MEMBER)
    })
    expect(outcome).toEqual({ ok: false, reason: 'not_an_org_member' })
    mocked.invite.mockRejectedValueOnce(new ApiError(409, 'plan_limit_reached', 'cap', []))
    await act(async () => {
      outcome = await result.current.actions.inviteMember(MEMBER)
    })
    expect(outcome).toMatchObject({ ok: false, reason: 'plan_limit' })
    mocked.invite.mockRejectedValueOnce(new Error('x'))
    await act(async () => {
      outcome = await result.current.actions.inviteMember(MEMBER)
    })
    expect(outcome).toEqual({ ok: false, reason: 'failed' })
  })
})
