// SOLUSDEV-317: the card and the org members section share one useTeamGithub;
// the section shows only for a manager with a live Organization link.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import type { TeamInstallation } from '../../lib/api/resources.teamGithub'
import { liveKeys, resetLiveRevisions, useLiveRevisionStore } from '../../store/liveRevisionStore'
import { ADA } from './githubOrgRoster.fixtures'
import { TeamGithubPanel, type TeamGithubPanelProps } from './TeamGithubPanel'
import * as hook from './useTeamGithub'

vi.mock('./useTeamGithub', () => ({ useTeamGithub: vi.fn() }))
vi.mock('./GitHubOrgCard', () => ({
  GitHubOrgCard: (p: { teamName: string; github: hook.TeamGithub }) => (
    <div data-testid="card" data-team={p.teamName}>
      <button onClick={() => void p.github.actions.link()}>link</button>
    </div>
  )
}))
vi.mock('./GitHubOrgMembersSection', () => ({
  GitHubOrgMembersSection: (p: {
    autoFocus?: boolean
    onLinkStale: () => void
    onMembersStale: () => void
  }) => (
    <div data-testid="section" data-autofocus={String(Boolean(p.autoFocus))}>
      <button onClick={p.onLinkStale}>link-stale</button>
      <button onClick={p.onMembersStale}>members-stale</button>
    </div>
  )
}))

const ORG: TeamInstallation = {
  id: 'i1',
  provider: 'github',
  account_login: 'fsae-ev',
  account_type: 'Organization',
  account_avatar_url: null,
  repository_selection: 'all',
  status: 'active',
  linked_by: null,
  linked_at: '2026-10-01T00:00:00Z',
  html_url: 'https://github.com/fsae-ev',
  manage_url: 'https://github.com/organizations/fsae-ev/settings/installations/1'
}

function github(installation: TeamInstallation | null): hook.TeamGithub {
  return {
    status: 'ready',
    installation,
    repoCount: null,
    unconfigured: false,
    linking: false,
    notice: null,
    actions: {
      link: vi.fn(async () => undefined),
      unlink: vi.fn(),
      inviteMember: vi.fn(),
      refresh: vi.fn(async () => undefined)
    }
  }
}

const props = (over: Partial<TeamGithubPanelProps> = {}): TeamGithubPanelProps => ({
  teamId: 't1',
  teamName: 'Strider',
  canManage: true,
  members: [ADA],
  onSectionChange: vi.fn(),
  ...over
})

beforeEach(() => {
  vi.resetAllMocks()
  resetLiveRevisions()
})

describe('TeamGithubPanel', () => {
  it('reads the active team and names it on the card', () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(null))
    render(<TeamGithubPanel {...props()} />)
    expect(hook.useTeamGithub).toHaveBeenCalledWith('t1')
    expect(screen.getByTestId('card')).toHaveAttribute('data-team', 'Strider')
  })

  it.each([
    ['no link', null, true],
    ['a User link', { ...ORG, account_type: 'User' as const }, true],
    ['a suspended link', { ...ORG, status: 'suspended' as const }, true],
    ['a non-manager', ORG, false]
  ])('no section for %s', (_, installation, canManage) => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(installation))
    const p = props({ canManage })
    render(<TeamGithubPanel {...p} />)
    expect(screen.queryByTestId('section')).toBeNull()
    expect(p.onSectionChange).toHaveBeenLastCalledWith(false)
  })

  it('shows the section for a manager with a live Organization link, and says so', () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(ORG))
    const p = props()
    render(<TeamGithubPanel {...p} />)
    expect(screen.getByTestId('section')).toHaveAttribute('data-autofocus', 'false')
    expect(p.onSectionChange).toHaveBeenLastCalledWith(true)
  })

  it('reports the section gone when it unmounts', () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(ORG))
    const p = props()
    const { unmount } = render(<TeamGithubPanel {...p} />)
    unmount()
    expect(p.onSectionChange).toHaveBeenLastCalledWith(false)
  })

  it('focuses the section after this admin links the org', async () => {
    const before = github(null)
    vi.mocked(hook.useTeamGithub).mockReturnValue(before)
    const { rerender } = render(<TeamGithubPanel {...props()} />)
    await act(async () => screen.getByRole('button', { name: 'link' }).click())
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(ORG))
    rerender(<TeamGithubPanel {...props()} />)
    expect(screen.getByTestId('section')).toHaveAttribute('data-autofocus', 'true')
  })

  it('focuses only once: a later remount does not grab focus', async () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(null))
    const { rerender } = render(<TeamGithubPanel {...props()} />)
    await act(async () => screen.getByRole('button', { name: 'link' }).click())
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(ORG))
    rerender(<TeamGithubPanel {...props()} />)
    vi.mocked(hook.useTeamGithub).mockReturnValue(github({ ...ORG, status: 'suspended' }))
    rerender(<TeamGithubPanel {...props()} />)
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(ORG))
    rerender(<TeamGithubPanel {...props()} />)
    expect(screen.getByTestId('section')).toHaveAttribute('data-autofocus', 'false')
  })

  it('refreshes the card on a stale link and bumps the members on stale members', () => {
    const g = github(ORG)
    vi.mocked(hook.useTeamGithub).mockReturnValue(g)
    render(<TeamGithubPanel {...props()} />)
    screen.getByRole('button', { name: 'link-stale' }).click()
    expect(g.actions.refresh).toHaveBeenCalled()
    const bump = vi.spyOn(useLiveRevisionStore.getState(), 'bump')
    screen.getByRole('button', { name: 'members-stale' }).click()
    expect(bump).toHaveBeenCalledWith([liveKeys.teamMembers('t1')])
  })
})
