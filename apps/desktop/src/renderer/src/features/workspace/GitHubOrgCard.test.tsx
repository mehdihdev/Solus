// SOLUSDEV-216 T9: every state of the GITHUB ORGANIZATION card (home.md).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { TeamInstallation } from '../../lib/api/resources.teamGithub'
import { useSettingsStore } from '../../store/settingsStore'
import { GitHubOrgCard } from './GitHubOrgCard'
import * as hook from './useTeamGithub'

vi.mock('./useTeamGithub', () => ({ useTeamGithub: vi.fn() }))
vi.mock('./GitHubRosterModal', () => ({
  GitHubRosterModal: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="roster-modal">
      <button onClick={onClose}>close-roster</button>
    </div>
  )
}))

const INSTALLATION: TeamInstallation = {
  id: 'i1',
  provider: 'github',
  account_login: 'fsae-ev',
  account_type: 'Organization',
  account_avatar_url: 'https://avatars.example/1',
  repository_selection: 'all',
  status: 'active',
  linked_by: { user_id: 'u1', name: 'Maya K' },
  linked_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
  html_url: 'https://github.com/fsae-ev',
  manage_url: 'https://github.com/organizations/fsae-ev/settings/installations/1'
}

function mockGithub(overrides: Partial<hook.TeamGithub> = {}): hook.TeamGithub {
  const value: hook.TeamGithub = {
    status: 'ready',
    installation: null,
    repoCount: null,
    unconfigured: false,
    linking: false,
    notice: null,
    actions: {
      link: vi.fn(async () => undefined),
      unlink: vi.fn(async () => ({
        ok: true as const,
        disabledSources: 3,
        manageUrl: 'https://github.com/organizations/fsae-ev/settings/installations/1'
      })),
      loadRoster: vi.fn(),
      inviteMember: vi.fn(),
      refresh: vi.fn(async () => undefined)
    },
    ...overrides
  }
  vi.mocked(hook.useTeamGithub).mockReturnValue(value)
  return value
}

const renderCard = (canManage = true, onUpgrade?: () => void): void => {
  render(<GitHubOrgCard teamId="t1" canManage={canManage} onUpgrade={onUpgrade} />)
}

beforeEach(() => {
  vi.resetAllMocks()
  useSettingsStore.setState({ solMode: 'Guide' })
})

describe('GitHubOrgCard', () => {
  it('requests the hook for the given team', () => {
    mockGithub()
    renderCard()
    expect(hook.useTeamGithub).toHaveBeenCalledWith('t1')
  })

  it('unlinked admin: explains and offers Link organization', async () => {
    const github = mockGithub()
    renderCard()
    expect(screen.getByText(/everyone on the team can add its repos/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /link organization/i }))
    expect(github.actions.link).toHaveBeenCalledTimes(1)
  })

  it('Expert mode swaps in the terse copy', () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    mockGithub()
    renderCard()
    expect(screen.getByText(/team-wide repo access/i)).toBeInTheDocument()
    expect(screen.queryByText(/everyone on the team can add its repos/i)).toBeNull()
  })

  it('unlinked member: says to ask an admin, with no button', () => {
    mockGithub()
    renderCard(false)
    expect(screen.getByText(/ask a team admin/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /link organization/i })).toBeNull()
  })

  it('unconfigured server: shows the honest note and no button', () => {
    mockGithub({ unconfigured: true })
    renderCard()
    expect(screen.getByText(/aren't set up on this server/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /link organization/i })).toBeNull()
  })

  it('while linking: disables the button and says the owner approves on GitHub', () => {
    mockGithub({ linking: true })
    renderCard()
    expect(screen.getByText(/organization owner approves/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /waiting for github/i })).toBeDisabled()
  })

  it('requested: waits for an org owner', () => {
    mockGithub({ notice: { kind: 'requested' } })
    renderCard()
    expect(screen.getByText(/waiting for an org owner/i)).toBeInTheDocument()
  })

  it('linked: login, type, repo count, linked by, scope', () => {
    mockGithub({ installation: INSTALLATION, repoCount: 6 })
    renderCard()
    expect(screen.getByText('fsae-ev')).toBeInTheDocument()
    expect(screen.getByText(/Organization/)).toBeInTheDocument()
    expect(screen.getByText(/6 repos/)).toBeInTheDocument()
    expect(screen.getByText(/Linked by Maya K/)).toBeInTheDocument()
    expect(screen.getByText(/3d ago/)).toBeInTheDocument()
    expect(screen.getByText(/all repositories/)).toBeInTheDocument()
  })

  it('linked by a removed member reads "a former member"; selected scope; unknown count omitted', () => {
    mockGithub({
      installation: { ...INSTALLATION, linked_by: null, repository_selection: 'selected' },
      repoCount: null
    })
    renderCard()
    expect(screen.getByText(/Linked by a former member/)).toBeInTheDocument()
    expect(screen.getByText(/selected repositories/)).toBeInTheDocument()
    expect(screen.queryByText(/repos$/)).toBeNull()
  })

  it('singular repo count', () => {
    mockGithub({ installation: INSTALLATION, repoCount: 1 })
    renderCard()
    expect(screen.getByText(/1 repo(?!s)/)).toBeInTheDocument()
  })

  it('Manage on GitHub is a safe external link', () => {
    mockGithub({ installation: INSTALLATION })
    renderCard(false)
    const link = screen.getByRole('link', { name: /manage on github/i })
    expect(link).toHaveAttribute('href', INSTALLATION.manage_url)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('does not render a non-https manage_url as a link', () => {
    mockGithub({ installation: { ...INSTALLATION, manage_url: 'javascript:alert(1)' } })
    renderCard()
    expect(screen.queryByRole('link', { name: /manage on github/i })).toBeNull()
  })

  it('renders hostile text as text, never HTML', () => {
    mockGithub({
      installation: { ...INSTALLATION, account_login: '<img src=x onerror=alert(1)>' }
    })
    const { container } = render(<GitHubOrgCard teamId="t1" canManage />)
    expect(container.querySelector('img[onerror]')).toBeNull()
    expect(screen.getAllByText('<img src=x onerror=alert(1)>').length).toBeGreaterThan(0)
  })

  it('suspended: warns that syncs are paused', () => {
    mockGithub({ installation: { ...INSTALLATION, status: 'suspended' } })
    renderCard()
    expect(screen.getByText(/suspended on github/i)).toBeInTheDocument()
  })

  it('members button: admin and Organization only', async () => {
    mockGithub({ installation: INSTALLATION })
    const { unmount } = render(<GitHubOrgCard teamId="t1" canManage />)
    await userEvent.click(screen.getByRole('button', { name: /members on github/i }))
    expect(screen.getByTestId('roster-modal')).toBeInTheDocument()
    unmount()

    renderCard(false)
    expect(screen.queryByRole('button', { name: /members on github/i })).toBeNull()
  })

  it('no members button for a User-type installation', () => {
    mockGithub({ installation: { ...INSTALLATION, account_type: 'User' } })
    renderCard()
    expect(screen.queryByRole('button', { name: /members on github/i })).toBeNull()
  })

  it('no overflow menu for non-admins', () => {
    mockGithub({ installation: INSTALLATION })
    renderCard(false)
    expect(screen.queryByRole('button', { name: /more actions/i })).toBeNull()
  })

  it('unlink: confirm, then names the disconnected sources and offers Uninstall on GitHub', async () => {
    const github = mockGithub({ installation: INSTALLATION })
    renderCard()
    await userEvent.click(screen.getByRole('button', { name: /more actions/i }))
    await userEvent.click(screen.getByRole('menuitem', { name: /unlink/i }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/disconnects every project source/i)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: /^unlink$/i }))
    expect(github.actions.unlink).toHaveBeenCalledTimes(1)
    await waitFor(() =>
      expect(screen.getByText(/3 project sources were disconnected/)).toBeVisible()
    )
    expect(screen.getByRole('link', { name: /uninstall on github/i })).toHaveAttribute(
      'href',
      'https://github.com/organizations/fsae-ev/settings/installations/1'
    )
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('unlink confirm names how many sources it disconnects when the API says', async () => {
    mockGithub({ installation: { ...INSTALLATION, bound_source_count: 4 } })
    renderCard()
    await userEvent.click(screen.getByRole('button', { name: /more actions/i }))
    await userEvent.click(screen.getByRole('menuitem', { name: /unlink/i }))
    expect(
      within(screen.getByRole('dialog')).getByText(/disconnects 4 project sources/i)
    ).toBeInTheDocument()
  })

  it('unlink: cancel does nothing; a failure is named', async () => {
    const github = mockGithub({ installation: INSTALLATION })
    vi.mocked(github.actions.unlink).mockResolvedValue({ ok: false })
    renderCard()
    await userEvent.click(screen.getByRole('button', { name: /more actions/i }))
    await userEvent.click(screen.getByRole('menuitem', { name: /unlink/i }))
    await userEvent.click(screen.getByRole('button', { name: /^unlink$/i }))
    expect(await screen.findByText(/couldn't unlink/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  describe('refusals', () => {
    it.each([
      ['already_linked', /already has a github organization linked/i],
      ['installation_linked_elsewhere', /linked to another Solus team — unlink it there first/i],
      ['installation_not_accessible', /couldn't see that installation/i],
      ['install_state_invalid', /expired or was already used/i]
    ] as const)('names %s inline', (code, text) => {
      mockGithub({ notice: { kind: 'refused', code, limit: null } })
      renderCard()
      expect(screen.getByRole('alert')).toHaveTextContent(text)
    })

    it('plan_limit_reached shows the server sentence with Upgrade', async () => {
      const onUpgrade = vi.fn()
      mockGithub({
        notice: {
          kind: 'refused',
          code: 'plan_limit_reached',
          limit: { limit: 'max_integrations', current: 1, max: 1, message: 'Plan allows 1 source' }
        }
      })
      renderCard(true, onUpgrade)
      expect(screen.getByText('Plan allows 1 source')).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: /upgrade/i }))
      expect(onUpgrade).toHaveBeenCalled()
    })

    it('cancelled, failed and no-desktop notices', () => {
      mockGithub({ notice: { kind: 'cancelled' } })
      const first = render(<GitHubOrgCard teamId="t1" canManage />)
      expect(screen.getByRole('alert')).toHaveTextContent(/cancelled/i)
      first.unmount()
      mockGithub({ notice: { kind: 'failed', reason: 'error', message: null } })
      const second = render(<GitHubOrgCard teamId="t1" canManage />)
      expect(screen.getByRole('alert')).toHaveTextContent(/couldn't finish linking/i)
      second.unmount()
      mockGithub({ notice: { kind: 'failed', reason: 'no_bridge', message: null } })
      render(<GitHubOrgCard teamId="t1" canManage />)
      expect(screen.getByRole('alert')).toHaveTextContent(/desktop app/i)
    })

    it('shows the loopback error verbatim as text', () => {
      mockGithub({
        notice: { kind: 'failed', reason: 'loopback', message: 'A sign-in is already in progress.' }
      })
      renderCard()
      expect(screen.getByRole('alert')).toHaveTextContent('A sign-in is already in progress.')
    })
  })

  it('shows a spinner while loading and nothing misleading when offline', () => {
    mockGithub({ status: 'loading' })
    const first = render(<GitHubOrgCard teamId="t1" canManage />)
    expect(screen.queryByRole('button', { name: /link organization/i })).toBeNull()
    first.unmount()
    mockGithub({ status: 'offline' })
    render(<GitHubOrgCard teamId="t1" canManage />)
    expect(screen.queryByRole('button', { name: /link organization/i })).toBeNull()
  })
})
