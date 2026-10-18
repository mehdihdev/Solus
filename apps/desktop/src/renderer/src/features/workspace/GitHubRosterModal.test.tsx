// SOLUSDEV-216 T9: the org roster — statuses, invite only for not_on_solus,
// the one-time token shown once, cursor pagination, named refusals.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { GithubOrgMember } from '../../lib/api/resources.teamGithub'
import { useSettingsStore } from '../../store/settingsStore'
import { GitHubRosterModal } from './GitHubRosterModal'
import type { TeamGithubActions } from './useTeamGithub'

const member = (id: number, status: GithubOrgMember['solus_status']): GithubOrgMember => ({
  github_id: id,
  github_login: `user${id}`,
  avatar_url: `https://avatars.example/${id}`,
  solus_status: status
})

type RosterActions = Pick<TeamGithubActions, 'loadRoster' | 'inviteMember'>

function makeActions(overrides: Partial<RosterActions> = {}): RosterActions {
  return {
    loadRoster: vi.fn(async () => ({
      ok: true as const,
      items: [member(1, 'member'), member(2, 'invited'), member(3, 'not_on_solus')],
      cursor: null
    })),
    inviteMember: vi.fn(async () => ({ ok: true as const, token: 'one-time-token' })),
    ...overrides
  }
}

const open = (actions: RosterActions, onClose = vi.fn(), onUpgrade?: () => void): void => {
  render(
    <GitHubRosterModal actions={actions} login="fsae-ev" onClose={onClose} onUpgrade={onUpgrade} />
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  useSettingsStore.setState({ solMode: 'Guide' })
})

describe('GitHubRosterModal', () => {
  it('lists members with a status chip, and Invite only for not_on_solus', async () => {
    open(makeActions())
    expect(await screen.findByText('user1')).toBeInTheDocument()
    expect(screen.getByText('On team')).toBeInTheDocument()
    expect(screen.getByText('Invited')).toBeInTheDocument()
    const buttons = screen.getAllByRole('button', { name: /^invite/i })
    expect(buttons).toHaveLength(1)
    expect(buttons[0]).toHaveAccessibleName('Invite user3')
  })

  it('has no bulk invite control', async () => {
    open(makeActions())
    await screen.findByText('user1')
    expect(screen.queryByRole('button', { name: /invite all|bulk|add all/i })).toBeNull()
  })

  it('renders hostile logins as text', async () => {
    const hostile = { ...member(9, 'not_on_solus'), github_login: '<b>x</b>' }
    open(
      makeActions({
        loadRoster: vi.fn(async () => ({ ok: true as const, items: [hostile], cursor: null }))
      })
    )
    expect(await screen.findByText('<b>x</b>')).toBeInTheDocument()
    expect(document.querySelector('b')).toBeNull()
  })

  it('shows the one-time token after an invite, once, and flips the row to Invited', async () => {
    const actions = makeActions()
    open(actions)
    await userEvent.click(await screen.findByRole('button', { name: 'Invite user3' }))
    expect(actions.inviteMember).toHaveBeenCalledWith(member(3, 'not_on_solus'))
    expect(await screen.findByTestId('invite-token')).toHaveTextContent('one-time-token')
    // Done twice because the token is uncopied
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(/won't see this token again/i)
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(screen.queryByTestId('invite-token')).toBeNull()
    expect(screen.queryByText('one-time-token')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Invite user3' })).toBeNull()
    expect(screen.getAllByText('Invited')).toHaveLength(2)
  })

  it('Done closes at once after the token is copied', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    open(makeActions())
    await userEvent.click(await screen.findByRole('button', { name: 'Invite user3' }))
    await userEvent.click(await screen.findByRole('button', { name: /copy token/i }))
    expect(writeText).toHaveBeenCalledWith('one-time-token')
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(screen.queryByTestId('invite-token')).toBeNull()
  })

  it('names not_an_org_member and keeps the row', async () => {
    open(
      makeActions({
        inviteMember: vi.fn(async () => ({
          ok: false as const,
          reason: 'not_an_org_member' as const
        }))
      })
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Invite user3' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/no longer a member/i)
  })

  it('names a plan limit with Upgrade, and a generic failure', async () => {
    const onUpgrade = vi.fn()
    const inviteMember = vi
      .fn<RosterActions['inviteMember']>()
      .mockResolvedValueOnce({
        ok: false,
        reason: 'plan_limit',
        limit: { limit: 'max_members', current: 3, max: 3, message: 'Plan allows 3 members' }
      })
      .mockResolvedValueOnce({ ok: false, reason: 'failed' })
    open(makeActions({ inviteMember }), vi.fn(), onUpgrade)
    await userEvent.click(await screen.findByRole('button', { name: 'Invite user3' }))
    expect(await screen.findByText('Plan allows 3 members')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /upgrade/i }))
    expect(onUpgrade).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Invite user3' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't create that invite/i)
  })

  it('paginates with Load more, appending the next page by cursor', async () => {
    const loadRoster = vi
      .fn<RosterActions['loadRoster']>()
      .mockResolvedValueOnce({ ok: true, items: [member(1, 'member')], cursor: 'c2' })
      .mockResolvedValueOnce({ ok: true, items: [member(4, 'not_on_solus')], cursor: null })
    open(makeActions({ loadRoster }))
    await screen.findByText('user1')
    await userEvent.click(screen.getByRole('button', { name: /load more/i }))
    expect(loadRoster).toHaveBeenLastCalledWith('c2')
    expect(await screen.findByText('user4')).toBeInTheDocument()
    expect(screen.getByText('user1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /load more/i })).toBeNull()
  })

  it('shows an empty state and a load failure', async () => {
    const first = render(
      <GitHubRosterModal
        actions={makeActions({
          loadRoster: vi.fn(async () => ({ ok: true as const, items: [], cursor: null }))
        })}
        login="fsae-ev"
        onClose={vi.fn()}
      />
    )
    expect(await screen.findByText(/no members/i)).toBeInTheDocument()
    first.unmount()
    open(makeActions({ loadRoster: vi.fn(async () => ({ ok: false as const })) }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't load/i)
  })

  it('titles the dialog with the org login and closes', async () => {
    const onClose = vi.fn()
    open(makeActions(), onClose)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/fsae-ev/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^close$/i }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})
