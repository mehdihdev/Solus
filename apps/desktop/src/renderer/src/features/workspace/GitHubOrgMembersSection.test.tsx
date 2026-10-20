// SOLUSDEV-317: the inline GITHUB ORG MEMBERS section — chips, the assign /
// change / unassign controls, invites, filters, search, paging, and its states.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as gh from '../../lib/api/resources.teamGithub'
import { ApiError } from '../../lib/api/envelope.types'
import { resetLiveRevisions } from '../../store/liveRevisionStore'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { githubText } from './githubOrgCopy'
import {
  ADA,
  ASSIGNED,
  FREE,
  INVITED,
  NOOR,
  SAM,
  SERVER_ASSIGNMENT,
  VERIFIED
} from './githubOrgRoster.fixtures'
import { useGithubAssignFocusStore } from './githubAssignFocusStore'
import { GitHubInviteTokenHost, useGithubInviteTokenStore } from './githubInviteTokenStore'
import {
  GitHubOrgMembersSection,
  type GitHubOrgMembersSectionProps
} from './GitHubOrgMembersSection'

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

function props(over: Partial<GitHubOrgMembersSectionProps> = {}): GitHubOrgMembersSectionProps {
  return {
    teamId: 't1',
    members: [ADA, NOOR, SAM],
    inviteMember: vi.fn(async () => ({ ok: true as const, token: 'one-time-token' })),
    onMembersStale: vi.fn(),
    onLinkStale: vi.fn(),
    onUpgrade: vi.fn(),
    ...over
  }
}

async function mount(over: Partial<GitHubOrgMembersSectionProps> = {}) {
  const p = props(over)
  render(
    <>
      <GitHubOrgMembersSection {...p} />
      <GitHubInviteTokenHost />
    </>
  )
  await screen.findByRole('list', { name: 'GitHub org members' })
  return p
}

const row = (login: string): HTMLElement =>
  screen.getByRole('listitem', { name: new RegExp(`@${login}$`) })

beforeEach(() => {
  vi.resetAllMocks()
  resetLiveRevisions()
  useSettingsStore.setState({ solMode: 'Guide' })
  useGithubAssignFocusStore.setState({ request: null })
  useGithubInviteTokenStore.setState({ reveal: null })
  mocked.list.mockResolvedValue({
    items: [FREE, ASSIGNED, VERIFIED, INVITED],
    total: 4,
    cursor: null
  })
})

describe('GitHubOrgMembersSection — rows', () => {
  it('shows every chip state and the header counts', async () => {
    await mount()
    expect(within(row('octo')).getByText('Not on Solus')).toBeInTheDocument()
    expect(within(row('noor-a')).getByText('Assigned')).toBeInTheDocument()
    expect(within(row('noor-a')).getByText('Noor')).toBeInTheDocument()
    expect(within(row('noor-a')).getByText(/assigned by Ada/)).toBeInTheDocument()
    expect(within(row('sam-v')).getByText('Verified')).toBeInTheDocument()
    expect(within(row('pending-pat')).getByText('Invited')).toBeInTheDocument()
    expect(screen.getByText(githubText('roster_count', 'Guide', { n: 4, m: 2 }))).toBeVisible()
  })

  it('verified rows are read-only and say why', async () => {
    await mount()
    expect(within(row('sam-v')).queryByRole('button')).toBeNull()
    expect(within(row('sam-v')).getByText(githubText('verified_hint', 'Guide'))).toBeVisible()
  })

  it('Invite only on not_on_solus rows; the token is shown once in a modal', async () => {
    const p = await mount()
    expect(screen.getAllByRole('button', { name: /^invite @/i })).toHaveLength(1)
    await userEvent.click(within(row('octo')).getByRole('button', { name: 'Invite @octo' }))
    expect(p.inviteMember).toHaveBeenCalledWith(FREE)
    const dialog = await screen.findByRole('dialog', { name: /invite @octo/i })
    expect(within(dialog).getByTestId('invite-token')).toHaveTextContent('one-time-token')
    await userEvent.click(within(dialog).getByRole('button', { name: /^done$/i }))
    await userEvent.click(within(dialog).getByRole('button', { name: /^done$/i }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(within(row('octo')).getByText('Invited')).toBeInTheDocument()
  })

  it('a plan-limit invite refusal shows Upgrade on the row', async () => {
    const limit = { code: 'plan_limit_reached', message: 'Plan full.' } as never
    const inviteMember = vi.fn(async () => ({
      ok: false as const,
      reason: 'plan_limit' as const,
      limit
    }))
    const p = await mount({ inviteMember })
    await userEvent.click(screen.getByRole('button', { name: 'Invite @octo' }))
    await userEvent.click(await within(row('octo')).findByRole('button', { name: /upgrade/i }))
    expect(p.onUpgrade).toHaveBeenCalled()
  })

  it('renders hostile logins as text and avatars only over https', async () => {
    mocked.list.mockResolvedValue({
      items: [{ ...FREE, github_login: '<img src=x onerror=alert(1)>', avatar_url: 'http://x/a' }],
      total: 1,
      cursor: null
    })
    const { container } = render(<GitHubOrgMembersSection {...props()} />)
    await screen.findByRole('list', { name: 'GitHub org members' })
    expect(container.querySelector('img[onerror]')).toBeNull()
    expect(container.querySelector('img[src^="http:"]')).toBeNull()
  })
})

describe('GitHubOrgMembersSection — assign', () => {
  it('picker excludes teammates linked elsewhere and shows a verified login', async () => {
    await mount()
    await userEvent.click(within(row('octo')).getByRole('button', { name: 'Assign' }))
    const list = screen.getByRole('listbox', { name: 'Teammate for @octo' })
    const names = within(list)
      .getAllByRole('option')
      .map((o) => o.textContent)
    expect(names).toEqual(['Adaada@team.dev', 'Sam@sam-v · verified'])
    expect(within(list).getByRole('option', { name: /Sam/ })).toHaveAttribute(
      'aria-disabled',
      'true'
    )
  })

  it('assigns, then announces on the row', async () => {
    mocked.assign.mockResolvedValue({ ...SERVER_ASSIGNMENT, user_id: 'u1', name: 'Ada' })
    await mount()
    await userEvent.click(within(row('octo')).getByRole('button', { name: 'Assign' }))
    await userEvent.click(screen.getByRole('option', { name: /Ada/ }))
    expect(mocked.assign).toHaveBeenCalledWith('t1', 7, 'u1')
    await waitFor(() =>
      expect(within(row('octo')).getByRole('status')).toHaveTextContent('@octo is now shown as Ada')
    )
    expect(within(row('octo')).getByText('Assigned')).toBeInTheDocument()
  })

  it('Change re-picks on an assigned row', async () => {
    mocked.assign.mockResolvedValue({ ...SERVER_ASSIGNMENT, user_id: 'u1', name: 'Ada' })
    await mount()
    await userEvent.click(within(row('noor-a')).getByRole('button', { name: 'Change' }))
    await userEvent.click(screen.getByRole('option', { name: /Ada/ }))
    expect(mocked.assign).toHaveBeenCalledWith('t1', 8, 'u1')
  })

  it('Unassign confirms inline, then clears', async () => {
    mocked.unassign.mockResolvedValue(undefined)
    await mount()
    await userEvent.click(within(row('noor-a')).getByRole('button', { name: 'Unassign' }))
    expect(
      within(row('noor-a')).getByText(/Remove the label linking @noor-a to Noor/)
    ).toBeVisible()
    expect(mocked.unassign).not.toHaveBeenCalled()
    await userEvent.click(within(row('noor-a')).getByRole('button', { name: 'Confirm unassign' }))
    expect(mocked.unassign).toHaveBeenCalledWith('t1', 8)
    await waitFor(() => expect(within(row('noor-a')).getByText('Not on Solus')).toBeVisible())
  })

  it('names the other login on member_already_assigned and offers to find it', async () => {
    mocked.assign.mockRejectedValue(
      new ApiError(409, 'member_already_assigned', 'm', [{ github_id: 8, github_login: 'noor-a' }])
    )
    await mount()
    await userEvent.click(within(row('octo')).getByRole('button', { name: 'Assign' }))
    await userEvent.click(screen.getByRole('option', { name: /Ada/ }))
    expect(await within(row('octo')).findByRole('alert')).toHaveTextContent('@noor-a')
    await userEvent.click(within(row('octo')).getByRole('button', { name: 'Find @noor-a' }))
    expect(screen.getByRole('searchbox', { name: /search org members/i })).toHaveValue('noor-a')
  })
})

describe('GitHubOrgMembersSection — browsing', () => {
  it.each([
    ['On team', ['noor-a', 'sam-v']],
    ['Not on Solus', ['octo', 'pending-pat']]
  ])('filter %s', async (filter, logins) => {
    await mount()
    await userEvent.click(screen.getByRole('radio', { name: filter }))
    const items = within(screen.getByRole('list', { name: 'GitHub org members' })).getAllByRole(
      'listitem'
    )
    expect(items.map((i) => i.getAttribute('aria-label'))).toEqual(logins.map((l) => `@${l}`))
  })

  it('Unassigned teammates lists teammates and assigns from their side', async () => {
    mocked.assign.mockResolvedValue({ ...SERVER_ASSIGNMENT, user_id: 'u1', name: 'Ada' })
    await mount()
    await userEvent.click(screen.getByRole('radio', { name: 'Unassigned teammates' }))
    const list = screen.getByRole('list', { name: 'Unassigned teammates' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(1)
    await userEvent.click(within(list).getByRole('button', { name: 'Pick GitHub account' }))
    await userEvent.click(screen.getByRole('option', { name: /@pending-pat/ }))
    expect(mocked.assign).toHaveBeenCalledWith('t1', 10, 'u1')
  })

  it('searches loaded logins and Load more appends the next page', async () => {
    mocked.list.mockResolvedValueOnce({ items: [FREE], total: 2, cursor: 'c2' })
    mocked.list.mockResolvedValueOnce({ items: [ASSIGNED], total: 2, cursor: null })
    await mount()
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await screen.findByRole('listitem', { name: '@noor-a' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
    await userEvent.type(screen.getByRole('searchbox', { name: /search org members/i }), 'oct')
    expect(screen.queryByRole('listitem', { name: '@noor-a' })).toBeNull()
  })

  it('opens a teammate’s picker when the members list asks', async () => {
    await mount()
    act(() => useGithubAssignFocusStore.getState().requestAssign('t1', 'u1'))
    expect(screen.getByRole('radio', { name: 'Unassigned teammates' })).toBeChecked()
    expect(screen.getByRole('listbox', { name: 'GitHub account for Ada' })).toBeInTheDocument()
    expect(useGithubAssignFocusStore.getState().request).toBeNull()
  })
})

describe('GitHubOrgMembersSection — states', () => {
  it('says so when the org has no members', async () => {
    mocked.list.mockResolvedValue({ items: [], total: 0, cursor: null })
    render(<GitHubOrgMembersSection {...props()} />)
    expect(await screen.findByText(githubText('roster_empty', 'Guide'))).toBeVisible()
  })

  it('a failed load shows a note and Retry', async () => {
    mocked.list.mockRejectedValueOnce(new Error('net'))
    render(<GitHubOrgMembersSection {...props()} />)
    expect(await screen.findByText(githubText('roster_failed', 'Guide'))).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('list', { name: 'GitHub org members' })).toBeInTheDocument()
  })

  it.each<SolMode>(['Guide', 'Expert'])('%s copy for the explainer and header', async (mode) => {
    useSettingsStore.setState({ solMode: mode })
    await mount()
    expect(screen.getByText(githubText('assign_intro', mode))).toBeVisible()
    expect(screen.getByText(githubText('roster_count', mode, { n: 4, m: 2 }))).toBeVisible()
  })

  it('labels the section by its heading', async () => {
    await mount()
    expect(screen.getByRole('region', { name: 'GitHub org members' })).toBeInTheDocument()
  })
})

describe('GitHubOrgMembersSection — review regressions', () => {
  it('the token outlives the section (team switch, demotion, suspension)', async () => {
    const p = props()
    const { rerender } = render(
      <>
        <GitHubOrgMembersSection {...p} />
        <GitHubInviteTokenHost />
      </>
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Invite @octo' }))
    await screen.findByRole('dialog', { name: /invite @octo/i })
    rerender(<GitHubInviteTokenHost />)
    expect(screen.getByTestId('invite-token')).toHaveTextContent('one-time-token')
  })

  it('a members-list request opens the picker once, not on every filter revisit', async () => {
    await mount()
    act(() => useGithubAssignFocusStore.getState().requestAssign('t1', 'u1'))
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('radio', { name: 'All' }))
    await userEvent.click(screen.getByRole('radio', { name: 'Unassigned teammates' }))
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('Unassign confirm takes focus and Cancel returns it to the row', async () => {
    await mount()
    await userEvent.click(within(row('noor-a')).getByRole('button', { name: 'Unassign' }))
    expect(within(row('noor-a')).getByRole('button', { name: 'Confirm unassign' })).toHaveFocus()
    await userEvent.click(within(row('noor-a')).getByRole('button', { name: 'Cancel' }))
    expect(within(row('noor-a')).getByRole('button', { name: 'Change' })).toHaveFocus()
  })
})
