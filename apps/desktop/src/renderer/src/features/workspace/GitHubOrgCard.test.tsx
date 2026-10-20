// SOLUSDEV-216 T9: every state of the GITHUB ORGANIZATION card (home.md).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { TeamInstallation } from '../../lib/api/resources.teamGithub'
import { useSettingsStore } from '../../store/settingsStore'
import { githubText } from './githubOrgCopy'
import { GitHubOrgCard } from './GitHubOrgCard'
import type * as hook from './useTeamGithub'

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
      inviteMember: vi.fn(),
      refresh: vi.fn(async () => undefined)
    },
    ...overrides
  }
  current = value
  return value
}

let current: hook.TeamGithub

const renderCard = (canManage = true, onUpgrade?: () => void): void => {
  render(
    <GitHubOrgCard
      github={current}
      teamName="Strider"
      canManage={canManage}
      onUpgrade={onUpgrade}
    />
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  useSettingsStore.setState({ solMode: 'Guide' })
})

describe('GitHubOrgCard', () => {
  it('names the active team as the link target, as text', () => {
    mockGithub()
    render(<GitHubOrgCard github={current} teamName="<b>Strider</b>" canManage />)
    expect(screen.getByText('<b>Strider</b>').tagName).toBe('STRONG')
    expect(screen.getByText(/Link a GitHub organization to/)).toBeInTheDocument()
  })

  it('only managers see the link target', () => {
    mockGithub()
    renderCard(false)
    expect(screen.queryByText(/Link a GitHub organization to/)).toBeNull()
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
    const { container } = render(<GitHubOrgCard github={current} teamName="Strider" canManage />)
    expect(container.querySelector('img[onerror]')).toBeNull()
    expect(screen.getAllByText('<img src=x onerror=alert(1)>').length).toBeGreaterThan(0)
  })

  it('suspended: warns that syncs are paused', () => {
    mockGithub({ installation: { ...INSTALLATION, status: 'suspended' } })
    renderCard()
    expect(screen.getByText(/suspended on github/i)).toBeInTheDocument()
  })

  it('has no roster button: the org members list is inline on Home now', () => {
    mockGithub({ installation: INSTALLATION })
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
    await userEvent.click(screen.getByRole('button', { name: 'Unlink' }))
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
    await userEvent.click(screen.getByRole('button', { name: 'Unlink' }))
    expect(
      within(screen.getByRole('dialog')).getByText(/disconnects 4 project sources/i)
    ).toBeInTheDocument()
  })

  it('unlink: cancel does nothing; a failure is named', async () => {
    const github = mockGithub({ installation: INSTALLATION })
    vi.mocked(github.actions.unlink).mockResolvedValue({ ok: false })
    renderCard()
    await userEvent.click(screen.getByRole('button', { name: /more actions/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Unlink' }))
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
      ['installation_admin_required', /only an owner of this organization/i],
      ['install_state_invalid', /expired or was already used/i],
      ['github_app_unconfigured', /aren't set up on this server/i]
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
      const first = render(<GitHubOrgCard github={current} teamName="Strider" canManage />)
      expect(screen.getByRole('alert')).toHaveTextContent(/cancelled/i)
      first.unmount()
      mockGithub({ notice: { kind: 'failed', reason: 'error', message: null } })
      const second = render(<GitHubOrgCard github={current} teamName="Strider" canManage />)
      expect(screen.getByRole('alert')).toHaveTextContent(/couldn't finish linking/i)
      second.unmount()
      mockGithub({ notice: { kind: 'failed', reason: 'no_bridge', message: null } })
      render(<GitHubOrgCard github={current} teamName="Strider" canManage />)
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

  it('shows a spinner while loading', () => {
    mockGithub({ status: 'loading' })
    render(<GitHubOrgCard github={current} teamName="Strider" canManage />)
    expect(screen.queryByRole('button', { name: /link organization/i })).toBeNull()
  })

  it.each(['Guide', 'Expert'] as const)(
    'offline (%s): a one-line note with Retry that refreshes, and no link action',
    async (mode) => {
      useSettingsStore.setState({ solMode: mode })
      const github = mockGithub({ status: 'offline' })
      render(<GitHubOrgCard github={current} teamName="Strider" canManage />)
      expect(screen.getByRole('status')).toHaveTextContent(githubText('offline_note', mode))
      expect(screen.queryByRole('button', { name: /link organization/i })).toBeNull()
      await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
      expect(github.actions.refresh).toHaveBeenCalledTimes(1)
    }
  )

  it('the Linked by line follows the SOL mode', () => {
    mockGithub({ installation: INSTALLATION })
    const { unmount } = render(<GitHubOrgCard github={current} teamName="Strider" canManage />)
    expect(screen.getByText(/Solus can read all repositories/)).toBeInTheDocument()
    unmount()
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<GitHubOrgCard github={current} teamName="Strider" canManage />)
    expect(screen.getByText(/^Linked by Maya K · 3d ago · all repos$/)).toBeInTheDocument()
  })

  describe('overflow disclosure', () => {
    const open = async (): Promise<HTMLElement> => {
      mockGithub({ installation: INSTALLATION })
      render(
        <>
          <GitHubOrgCard github={current} teamName="Strider" canManage />
          <button>elsewhere</button>
        </>
      )
      const trigger = screen.getByRole('button', { name: /more actions/i })
      await userEvent.click(trigger)
      return trigger
    }

    it('is a disclosure, not an ARIA menu', async () => {
      const trigger = await open()
      expect(trigger).toHaveAttribute('aria-expanded', 'true')
      expect(trigger).not.toHaveAttribute('aria-haspopup')
      const panel = document.getElementById(trigger.getAttribute('aria-controls') ?? '')
      expect(panel).not.toBeNull()
      expect(screen.queryByRole('menu')).toBeNull()
      expect(screen.queryByRole('menuitem')).toBeNull()
    })

    it('closes on Escape and returns focus to the trigger', async () => {
      const trigger = await open()
      await userEvent.tab()
      expect(screen.getByRole('button', { name: 'Unlink' })).toHaveFocus()
      await userEvent.keyboard('{Escape}')
      expect(screen.queryByRole('button', { name: 'Unlink' })).toBeNull()
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
      expect(trigger).toHaveFocus()
    })

    it('opens from the keyboard and closes again with Escape', async () => {
      mockGithub({ installation: INSTALLATION })
      renderCard()
      const trigger = screen.getByRole('button', { name: /more actions/i })
      trigger.focus()
      await userEvent.keyboard('{Enter}')
      expect(trigger).toHaveAttribute('aria-expanded', 'true')
      await userEvent.keyboard('{Escape}')
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
      expect(trigger).toHaveFocus()
    })

    it('closes on an outside click', async () => {
      const trigger = await open()
      await userEvent.click(screen.getByRole('button', { name: 'elsewhere' }))
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
    })

    it('closes when focus tabs out of it', async () => {
      const trigger = await open()
      await userEvent.tab()
      await userEvent.tab()
      expect(screen.getByRole('button', { name: 'elsewhere' })).toHaveFocus()
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
    })

    it('Unlink closes the disclosure and opens a labelled confirm dialog', async () => {
      await open()
      await userEvent.click(screen.getByRole('button', { name: 'Unlink' }))
      expect(screen.getByRole('dialog', { name: 'Unlink GitHub organization' })).toBeInTheDocument()
      await userEvent.keyboard('{Escape}')
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(screen.getByRole('button', { name: /more actions/i })).toHaveFocus()
    })
  })
})
